from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Status(StrEnum):
    SUBMITTED = "Confirmed Submitted"
    NOT_SUBMITTED = "Confirmed Not Submitted"
    UNKNOWN = "Unknown"
    GRADED = "Graded"
    PENDING = "Pending / Processing"


def timestamp(value):
    if not value:
        return None
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("Canvas date must contain a timezone")
    return d.astimezone(UTC)


def submission_state(raw):
    """Current Canvas workflow wins over historical timestamps or uploaded files."""
    if not isinstance(raw, dict):
        return Status.UNKNOWN
    state = raw.get("workflow_state")
    if state in ("pending", "processing") or raw.get("processing") is True:
        return Status.PENDING
    if raw.get("excused") is True:
        return Status.GRADED
    if state == "unsubmitted":
        return Status.NOT_SUBMITTED
    history = raw.get("submission_history") or []
    attempt = raw.get("attempt") or 0
    if not isinstance(history, list) or type(attempt) is not int or attempt < 0:
        return Status.UNKNOWN
    attempts = [h.get("attempt") or 0 for h in history if isinstance(h, dict)]
    if any(type(a) is not int or a < 0 for a in attempts):
        return Status.UNKNOWN
    if max(attempts, default=0) > attempt:
        return Status.UNKNOWN
    if state == "graded":
        return Status.GRADED
    if state in ("submitted", "pending_review"):
        return Status.SUBMITTED
    return Status.UNKNOWN


@dataclass
class Task:
    key: str
    course_id: int
    course: str
    title: str
    kind: str
    due: str | None
    status: str
    url: str
    points: float | None = None
    unlock: str | None = None
    lock: str | None = None
    late_allowed: bool | None = None
    excused: bool = False

    @property
    def completed(self):
        return self.status in (Status.SUBMITTED, Status.GRADED)

    def to_dict(self):
        return asdict(self)


@dataclass
class Announcement:
    key: str
    course_id: int
    course: str
    title: str
    posted: str | None
    updated: str | None
    body: str
    url: str

    def to_dict(self):
        return asdict(self)


@dataclass
class Snapshot:
    courses: list
    tasks: list[Task]
    announcements: list[Announcement]
    successful: list[tuple[int, str]]
    failures: list[dict]
    capabilities: list[dict] = field(default_factory=list)

    @property
    def complete(self):
        return not self.failures and not self.capabilities

    @property
    def status(self):
        return sync_status(self.failures, self.capabilities)


def sync_status(failures, capabilities=()):
    if failures:
        return "partial"
    return "limited" if capabilities else "complete"
