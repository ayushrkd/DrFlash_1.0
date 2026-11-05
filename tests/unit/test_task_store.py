"""Unit tests for the Task Store."""

import pytest
from pathlib import Path

from services.contracts.enums import TaskStatus
from services.contracts.models import Task
from services.task_store import TaskStore, InvalidTransitionError


@pytest.fixture
async def store(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    s = TaskStore(db_path=db_path)
    await s.initialize()
    yield s
    await s.close()


class TestTaskCreation:
    @pytest.mark.asyncio
    async def test_create_and_retrieve(self, store: TaskStore):
        task = Task(input_text="Test task")
        created = await store.create_task(task)
        assert created.task_id == task.task_id
        assert created.status == TaskStatus.CREATED

        retrieved = await store.get_task(task.task_id)
        assert retrieved is not None
        assert retrieved.input_text == "Test task"

    @pytest.mark.asyncio
    async def test_list_tasks(self, store: TaskStore):
        for i in range(5):
            await store.create_task(Task(input_text=f"Task {i}"))
        tasks = await store.list_tasks()
        assert len(tasks) == 5

    @pytest.mark.asyncio
    async def test_nonexistent_task_returns_none(self, store: TaskStore):
        result = await store.get_task("nonexistent")
        assert result is None


class TestTaskStateMachine:
    @pytest.mark.asyncio
    async def test_valid_transition(self, store: TaskStore):
        task = Task(input_text="Test")
        await store.create_task(task)

        updated = await store.transition(task.task_id, TaskStatus.UNDERSTANDING)
        assert updated.status == TaskStatus.UNDERSTANDING

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, store: TaskStore):
        task = Task(input_text="Test")
        await store.create_task(task)

        with pytest.raises(InvalidTransitionError):
            await store.transition(task.task_id, TaskStatus.COMPLETED)

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, store: TaskStore):
        task = Task(input_text="Test lifecycle")
        await store.create_task(task)

        await store.transition(task.task_id, TaskStatus.UNDERSTANDING)
        await store.transition(task.task_id, TaskStatus.PLANNED)
        await store.transition(task.task_id, TaskStatus.POLICY_CHECK)
        await store.transition(task.task_id, TaskStatus.RUNNING)
        await store.transition(task.task_id, TaskStatus.VERIFYING)
        result = await store.transition(task.task_id, TaskStatus.COMPLETED)

        assert result.status == TaskStatus.COMPLETED
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancellation_from_any_active_state(self, store: TaskStore):
        for intermediate in [TaskStatus.UNDERSTANDING, TaskStatus.PLANNED]:
            task = Task(input_text=f"Cancel from {intermediate}")
            await store.create_task(task)
            await store.transition(task.task_id, TaskStatus.UNDERSTANDING)
            if intermediate == TaskStatus.PLANNED:
                await store.transition(task.task_id, TaskStatus.PLANNED)
            result = await store.transition(task.task_id, TaskStatus.CANCELLED)
            assert result.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_terminal_states_cannot_transition(self, store: TaskStore):
        task = Task(input_text="Terminal test")
        await store.create_task(task)
        await store.transition(task.task_id, TaskStatus.UNDERSTANDING)
        await store.transition(task.task_id, TaskStatus.FAILED, error="test error")

        with pytest.raises(InvalidTransitionError):
            await store.transition(task.task_id, TaskStatus.RUNNING)


class TestTaskEvents:
    @pytest.mark.asyncio
    async def test_events_recorded(self, store: TaskStore):
        task = Task(input_text="Events test")
        await store.create_task(task)
        await store.transition(task.task_id, TaskStatus.UNDERSTANDING)

        events = await store.get_events(task.task_id)
        assert len(events) >= 2  # create + transition
        assert events[0].event_type == "task.created"

    @pytest.mark.asyncio
    async def test_events_survive_restart(self, tmp_path: Path):
        db_path = str(tmp_path / "persist.db")

        store1 = TaskStore(db_path=db_path)
        await store1.initialize()
        task = Task(input_text="Persist test")
        await store1.create_task(task)
        await store1.transition(task.task_id, TaskStatus.UNDERSTANDING)
        await store1.close()

        store2 = TaskStore(db_path=db_path)
        await store2.initialize()
        retrieved = await store2.get_task(task.task_id)
        events = await store2.get_events(task.task_id)
        await store2.close()

        assert retrieved is not None
        assert retrieved.status == TaskStatus.UNDERSTANDING
        assert len(events) >= 2
