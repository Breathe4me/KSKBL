"""Read-only latest submission verification, with durable bounded history."""

from datetime import UTC, datetime

from .api import APIError
from .models import Status, submission_state, timestamp
from .security import plain

SUBMITTED = "Confirmed Submitted"
NOT_SUBMITTED = "Confirmed Not Submitted"
PENDING = "Pending / Processing"
UNKNOWN = "Unknown / Unable to Verify"
EXCUSED = "Excused / No submission required"


def classify(raw):
    status = submission_state(raw)
    if status == Status.GRADED:
        return EXCUSED if raw.get("excused") is True else SUBMITTED
    return {
        Status.SUBMITTED: SUBMITTED,
        Status.NOT_SUBMITTED: NOT_SUBMITTED,
        Status.PENDING: PENDING,
    }.get(status, UNKNOWN)


def verify(api, course_id, assignment_id, store=None, now=None):
    cid, aid = int(course_id), int(assignment_id)
    now = now or datetime.now(UTC)
    result = {
        "key": f"{cid}:assignment:{aid}",
        "status": UNKNOWN,
        "checked": now.isoformat(),
        "url": f"{api.base}/courses/{cid}/assignments/{aid}/submissions",
        "error": None,
        "due": None,
        "late_allowed": None,
        "submitted_at": None,
        "submission_type": None,
        "attachments": [],
        "attempt": None,
        "late": None,
        "history": [],
        "assignment_refreshed": False,
    }
    try:
        assignment, _ = api.get(f"courses/{cid}/assignments/{aid}", {"include[]": "submission"})
        if not isinstance(assignment, dict) or assignment.get("id") != aid:
            raise APIError("invalid_assignment")
        due, lock = assignment.get("due_at"), assignment.get("lock_at")
        timestamp(due)
        timestamp(lock)
        result.update(due=due, lock=lock, assignment_refreshed=True)
        result["late_allowed_basis"] = (
            "Availability inferred from Canvas lock_at and locked_for_user; "
            "teacher/institution late-submission policy is not verified."
        )
        if assignment.get("locked_for_user") is False and due:
            result["late_allowed"] = not lock or timestamp(lock) > timestamp(due)
        elif assignment.get("locked_for_user") is True:
            result["late_allowed"] = False
        raw, _ = api.get(
            f"courses/{cid}/assignments/{aid}/submissions/self", {"include[]": "submission_history"}
        )
        if not isinstance(raw, dict):
            raise APIError("invalid_submission")
        if raw.get("assignment_id") not in (None, aid):
            raise APIError("invalid_submission")
        # Top-level is Canvas's current record. History cannot override a current unsubmitted state.
        result.update(
            status=classify(raw),
            submitted_at=raw.get("submitted_at"),
            submission_type=raw.get("submission_type"),
            attempt=raw.get("attempt"),
            late=raw.get("late"),
        )
        result["attachments"] = [
            {
                "id": f.get("id"),
                "name": plain(f.get("display_name", f.get("filename", "")), 300),
                "bytes": f.get("size"),
            }
            for f in raw.get("attachments", [])[:100]
        ]
        history = raw.get("submission_history") or []
        result["history"] = [
            {"attempt": h.get("attempt"), "submitted_at": h.get("submitted_at"), "status": classify(h)}
            for h in history[:100]
            if isinstance(h, dict)
        ]
        # Inconsistent attempt ordering must not be reported as confirmed success.
        if result["status"] == UNKNOWN and any(
            isinstance(h, dict)
            and type(h.get("attempt")) is int
            and type(raw.get("attempt", 0)) is int
            and h["attempt"] > raw.get("attempt", 0)
            for h in history
        ):
            result["error"] = "inconsistent_latest_attempt"
    except APIError as error:
        result.update(status=UNKNOWN, error="verification_unavailable", error_code=error.code)
    except (ValueError, TypeError):
        result.update(status=UNKNOWN, error="verification_unavailable")
    if store:
        key = "verification:" + result["key"]
        store.set(key, result)
        history = store.get("verification_history", [])
        history.append({k: result[k] for k in ("key", "checked", "status", "attempt", "error")})
        store.set("verification_history", history[-500:])
        store.event("submission_verified", result["status"])
        if result["status"] == SUBMITTED:
            store.mark_submitted(result["key"], now)
        elif result["status"] == EXCUSED:
            store.update_task(result["key"], {"status": "Graded", "excused": True})
        else:
            # A fresh unsubmitted/pending/UNKNOWN result must not leave a stale success badge.
            store.update_task(
                result["key"],
                {
                    "status": "Unknown" if result["status"] == UNKNOWN else result["status"],
                    "checked": now.isoformat(),
                },
            )
    return result
