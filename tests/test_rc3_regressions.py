import json
import ssl
import sys

import pytest
import requests
from conftest import Response, Session
from test_ai_notifications import Channel

from canvas_agent import app, schedule
from canvas_agent.api import APIError, CanvasAPI
from canvas_agent.models import Snapshot
from canvas_agent.notifications import Dispatcher
from canvas_agent.rules import weekly_report
from canvas_agent.storage import Store
from canvas_agent.transport import WindowsTrustAdapter
from canvas_agent.windows_native import WindowsAPIError


def test_unexplained_quiz_404_is_not_inferred_to_be_disabled():
    session = Session(Response([{"id": 2, "name": "Work"}]), Response(status=404), Response([]))
    api = CanvasAPI("https://canvas.example", "synthetic", session)
    snap = api.sync([{"id": 1, "name": "C"}])
    assert len(snap.failures) == 1 and snap.failures[0]["code"] == "unsupported_or_missing"
    assert not snap.capabilities
    assert len(snap.tasks) == 1 and not snap.complete
    assert (1, "quizzes") not in snap.successful


def test_quiz_404_and_announcement_permission_error_both_remain_failures():
    session = Session(Response([]), Response(status=404), Response(status=403))
    snap = CanvasAPI("https://canvas.example", "synthetic", session).sync([{"id": 1, "name": "C"}])
    assert snap.failures[0]["code"] == "unsupported_or_missing"
    assert snap.failures[1]["code"] == "permission_denied"


def test_quiz_uses_canvas_title_field():
    session = Session(Response([]), Response([{"id": 3, "title": "Practice quiz"}]), Response([]))
    snap = CanvasAPI("https://canvas.example", "synthetic", session).sync([{"id": 1, "name": "C"}])
    assert snap.tasks[0].title == "Practice quiz"


def test_weekly_failure_reason_survives_dispatch_with_paragraphs(tmp_path, task, config, now):
    snap = Snapshot(
        [], [task], [], [], [{"course_id": 1, "kind": "quizzes", "code": "quiz_navigation_unavailable"}]
    )
    message = weekly_report(snap, config, now, "week")
    message.body += "\n\n<b>synthetic-sensitive</b><br>Final line"
    store = Store(tmp_path)
    try:
        channel = Channel()
        dispatcher = Dispatcher(
            store, {"pushplus": channel}, ["synthetic-sensitive"], "https://canvas.example"
        )
        assert dispatcher.send(message, ["pushplus"], now)
        body = channel.calls[0][1]
        assert body.index("测验入口未开放") < body.index("This week")
        assert body.count(task.title) == 1
        assert "\n\nCompleted" in body and "\nFinal line" in body
        assert "<b>" not in body and "synthetic-sensitive" not in body
        assert "[REDACTED]" in body and "Data incomplete" in body
    finally:
        store.close()


def test_certificate_error_is_not_retried_or_ignored():
    session = Session(requests.exceptions.SSLError("synthetic sensitive details"))
    api = CanvasAPI("https://canvas.example", "synthetic", session)
    with pytest.raises(APIError, match="^tls_verification_failed$"):
        api.identity()
    assert len(session.calls) == 1
    assert session.calls[0][1].get("verify", True) is True


def test_windows_trust_keeps_hostname_and_certificate_verification():
    adapter = WindowsTrustAdapter()
    context = adapter.poolmanager.connection_pool_kw["ssl_context"]
    assert context.check_hostname is True and context.verify_mode == ssl.CERT_REQUIRED
    proxy = adapter.proxy_manager_for("http://127.0.0.1:9")
    context = proxy.connection_pool_kw["ssl_context"]
    assert context.check_hostname is True and context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize(
    "error,code",
    [
        (WindowsAPIError("task_scheduler_failed", 0x80070005), "task_scheduler_failed"),
        (RuntimeError("synthetic-sensitive"), "task_cleanup_failed"),
    ],
)
def test_uninstall_scheduler_error_is_bounded_and_returns_failure(tmp_path, monkeypatch, error, code):
    def fail(root):
        raise error

    monkeypatch.setattr(schedule, "remove_task", fail)
    monkeypatch.setattr(sys, "argv", ["agent", "--remove-task", "--data-dir", str(tmp_path)])
    assert app.main() == 3
    text = (tmp_path / "task-cleanup-result.json").read_text()
    assert json.loads(text)["code"] == code and "synthetic-sensitive" not in text


def test_uninstall_missing_task_is_success(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "remove_task", lambda root: None)
    monkeypatch.setattr(schedule, "remove_deadline_task", lambda root: None)
    monkeypatch.setattr(sys, "argv", ["agent", "--remove-task", "--data-dir", str(tmp_path)])
    assert app.main() == 0
    assert json.loads((tmp_path / "task-cleanup-result.json").read_text())["status"] == "ok"
