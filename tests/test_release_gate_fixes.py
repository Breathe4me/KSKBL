"""Offline counterexamples for the release audit; no native GUI, provider or task execution."""

import json
import queue
import threading
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
import requests
from conftest import Response, Session
from test_ai_notifications import Channel
from test_engine import FakeSecrets, setup
from test_v11_copilot import ai_client, ai_response, announcement, guardian_setup

from canvas_agent.ai import AIClient
from canvas_agent.ai_cache import cached_request
from canvas_agent.ai_jobs import drain
from canvas_agent.announcement_intelligence import summarize_one
from canvas_agent.config import DEFAULTS, load, save
from canvas_agent.engine import run
from canvas_agent.guardian import rebuild_plan, tick, update_schedule
from canvas_agent.models import Snapshot, Status, submission_state, timestamp
from canvas_agent.notifications import Dispatcher
from canvas_agent.rules import Message
from canvas_agent.security import ProcessLock
from canvas_agent.storage import Store
from canvas_agent.submission import EXCUSED, NOT_SUBMITTED, PENDING, SUBMITTED, UNKNOWN, classify


@pytest.mark.parametrize(
    "raw,primary,verified",
    [
        (
            {"workflow_state": "unsubmitted", "submitted_at": "2026-01-01T00:00:00Z"},
            Status.NOT_SUBMITTED,
            NOT_SUBMITTED,
        ),
        ({"workflow_state": "processing", "submitted_at": "2026-01-01T00:00:00Z"}, Status.PENDING, PENDING),
        ({"workflow_state": "complete"}, Status.UNKNOWN, UNKNOWN),
        ({"submitted_at": "2026-01-01T00:00:00Z"}, Status.UNKNOWN, UNKNOWN),
        (
            {"workflow_state": "submitted", "attempt": 1, "submission_history": [{"attempt": 2}]},
            Status.UNKNOWN,
            UNKNOWN,
        ),
        ({"workflow_state": "submitted"}, Status.SUBMITTED, SUBMITTED),
        ({"workflow_state": "graded"}, Status.GRADED, SUBMITTED),
        ({"excused": True}, Status.GRADED, EXCUSED),
    ],
)
def test_current_workflow_consistent_across_both_classifiers(raw, primary, verified):
    assert submission_state(raw) == primary
    assert classify(raw) == verified


def test_cancel_course_immediately_cancels_cached_guardian_checks(tmp_path, task, config, now):
    state = Store(tmp_path)
    try:
        api, channel, dispatcher = guardian_setup(state, task, config, now)
        config["course_ids"] = []
        assert rebuild_plan(state, config, now) == []
        assert tick(state, config, api, dispatcher, timestamp(task.due)) == []
        assert not api.calls and not channel.calls
    finally:
        state.close()


def test_changed_account_is_checked_before_cached_guardian(tmp_path, task, config, now, monkeypatch):
    config.update(
        canvas_url="https://canvas.example", monitoring=True, guardian_enabled=True, weekly_enabled=False
    )
    save(tmp_path / "config.json", config)
    state = Store(tmp_path)
    state.snapshot(
        Snapshot(
            [{"id": 1}],
            [replace(task, due=(now + timedelta(minutes=10)).isoformat())],
            [],
            [(1, "assignments")],
            [],
        ),
        now,
    )
    state.set("account", "old-account")
    state.set("credential_scope", "old-token-scope")
    state.close()

    class NewAccount:
        def __init__(self, *args):
            pass

        def identity(self):
            return "new-account"

        def get(self, *args):
            raise AssertionError("Old cached assignment must never be verified")

        def courses(self, *args):
            return []

        def sync(self, *args):
            return Snapshot([], [], [], [], [])

    monkeypatch.setattr("canvas_agent.engine.Secrets", FakeSecrets)
    monkeypatch.setattr("canvas_agent.guardian.update_schedule", lambda *a, **k: None)
    channel = Channel()
    assert (
        run(tmp_path, now=now, api_factory=NewAccount, channel_factory=lambda _: {"windows": channel})[
            "status"
        ]
        == "ok"
    )
    assert not channel.calls


