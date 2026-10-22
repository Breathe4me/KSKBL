from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import Response, Session
from test_rc4_regressions import recovered_snapshot

from canvas_agent.api import CanvasAPI
from canvas_agent.rules import reminder_messages, weekly_report
from canvas_agent.storage import Store

DISABLED = {"message": "That page has been disabled for this course"}


@pytest.mark.parametrize(
    "status,payload,code",
    [
        (404, None, "unsupported_or_missing"),
        (404, {"message": "Resource not found"}, "unsupported_or_missing"),
        (403, DISABLED, "permission_denied"),
        (401, {}, "invalid_token"),
    ],
)
def test_only_explicit_course_disabled_404_is_a_capability(status, payload, code):
    api = CanvasAPI(
        "https://canvas.example",
        "synthetic",
        Session(Response([]), Response(payload, status=status), Response([])),
    )
    snap = api.sync([{"id": 1, "name": "COMP1234"}])
    assert not snap.capabilities and snap.failures[0]["code"] == code


def test_disabled_quiz_list_is_information_without_faking_full_coverage(config, now):
    snap, _ = recovered_snapshot()
    assert not snap.failures and snap.capabilities[0]["state"] == "disabled_by_course"
    assert snap.status == "limited" and snap.complete is False
    report = weekly_report(snap, config, now, "week")
    assert "作业与公告同步成功" in report.body and "数据源说明" in report.body
    assert "数据不完整" not in report.body and "独立测验无法保证全量枚举" in report.body


def test_disabled_list_does_not_hide_module_failure():
    session = Session(Response([]), Response(DISABLED, status=404), Response(status=403), Response([]))
    snap = CanvasAPI("https://canvas.example", "synthetic", session).sync([{"id": 1, "name": "COMP1234"}])
    assert snap.capabilities and snap.status == "partial"
    assert snap.failures == [{"course_id": 1, "kind": "quiz_recovery", "code": "permission_denied"}]


def test_reopened_quiz_list_clears_capability_and_recovers_complete_status(tmp_path, now):
    session = Session(
        Response([]),
        Response(DISABLED, status=404),
        Response([]),
        Response([]),
        Response([]),
        Response([{"id": 5, "title": "Now visible"}]),
        Response([]),
    )
    api = CanvasAPI("https://canvas.example", "synthetic", session)
    store = Store(tmp_path)
    try:
        first = api.sync([{"id": 1, "name": "COMP1234"}])
        store.snapshot(first, now)
        assert store.get("last_sync_ok") and not store.get("last_complete")
        assert len(store.get("capabilities")) == 1 and not store.get("failures")
        second = api.sync([{"id": 1, "name": "COMP1234"}])
        store.snapshot(second, now + timedelta(hours=1))
        assert second.complete and second.status == "complete"
        assert store.get("capabilities") == [] and store.get("last_complete") is True
        assert store.cached()[0]["title"] == "Now visible"
    finally:
        store.close()


def test_completed_assignment_linked_quiz_stops_reminders_even_with_disabled_list(config, now, task):
    done = replace(task, status="Graded", due=(now + timedelta(hours=1)).isoformat())
    snap, _ = recovered_snapshot()
    assert reminder_messages([done], config, now, "round") == []
    assert snap.capabilities and not snap.failures


def test_notification_failure_and_disabled_capability_are_independent(config, now, task):
    snap, _ = recovered_snapshot()
    snap.failures.append({"course_id": 1, "kind": "announcements", "code": "network_or_timeout"})
    report = weekly_report(snap, config, now, "week")
    assert "Data incomplete" in report.body and "network_or_timeout" in report.body
    assert "Data source notes" in report.body
