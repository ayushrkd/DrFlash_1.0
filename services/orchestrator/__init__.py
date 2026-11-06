"""Dr. Flash — Task Orchestrator.

Single orchestrator with typed tools and a durable state machine.
Interprets intent, generates plans, dispatches tool calls through
the execution broker, verifies outcomes, and handles recovery.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from services.contracts.enums import TaskStatus
from services.contracts.models import (
    ModelRequest,
    Task,
    TaskEvent,
    TaskPlan,
    TaskStep,
    ToolCall,
)
from services.execution_broker import ExecutionBroker
from services.model_router import ModelRouter
from services.task_store import TaskStore


class Orchestrator:
    """Core task orchestrator: intent → plan → execute → verify."""

    def __init__(
        self,
        task_store: TaskStore,
        model_router: ModelRouter,
        broker: ExecutionBroker,
    ) -> None:
        self._store = task_store
        self._router = model_router
        self._broker = broker

    async def submit_task(self, input_text: str) -> Task:
        """Create a new task and begin processing."""
        task = Task(input_text=input_text)
        task = await self._store.create_task(task)
        return task

    async def process_task(self, task_id: str) -> Task:
        """Run the full task lifecycle: understand → plan → execute → verify."""
        task = await self._store.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        try:
            # Phase 1: Understanding
            task = await self._store.transition(task_id, TaskStatus.UNDERSTANDING)
            intent = await self._understand_intent(task)

            # Phase 2: Planning
            task = await self._store.transition(task_id, TaskStatus.PLANNED)
            plan = await self._create_plan(task, intent)
            await self._store.update_plan(task_id, plan.model_dump_json())
            task.plan = plan

            # Phase 3: Policy Check
            task = await self._store.transition(task_id, TaskStatus.POLICY_CHECK)

            # Phase 4: Execution
            task = await self._store.transition(task_id, TaskStatus.RUNNING)
            results = await self._execute_plan(task, plan)

            # Phase 5: Verification
            task = await self._store.transition(task_id, TaskStatus.VERIFYING)
            all_passed = all(r.get("verification_passed", False) for r in results)

            if all_passed:
                task = await self._store.transition(task_id, TaskStatus.COMPLETED)
            else:
                failed = [r for r in results if not r.get("verification_passed", False)]
                task = await self._store.transition(
                    task_id, TaskStatus.FAILED,
                    error=f"Verification failed for {len(failed)} step(s)"
                )

        except Exception as e:
            try:
                task = await self._store.transition(task_id, TaskStatus.FAILED, error=str(e))
            except Exception:
                pass  # Task may already be in terminal state

        return await self._store.get_task(task_id) or task

    async def cancel_task(self, task_id: str) -> Task:
        """Cancel a running or pending task."""
        return await self._store.transition(task_id, TaskStatus.CANCELLED)

    async def _understand_intent(self, task: Task) -> dict:
        """Use the model to understand the user's intent and extract structure."""
        tools = self._broker.list_tools()
        tool_descriptions = [
            {"tool_id": t.tool_id, "description": t.description, "capabilities": [
                {"action": c.action, "description": c.description}
                for c in t.capabilities
            ]}
            for t in tools
        ]

        request = ModelRequest(
            role="FAST_INTENT",
            messages=[
                {"role": "system", "content": (
                    "You are Dr. Flash, a task planning assistant. Analyze the user's request "
                    "and identify: 1) the goal, 2) required tools, 3) key parameters. "
                    "Be concise and structured."
                )},
                {"role": "user", "content": task.input_text},
            ],
            tools=tool_descriptions,
            task_id=task.task_id,
        )

        response = await self._router.route(request)
        return {
            "understanding": response.content,
            "model": response.model,
            "tokens_used": response.input_tokens + response.output_tokens,
        }

    async def _create_plan(self, task: Task, intent: dict) -> TaskPlan:
        """Generate an execution plan based on intent and available tools."""
        tools = self._broker.list_tools()

        request = ModelRequest(
            role="LOCAL_DIALOG",
            messages=[
                {"role": "system", "content": (
                    "You are Dr. Flash, a task planner. Given the user's request and available tools, "
                    "produce a JSON plan with steps. Each step has: description, tool_id, action, args. "
                    "Keep plans minimal and safe. Only use registered tools. "
                    "Respond with ONLY a JSON array of step objects."
                )},
                {"role": "user", "content": (
                    f"Request: {task.input_text}\n"
                    f"Intent: {intent['understanding']}\n"
                    f"Available tools: {json.dumps([{'tool_id': t.tool_id, 'capabilities': [c.action for c in t.capabilities]} for t in tools])}"
                )},
            ],
            task_id=task.task_id,
        )

        response = await self._router.route(request)

        # Parse plan from model response, with fallback to a simple default
        steps = self._parse_plan_steps(response.content, task.task_id, tools)

        return TaskPlan(
            task_id=task.task_id,
            steps=steps,
            reasoning=response.content,
        )

    def _parse_plan_steps(
        self, content: str, task_id: str, tools: list
    ) -> list[TaskStep]:
        """Parse model output into structured plan steps."""
        # Try JSON parsing first
        try:
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(clean)
            if isinstance(parsed, list):
                steps = []
                for i, item in enumerate(parsed):
                    steps.append(TaskStep(
                        task_id=task_id,
                        description=item.get("description", f"Step {i+1}"),
                        tool_id=item.get("tool_id"),
                        action=item.get("action"),
                        args=item.get("args", {}),
                        order=i,
                    ))
                return steps
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Fallback: create a generic observation step
        tool_ids = [t.tool_id for t in tools]
        default_tool = tool_ids[0] if tool_ids else None

        return [
            TaskStep(
                task_id=task_id,
                description="Observe available resources",
                tool_id=default_tool,
                action="list_files",
                args={"directory": ""},
                order=0,
            ),
        ]

    async def _execute_plan(self, task: Task, plan: TaskPlan) -> list[dict]:
        """Execute each step of the plan through the broker."""
        results = []

        for step in sorted(plan.steps, key=lambda s: s.order):
            if step.tool_id is None or step.action is None:
                results.append({
                    "step_id": step.step_id,
                    "skipped": True,
                    "reason": "No tool/action specified",
                    "verification_passed": True,
                })
                continue

            tool_reg = self._broker._policy.get_tool(step.tool_id)
            if tool_reg is None:
                results.append({
                    "step_id": step.step_id,
                    "skipped": True,
                    "reason": f"Tool {step.tool_id} not registered",
                    "verification_passed": False,
                })
                continue

            call = ToolCall(
                task_id=task.task_id,
                step_id=step.step_id,
                tool_id=step.tool_id,
                tool_version=tool_reg.version,
                action=step.action,
                args=step.args,
                expected_outcome=step.expected_outcome,
            )

            decision, result, verification = await self._broker.dispatch(
                call, task.scope_ids
            )

            step_result = {
                "step_id": step.step_id,
                "tool_id": step.tool_id,
                "action": step.action,
                "policy_allowed": decision.allowed,
                "risk": decision.risk.value,
                "result_success": result.success if result else None,
                "verification_passed": verification.passed if verification else False,
                "error": result.error if result else decision.reason if not decision.allowed else None,
            }
            results.append(step_result)

            # Stop execution on failure (conservative)
            if result and not result.success:
                break

        return results