def test_uncertain_receipt_never_becomes_success_on_recheck(tmp_path, now):
    state = Store(tmp_path)
    try:
        channel = Channel(fail=True)
        dispatcher = Dispatcher(state, {"windows": channel}, (), "https://canvas.example")
        message = Message("same-key", "Title", "Body")
        assert dispatcher.send(message, ["windows"], now) is False
        assert dispatcher.send(message, ["windows"], now) is False
        assert dispatcher.send_result(message, ["windows"], now)["channels"] == {"windows": "uncertain"}
        assert len(channel.calls) == 1
    finally:
        state.close()


def test_failed_weekly_delivery_is_not_marked_done(tmp_path, config, task, now, monkeypatch):
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    config.update(weekly_enabled=True, strong_enabled=False)
    save(tmp_path / "config.json", config)
    channel.fail = True
    run(tmp_path, scheduled=True, now=now, api_factory=api, channel_factory=factory)
    run(tmp_path, scheduled=True, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)
    state = Store(tmp_path)
    try:
        assert state.get("weekly_done") is None
        assert len(channel.calls) == 1
    finally:
        state.close()


def test_failed_announcement_stays_cached_across_restarts_and_requires_force(tmp_path, config):
    state = Store(tmp_path)
    client, session = ai_client(config, requests.Timeout())
    result = summarize_one(announcement(), client, state)
    assert result["status"] == "failed_fallback" and len(session.calls) == 1
    state.close()
    state = Store(tmp_path)
    try:
        client, session = ai_client(config, ai_response())
        cached = summarize_one(announcement(), client, state)
        assert cached["cached"] and cached["status"] == "failed_fallback"
        assert not session.calls
        assert summarize_one(announcement(), client, state, force=True)["status"] == "ok"
        assert len(session.calls) == 1
    finally:
        state.close()


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"summary": "short"}, "summary_length"),
        ({"summary": None}, "summary_type"),
        ({"summary": "x" * 151}, "summary_length"),
        ({"importance": "Urgent"}, "importance_enum"),
        ({"todos": "not a list"}, "todos_type"),
        ({"dates": [123]}, "dates_type"),
    ],
)
def test_invalid_schema_retains_strict_checks_with_redacted_reason(tmp_path, config, changes, reason):
    state = Store(tmp_path)
    try:
        client, _ = ai_client(config, ai_response(**changes))
        result = summarize_one(announcement(), client, state)
        assert result["status"] == "invalid_response" and result["reason"] == reason
        assert "synthetic-key" not in json.dumps(result)
    finally:
        state.close()


def test_budget_persists_and_crashed_reservation_is_not_automatically_retried(tmp_path, config, now):
    config["ai_daily_budget"] = 1
    state = Store(tmp_path)
    try:
        assert state.reserve_ai("item:digest", "digest", 1, now) is None
        result = cached_request(
            state, "item", "digest", config, lambda: pytest.fail("automatic retry"), now=now
        )
        assert result["status"] == "request_in_progress" and result["cached"]
        assert (
            cached_request(state, "other", "new", config, lambda: pytest.fail("over budget"), now=now)[
                "status"
            ]
            == "daily_budget_exhausted"
        )
        result = cached_request(
            state, "other", "new", config, lambda: {"status": "ok"}, now=now + timedelta(days=1)
        )
        assert result["status"] == "ok"
    finally:
        state.close()


def test_late_ai_response_does_not_repopulate_new_account(tmp_path, config, now):
    state = Store(tmp_path)
    try:
        state.set("account", "old")

        def response():
            state.reset_account()
            state.set("account", "new")
            return {"status": "ok", "summary": "old private content"}

        assert cached_request(state, "ai_result", "d", config, response, now=now)["status"] == "stale_context"
        assert state.get("ai_result") is None
    finally:
        state.close()


