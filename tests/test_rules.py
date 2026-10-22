from dataclasses import replace
from datetime import timedelta

import pytest

from canvas_agent.models import Snapshot, Status, submission_state
from canvas_agent.rules import reminder_messages, weekly_report


@pytest.mark.parametrize(
    "raw,status",
    [
        ({}, Status.UNKNOWN),
        ({"workflow_state": "unsubmitted"}, Status.NOT_SUBMITTED),
        ({"workflow_state": "submitted"}, Status.SUBMITTED),
        ({"workflow_state": "pending_review"}, Status.SUBMITTED),
        ({"workflow_state": "graded"}, Status.GRADED),
        ({"submitted_at": "2026-10-01T00:00:00Z"}, Status.UNKNOWN),
        ({"attempts": 0}, Status.UNKNOWN),
        ({"excused": True}, Status.GRADED),
    ],
)
def test_submission_states(raw, status):
    assert submission_state(raw) == status


@pytest.mark.parametrize("hours", [24, 48, 37])
def test_strong_window_inclusive(task, config, now, hours):
    config["strong_hours"] = hours
    task.due = (now + timedelta(hours=hours)).isoformat()
    assert len(reminder_messages([task], config, now, "one")) == 1
    task.due = (now + timedelta(hours=hours, seconds=1)).isoformat()
    assert reminder_messages([task], config, now, "one") == []


@pytest.mark.parametrize(
    "hours,days,expected", [(0, 7, 1), (-24, 7, 1), (-168, 7, 1), (-169, 7, 0), (-200, 10, 1), (-241, 10, 0)]
)
def test_overdue_boundaries(task, config, now, hours, days, expected):
    config["overdue_days"] = days
    task.due = (now + timedelta(hours=hours)).isoformat()
    assert len(reminder_messages([task], config, now, "one")) == expected


@pytest.mark.parametrize("status", [Status.SUBMITTED, Status.GRADED])
def test_completed_never_reminded(task, config, now, status):
    task.status = status
    for delta in (-24, 24):
        task.due = (now + timedelta(hours=delta)).isoformat()
        assert not reminder_messages([task], config, now, "one")


def test_unknown_explicit(task, config, now):
    task.status = Status.UNKNOWN
    msg = reminder_messages([task], config, now, "one")[0]
    assert "unknown" in msg.body and "Not Submitted" not in msg.body
    assert task.url == msg.url


def test_disabled_and_undated(task, config, now):
    config["strong_enabled"] = config["overdue_enabled"] = False
    assert not reminder_messages([task], config, now, "one")
    task.due = None
    config["strong_enabled"] = True
    assert not reminder_messages([task], config, now, "one")


def test_round_dedup_and_repeat(task, config, now):
    first = reminder_messages([task, task], config, now, "one")
    second = reminder_messages([task], config, now, "two")
    assert len(first) == 1 and first[0].key != second[0].key


def test_weekly_incomplete_and_unknown(task, config, now):
    task.status = Status.UNKNOWN
    snap = Snapshot(
        [],
        [task, replace(task, key="undated", due=None)],
        [],
        [],
        [{"course_id": 2, "kind": "assignments", "code": "permission_denied"}],
    )
    message = weekly_report(snap, config, now, "2026-W43")
    assert "incomplete" in message.body and "Unknown / 未知: 1" in message.body
    assert "No Due Date / 无截止日期: 1" in message.body
    assert "permission_denied" in message.body


def test_dst_due_display(task, config, now):
    from canvas_agent.rules import due_label

    config["timezone"] = "Australia/Sydney"
    assert "AEDT" in due_label(task, config["timezone"])


def test_weekly_sorts_instants_and_deduplicates(task, config, now):
    later = replace(task, key="later", title="Later", due="2026-10-20T04:00:00Z")
    earlier = replace(task, key="earlier", title="Earlier", due="2026-10-20T12:00:00+11:00")
    report = weekly_report(Snapshot([], [later, earlier, earlier], [], [], []), config, now, "week")
    assert report.body.index("Earlier") < report.body.index("Later")
    assert "This week / 本周: 2" in report.body
