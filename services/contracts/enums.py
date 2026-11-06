"""Core enumerations for DR_FLASH."""

from enum import StrEnum


class Risk(StrEnum):
    """Side-effect risk classification for tool calls."""
    R0_READ = "R0_READ"
    R1_LOCAL_WRITE = "R1_LOCAL_WRITE"
    R2_EXTERNAL_WRITE = "R2_EXTERNAL_WRITE"
    R3_SENSITIVE = "R3_SENSITIVE"
    R4_DENY = "R4_DENY"


class TaskStatus(StrEnum):
    """Canonical task state machine states."""
    CREATED = "CREATED"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNED = "PLANNED"
    POLICY_CHECK = "POLICY_CHECK"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    RETRYING = "RETRYING"
    REPLANNING = "REPLANNING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Valid state transitions — enforced by the task store
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED: {TaskStatus.UNDERSTANDING, TaskStatus.CANCELLED},
    TaskStatus.UNDERSTANDING: {TaskStatus.PLANNED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.PLANNED: {TaskStatus.POLICY_CHECK, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.POLICY_CHECK: {
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.AWAITING_APPROVAL: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.VERIFYING,
        TaskStatus.RETRYING,
        TaskStatus.REPLANNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.VERIFYING: {
        TaskStatus.COMPLETED,
        TaskStatus.RETRYING,
        TaskStatus.REPLANNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RETRYING: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.REPLANNING: {TaskStatus.PLANNED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


class SideEffect(StrEnum):
    """Side-effect classification for tool capabilities."""
    READ = "READ"
    LOCAL_WRITE = "LOCAL_WRITE"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"
    PRIVILEGED = "PRIVILEGED"


class EvidenceKind(StrEnum):
    """Types of verification evidence."""
    API_STATE = "api_state"
    FILE_HASH = "file_hash"
    UI_TREE = "ui_tree"
    SCREENSHOT = "screenshot"
    TEST_REPORT = "test_report"
    HUMAN = "human"


class ModelRole(StrEnum):
    """Roles for model routing."""
    FAST_INTENT = "FAST_INTENT"
    LOCAL_DIALOG = "LOCAL_DIALOG"
    HARD_REASONING = "HARD_REASONING"
    VISION_GROUNDING = "VISION_GROUNDING"
    VERIFIER = "VERIFIER"
    EMBEDDINGS = "EMBEDDINGS"
    ASR = "ASR"
    TTS = "TTS"
    REALTIME_VOICE = "REALTIME_VOICE"


class ApprovalStatus(StrEnum):
    """Approval decision states."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
