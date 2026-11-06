"""Dr. Flash — Independent Outcome Verifier.

Verifies that tool actions actually produced the expected outcome.
"Tool returned success" is not enough — check the destination state.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from services.contracts.enums import EvidenceKind
from services.contracts.models import Evidence, ToolCall, ToolResult, Verification


class OutcomeVerifier:
    """Verifies tool outcomes against expected results using independent checks."""

    async def verify(
        self,
        call: ToolCall,
        result: ToolResult,
        state_before: dict | None = None,
        state_after: dict | None = None,
    ) -> Verification:
        """Run verification checks for a completed tool call."""
        checks: list[dict] = []
        evidence_ids: list[str] = []

        # Check 1: Tool reported success
        checks.append({
            "name": "tool_success",
            "passed": result.success,
            "detail": result.error if not result.success else "Tool reported success",
        })

        # Check 2: State changed as expected
        if state_before is not None and state_after is not None:
            state_check = self._check_state_change(call, state_before, state_after)
            checks.append(state_check)

        # Check 3: File-specific verification
        if call.action in ("write_file", "write_report") and result.success:
            file_check, evidence = await self._verify_file_output(call, result)
            checks.append(file_check)
            if evidence:
                evidence_ids.append(evidence.evidence_id)

        # Check 4: Expected outcome match
        if call.expected_outcome:
            outcome_check = self._check_expected_outcome(call.expected_outcome, result.data)
            checks.append(outcome_check)

        all_passed = all(c["passed"] for c in checks)
        uncertainty = None
        if not all_passed:
            failed = [c["name"] for c in checks if not c["passed"]]
            uncertainty = f"Failed checks: {', '.join(failed)}"

        return Verification(
            passed=all_passed,
            checks=checks,
            evidence_ids=evidence_ids,
            uncertainty=uncertainty,
        )

    def _check_state_change(
        self, call: ToolCall, before: dict, after: dict
    ) -> dict:
        """Verify state actually changed between before and after observation."""
        if call.action in ("list_files", "read_file"):
            return {"name": "state_unchanged_expected", "passed": True, "detail": "Read-only action"}

        changed = before != after
        if call.action in ("write_file", "write_report"):
            return {
                "name": "state_changed",
                "passed": changed,
                "detail": "State changed after write" if changed else "No state change detected after write",
            }

        return {"name": "state_check", "passed": True, "detail": "State observation recorded"}

    async def _verify_file_output(
        self, call: ToolCall, result: ToolResult
    ) -> tuple[dict, Evidence | None]:
        """Verify a file was actually created/modified with expected content."""
        output_path = call.args.get("output_path") or call.args.get("path")
        if not output_path:
            return {"name": "file_exists", "passed": False, "detail": "No output path specified"}, None

        path = Path(output_path)
        if not path.exists():
            return {"name": "file_exists", "passed": False, "detail": f"File not found: {path}"}, None

        content = path.read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        evidence = Evidence(
            kind=EvidenceKind.FILE_HASH,
            source_id=str(path),
            content={"size_bytes": len(content), "lines": content.count("\n") + 1},
            content_hash=content_hash,
        )

        size_ok = len(content) > 0
        return {
            "name": "file_exists",
            "passed": size_ok,
            "detail": f"File exists, {len(content)} bytes, hash={content_hash[:16]}..."
        }, evidence

    def _check_expected_outcome(self, expected: dict, actual: dict) -> dict:
        """Check whether actual results match expected outcome criteria."""
        mismatches: list[str] = []
        for key, expected_val in expected.items():
            actual_val = actual.get(key)
            if actual_val != expected_val:
                mismatches.append(f"{key}: expected={expected_val}, actual={actual_val}")

        return {
            "name": "expected_outcome",
            "passed": len(mismatches) == 0,
            "detail": "All expectations met" if not mismatches else f"Mismatches: {'; '.join(mismatches)}",
        }
