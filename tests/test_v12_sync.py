"""API response boundaries and latest submission status; no live accounts or writes."""

from dataclasses import replace
from datetime import timedelta

import pytest
import requests
from conftest import Response, Session

from canvas_agent.api import APIError, CanvasAPI
from canvas_agent.engine import run
from canvas_agent.notifications import Dispatcher
from canvas_agent.rules import Message
from canvas_agent.storage import Store
from canvas_agent.submission import SUBMITTED, UNKNOWN, verify
from canvas_agent.tracking import Tracking


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "invalid_token"),
        (403, "permission_denied"),
        (404, "unsupported_or_missing"),
        (429, "rate_limited"),
        (503, "canvas_unavailable"),
    ],
)
def test_api_errors_are_bounded_and_keep_safe_codes(status, code):
    session = Session(*[Response({"private": "never record"}, status=status) for _ in range(4)])
    api = CanvasAPI("https://canvas.example", "synthetic-token", session=session, sleep=lambda _: None)
    with pytest.raises(APIError) as error:
        api.identity()
    assert error.value.code == code
    assert len(session.calls) <= 4
    assert "synthetic-token" not in str(error.value)


def test_timeout_submission_result_is_unknown_and_get_only(tmp_path, now):
    session = Session(*[requests.Timeout() for _ in range(4)])
    api = CanvasAPI("https://canvas.example", "synthetic", session=session, sleep=lambda _: None)
    store = Store(tmp_path)
    result = verify(api, 1, 2, store, now)
    assert result["status"] == UNKNOWN
    assert result["error"] == "verification_unavailable"
    assert result["error_code"] == "network_or_timeout"
    assert len(session.calls) == 4
    assert store.get("verification_history")[-1]["status"] == UNKNOWN
    store.close()


def test_confirmed_verification_preserves_local_choice(tmp_path, task, now):
    from test_v12_tracking import seed

    session = Session(
        Response({"id": 2, "due_at": task.due}),
        Response(
            {"assignment_id": 2, "workflow_state": "submitted", "attempt": 1, "submitted_at": now.isoformat()}
        ),
    )
    store = Store(tmp_path)
    seed(store, task, now)
    Tracking(store).set(task.to_dict(), "completed")
    api = CanvasAPI("https://canvas.example", "synthetic", session=session)
    assert verify(api, 1, 2, store, now)["status"] == SUBMITTED
    row = Tracking(store).rows()[0]
    assert row["status"] == SUBMITTED and row["local"]["state"] == "completed"
    store.close()


@pytest.mark.parametrize("state", ["ignored", "completed"])
def test_engine_filters_every_task_notification_after_sync(tmp_path, config, monkeypatch, task, now, state):
    from test_engine import setup

    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    run(tmp_path, now=now, api_factory=api, channel_factory=factory)
    store = Store(tmp_path)
    Tracking(store).set(task.to_dict(), state)
    store.close()
    api.tasks = [replace(task, due="2026-10-20T10:00:00Z", title="Updated assignment")]
    run(tmp_path, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)
    assert len(channel.calls) == 1
    store = Store(tmp_path)
    assert Tracking(store).rows()[0]["local"]["state"] == state
    assert Tracking(store).rows()[0]["local"]["content_changed"]
    store.close()


def test_repeated_manual_sync_does_not_blast_same_task(tmp_path, config, monkeypatch, task, now):
    from test_engine import setup

    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    for minutes in (0, 1, 2):
        run(tmp_path, now=now + timedelta(minutes=minutes), api_factory=api, channel_factory=factory)
    assert len(channel.calls) == 1


def test_dispatcher_rechecks_confirmed_canvas_at_send_boundary(tmp_path, task, now):
    from test_ai_notifications import Channel
    from test_v12_tracking import seed

    store = Store(tmp_path)
    seed(store, task, now)
    store.mark_submitted(task.key, now)
    channel = Channel()
    result = Dispatcher(store, {"windows": channel}, [], "").send_result(
        Message("pending", "t", "b", task_key=task.key), ["windows"], now
    )
    assert result["status"] == "suppressed" and not channel.calls
    store.close()