def test_provider_busy_and_truncated_output_are_never_automatically_retried(config):
    config.update(ai_enabled=True, ai_consent=True)
    busy = Session(Response({}, status=429, headers={"Retry-After": "0"}), ai_response())
    assert AIClient(config, "synthetic", busy).request_json("test", "test")["status"] == "retry_later"
    assert len(busy.calls) == 1
    truncated = Session(Response({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}))
    result = AIClient(config, "synthetic", truncated).request_json("test", "test")
    assert result == {"status": "invalid_response", "reason": "output_truncated"}


def test_connection_probe_uses_announcement_schema(config):
    client, session = ai_client(config, ai_response(summary="short"))
    assert client.test()["reason"] == "summary_length"
    assert "50-150" in session.calls[0][1]["json"]["messages"][0]["content"]


def test_legacy_config_does_not_opt_into_new_external_purposes(tmp_path):
    old = DEFAULTS | {"ai_enabled": True, "ai_consent": True}
    for key in ("ai_announcements_enabled", "ai_weekly_enabled", "ai_daily_budget"):
        old.pop(key)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(old))
    before = path.read_bytes()
    loaded = load(path)
    assert not loaded["ai_announcements_enabled"] and not loaded["ai_weekly_enabled"]
    assert loaded["ai_daily_budget"] == 20 and path.read_bytes() == before


def test_global_ai_consent_alone_never_calls_weekly_or_automatic_ai(tmp_path, config, task, now, monkeypatch):
    api, _, factory = setup(tmp_path, config, monkeypatch, task)
    config.update(ai_enabled=True, ai_consent=True, weekly_enabled=True)
    save(tmp_path / "config.json", config)
    monkeypatch.setattr("canvas_agent.ai.AIClient.request_json", lambda *a: pytest.fail("unapproved purpose"))
    run(tmp_path, scheduled=True, now=now, api_factory=api, channel_factory=factory)
    state = Store(tmp_path)
    try:
        assert not state.get("ai_pending_jobs")
    finally:
        state.close()


def test_slow_ai_cannot_hold_core_process_lock(tmp_path, config, task, now, monkeypatch):
    api, _, factory = setup(tmp_path, config, monkeypatch, task)
    config.update(ai_enabled=True, ai_consent=True, ai_announcements_enabled=True)
    save(tmp_path / "config.json", config)
    monkeypatch.setattr("canvas_agent.ai_jobs.start_worker", lambda _: None)
    run(tmp_path, now=now, api_factory=api, channel_factory=factory)
    entered, release = threading.Event(), threading.Event()

    class SlowAI(AIClient):
        def request_json(self, *args):
            entered.set()
            assert release.wait(5)
            return {"status": "failed_fallback"}

    worker = threading.Thread(
        target=lambda: drain(
            tmp_path, now=now, ai_factory=SlowAI, secrets_factory=FakeSecrets, channel_factory=factory
        )
    )
    worker.start()
    try:
        assert entered.wait(2)
        with ProcessLock(tmp_path):
            pass
        assert (
            run(tmp_path, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)["status"]
            == "ok"
        )
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()


def test_deleted_deadline_task_is_repaired_despite_unchanged_digest(tmp_path, task, config, now, monkeypatch):
    state = Store(tmp_path)
    try:
        guardian_setup(state, task, config, now)
        calls = []
        monkeypatch.setattr("canvas_agent.schedule.install_deadline_task", lambda *a: calls.append(a))
        monkeypatch.setattr("canvas_agent.schedule.deadline_task_info", lambda _: {"exists": False})
        update_schedule(tmp_path, state, config, now)
        update_schedule(tmp_path, state, config, now, force=True)
        assert len(calls) == 2
    finally:
        state.close()


def test_pdf_external_decoder_is_disabled_even_if_dependency_would_use_it(monkeypatch):
    from pypdf import apply_configuration, get_configuration
    from pypdf.filters import JBIG2Decode

    from canvas_agent.material_files import MaterialError, parse_material

    class Page:
        def extract_text(self):
            assert get_configuration().jbig2dec_binary is None
            JBIG2Decode.decode(b"synthetic")

    monkeypatch.setattr(
        "pypdf.PdfReader", lambda *a, **k: SimpleNamespace(is_encrypted=False, pages=[Page()])
    )
    with apply_configuration(jbig2dec_binary="untrusted-path-decoder"):
        with pytest.raises(MaterialError, match="unreadable_material"):
            parse_material("test.pdf", b"%PDF- synthetic")
        assert get_configuration().jbig2dec_binary == "untrusted-path-decoder"


def test_safe_tk_never_runs_implicit_profiles(monkeypatch):
    import tkinter as tk

    from canvas_agent.safe_tk import SafeTk

    monkeypatch.setattr(tk.Tk, "__init__", lambda self: self.readprofile("test", "Tk"))
    assert SafeTk() is not None


def fake_poll_app(callback):
    from canvas_agent.gui import Application

    values, after = [], []
    results = queue.Queue()
    results.put((True, {}, callback))
    app = SimpleNamespace(
        refresh_clock=lambda: None,
        results=results,
        busy=True,
        ai_busy=False,
        progress=SimpleNamespace(stop=lambda: None),
        tr=lambda en, zh: en,
        status=SimpleNamespace(set=values.append),
        refresh_credential_status=lambda: None,
        refresh=lambda: None,
        root=SimpleNamespace(winfo_exists=lambda: True, after=lambda *a: after.append(a)),
    )
    app.poll = lambda: Application.poll(app)
    return app, after


@pytest.mark.parametrize("error", [ValueError("private response body"), None])
def test_callback_failure_cannot_stop_future_gui_results(error):
    import tkinter as tk

    failure = error or tk.TclError("closed child widget")

    def broken(_):
        raise failure

    app, after = fake_poll_app(broken)
    app.poll()
    assert len(after) == 1
    seen = []
    app.results.put((True, "second", seen.append))
    app.poll()
    assert seen == ["second"] and len(after) == 2


def test_independent_ai_result_does_not_clear_active_save_busy_state():
    app, _ = fake_poll_app(lambda _: None)
    app.results.get_nowait()
    app.results.put((True, {}, lambda _: None, True))
    app.ai_busy = True
    app.poll()
    assert app.busy and not app.ai_busy


def test_closed_announcement_text_is_not_accessed():
    from canvas_agent.copilot_gui import show_text

    show_text(SimpleNamespace(winfo_exists=lambda: False), "result")


def test_queued_weekly_data_is_discarded_after_course_selection_changes(tmp_path, config, monkeypatch):
    from canvas_agent.ai_jobs import queue_job

    config.update(ai_enabled=True, ai_consent=True, ai_weekly_enabled=True)
    state = Store(tmp_path)
    try:
        queue_job(state, config, "weekly", {"week": "synthetic-week", "body": "old course text"})
    finally:
        state.close()
    config["course_ids"] = []
    save(tmp_path / "config.json", config)
    assert drain(tmp_path, secrets_factory=lambda _: pytest.fail("Revoked scope must not read a key")) == 0


def test_optional_worker_start_failure_does_not_fail_completed_sync(tmp_path, task, config, now, monkeypatch):
    api, _, factory = setup(tmp_path, config, monkeypatch, task)

    def unavailable(_):
        raise RuntimeError("private response")

    monkeypatch.setattr("canvas_agent.ai_jobs.start_worker", unavailable)
    result = run(tmp_path, now=now, api_factory=api, channel_factory=factory)
    assert result["status"] == "ok" and result["ai_status"] == "worker_unavailable"
    state = Store(tmp_path)
    try:
        assert state.cached() and state.get("last_complete")
    finally:
        state.close()


def test_legacy_confirmed_cache_is_reverified_instead_of_suppressing_alerts(
    tmp_path, task, config, now, monkeypatch
):
    from test_v11_copilot import API

    config.update(canvas_url=API.base, monitoring=True, guardian_enabled=True)
    save(tmp_path / "config.json", config)
    state = Store(tmp_path)
    try:
        api, channel, _ = guardian_setup(
            state,
            replace(task, status="Confirmed Submitted"),
            config,
            now,
            submission={"workflow_state": "unsubmitted", "submitted_at": now.isoformat()},
        )
        api.identity = lambda: "current-account"
    finally:
        state.close()
    monkeypatch.setattr("canvas_agent.engine.Secrets", FakeSecrets)
    monkeypatch.setattr("canvas_agent.guardian.update_schedule", lambda *a, **k: None)
    run(
        tmp_path,
        guardian_only=True,
        now=timestamp(task.due) - timedelta(minutes=15),
        api_factory=lambda *a: api,
        channel_factory=lambda _: {"windows": channel},
    )
    assert len(channel.calls) == 1 and NOT_SUBMITTED in channel.calls[0][1]


def test_processing_task_is_not_grouped_as_confirmed_not_submitted(config, task, now):
    from canvas_agent.rules import weekly_report

    task = replace(task, status=Status.PENDING)
    result = weekly_report(Snapshot([], [task], [], [], []), config, now, "week")
    assert "Not submitted / 未提交: 0" in result.body
    assert "Pending / Processing / 处理中: 1" in result.body


def test_explicit_weekly_purpose_queues_a_separate_supplement(tmp_path, task, config, now, monkeypatch):
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    config.update(
        weekly_enabled=True, strong_enabled=False, ai_enabled=True, ai_consent=True, ai_weekly_enabled=True
    )
    save(tmp_path / "config.json", config)
    monkeypatch.setattr("canvas_agent.ai_jobs.start_worker", lambda _: None)
    run(tmp_path, scheduled=True, now=now, api_factory=api, channel_factory=factory)
    assert len(channel.calls) == 1

    class WeeklyAI:
        def __init__(self, *a, **k):
            pass

        def summarize(self, *a, **k):
            return {
                "status": "ok",
                "label": "AI extracted",
                "summary": "Synthetic weekly advice",
                "todos": [],
                "dates": [],
            }

    drain(tmp_path, now=now, ai_factory=WeeklyAI, secrets_factory=FakeSecrets, channel_factory=factory)
    assert len(channel.calls) == 2 and "AI weekly supplement" in channel.calls[1][0]


def test_streamed_provider_response_is_bounded_closed_and_decoded(config):
    config.update(ai_enabled=True, ai_consent=True)
    value = {"summary": "合成摘要", "todos": [], "dates": []}
    body = json.dumps({"choices": [{"message": {"content": json.dumps(value)}}]}).encode()

    class Stream:
        status_code = 200
        closed = False

        def iter_content(self, chunk_size):
            yield body[:17]
            yield body[17:]

        def close(self):
            self.closed = True

    response = Stream()
    result = AIClient(config, "synthetic", Session(response)).request_json("test", "synthetic")
    assert result == {"status": "ok", "value": value} and response.closed


def test_oversized_stream_closes_and_releases_ai_gate(config):
    config.update(ai_enabled=True, ai_consent=True)

    class Stream:
        status_code = 200
        closed = False

        def iter_content(self, chunk_size):
            yield b"x" * 512001

        def close(self):
            self.closed = True

    response = Stream()
    result = AIClient(config, "synthetic", Session(response)).request_json("test", "synthetic")
    assert result["reason"] == "response_too_large" and response.closed
    client, _ = ai_client(config, ai_response())
    assert client.request_json("test", "synthetic")["status"] == "ok"


def test_ambiguous_stream_failure_is_cached_without_resubmission(tmp_path, config):
    config.update(ai_enabled=True, ai_consent=True)

    class Stream:
        status_code = 200

        def iter_content(self, chunk_size):
            raise requests.Timeout("synthetic private response")
            yield b""  # keep this a streaming generator

        def close(self):
            pass

    session = Session(Stream())
    client = AIClient(config, "synthetic", session)
    state = Store(tmp_path)
    try:
        assert summarize_one(announcement(), client, state)["status"] == "failed_fallback"
        assert summarize_one(announcement(), client, state)["cached"]
        assert len(session.calls) == 1
    finally:
        state.close()
