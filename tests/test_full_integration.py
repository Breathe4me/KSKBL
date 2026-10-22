"""Real-mode services through the UI bridge, with fake HTTP/DPAPI/native boundaries only."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from conftest import Response

from canvas_agent import schedule, web_bridge
from canvas_agent.api import CanvasAPI
from canvas_agent.config import DEFAULTS, load, save
from canvas_agent.guardian import rebuild_plan
from canvas_agent.notifications import Dispatcher
from canvas_agent.pushplus import PushPlusChannel
from canvas_agent.rules import Message
from canvas_agent.storage import Store
from canvas_agent.tracking import Tracking
from canvas_agent.web_bridge import Bridge


class Vault:
    def __init__(self, root):
        self.data = {"canvas": "SYNTHETIC-CANVAS-ONLY", "pushplus": "", "ai": ""}

    def get(self, key):
        return self.data.get(key, "")

    def set(self, key, value):
        self.data[key] = value

    def values(self):
        return tuple(self.data.values())


class School:
    def __init__(self):
        self.calls = []
        self.user = 71
        self.failure = None
        self.submission = "unsubmitted"
        self.quiz_status = 200
        self.due = (datetime.now(UTC) + timedelta(minutes=50)).isoformat()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        path = urlsplit(url).path.removeprefix("/api/v1/")
        if self.failure:
            if isinstance(self.failure, Exception):
                raise self.failure
            return Response({}, status=self.failure)
        if path == "users/self/profile":
            return Response({"id": self.user})
        if path == "courses":
            return Response([{"id": 1, "name": "Synthetic COMP5618", "course_code": "COMP5618"}])
        assignment = {
            "id": 2,
            "name": "Read-only report",
            "due_at": self.due,
            "quiz_id": 9,
            "description": '<p>Report requirements</p><a href="/files/88?verifier=secret">file</a>',
            "submission_types": ["online_upload"],
            "allowed_extensions": ["pdf"],
            "rubric": [{"id": "r1", "description": "Explain evidence", "points": 10, "ratings": []}],
            "submission": {"workflow_state": self.submission},
        }
        if path == "courses/1/assignments":
            return Response([assignment])
        if path == "courses/1/quizzes":
            return Response(
                [{"id": 9, "assignment_id": 2, "title": "Duplicate quiz", "due_at": self.due}],
                status=self.quiz_status,
            )
        if path == "courses/1/discussion_topics":
            return Response([])
        if path == "courses/1/assignments/2":
            return Response(assignment)
        if path == "courses/1/assignments/2/submissions/self":
            return Response({"assignment_id": 2, "workflow_state": self.submission, "attempt": 1})
        raise AssertionError("Unexpected fake route: " + path)


@pytest.fixture
def connected(tmp_path):
    save(tmp_path / "config.json", DEFAULTS | {"canvas_url": "https://canvas.example"})
    vault, school = Vault(tmp_path), School()
    bridge = Bridge(
        tmp_path,
        qa=False,
        secrets_factory=lambda _: vault,
        api_factory=lambda base, token: CanvasAPI(base, token, session=school, sleep=lambda _: None),
    )
    return tmp_path, bridge, vault, school


def state(bridge):
    result = bridge.invoke("get_state", {})
    assert result["ok"], result
    return result["data"]


def task_params(bridge):
    current = state(bridge)
    return {"key": current["tasks"][0]["key"], "account_scope": current["account_scope"]}


def test_canvas_rest_to_sqlite_bridge_and_duplicate_quiz(connected):
    root, bridge, _, school = connected
    assert state(bridge)["tasks"] == []  # real mode never seeds a demo
    result = bridge.invoke("sync", {})
    assert result["ok"] and result["data"]["notifications_sent"] is False
    current = state(bridge)
    assert current["qa"] is False and len(current["tasks"]) == 1
    assert current["tasks"][0]["title"] == "Read-only report"
    assert current["sync"]["last_success"] and current["account_scope"]
    assert all(call[1]["allow_redirects"] is False for call in school.calls)
    with_sqlite = Store(root)
    assert len(with_sqlite.cached()) == 1
    with_sqlite.close()
    assert "SYNTHETIC-CANVAS-ONLY" not in json.dumps(current)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "invalid_token"),
        (403, "permission_denied"),
        (429, "rate_limited"),
        (requests.Timeout(), "network_or_timeout"),
    ],
)
def test_sync_error_retains_cache_and_safe_error_status(connected, status, code):
    _, bridge, _, school = connected
    assert bridge.invoke("sync", {})["ok"]
    previous = state(bridge)["sync"]["last_success"]
    school.failure = status
    result = bridge.invoke("sync", {})["data"]
    assert result["status"] == code and result["complete"] is False
    current = state(bridge)
    assert len(current["tasks"]) == 1 and current["sync"]["last_success"] == previous
    assert current["failures"][0]["code"] == code


def test_disabled_quiz_coverage_is_not_an_empty_complete_result(connected):
    _, bridge, _, school = connected
    school.quiz_status = 403
    result = bridge.invoke("sync", {})["data"]
    current = state(bridge)
    assert result["complete"] is False and len(current["tasks"]) == 1
    assert current["coverage"] or current["failures"]


@pytest.mark.parametrize("choice", ["ignored", "completed"])
def test_ui_choice_persists_resync_filters_weekly_guardian_and_restores(connected, choice):
    root, bridge, vault, _ = connected
    bridge.invoke("sync", {})
    args = task_params(bridge)
    assert bridge.invoke(
        "set_tracking", args | {"state": choice, "reason": "optional", "note": "Saved note"}
    )["ok"]
    bridge.invoke("sync", {})
    restarted = Bridge(root, secrets_factory=lambda _: vault)
    assert state(restarted)["tasks"][0]["local"]["note"] == "Saved note"
    assert state(restarted)["local_history"][0]["state"] == choice
    assert state(restarted)["history"] == []
    assert "Read-only report" not in restarted.invoke("weekly_preview", {})["data"]["text"]
    store = Store(root)
    assert rebuild_plan(store, load(root / "config.json") | {"monitoring": True}, datetime.now(UTC)) == []
    calls = []
    channel = SimpleNamespace(send=lambda *args: calls.append(args))
    dispatcher = Dispatcher(store, {"windows": channel}, [], "https://canvas.example")
    message = Message("before_restore", "t", "b", task_key=args["key"])
    assert dispatcher.send_result(message, ["windows"], datetime.now(UTC))["status"] == "suppressed"
    store.close()
    assert restarted.invoke("set_tracking", args | {"state": "tracking"})["ok"]
    store = Store(root)
    assert Dispatcher(store, {"windows": channel}, [], "https://canvas.example").send(
        message, ["windows"], datetime.now(UTC)
    )
    assert len(calls) == 1
    store.close()


def test_next_channel_rechecks_local_state_after_first_channel(connected):
    root, bridge, _, _ = connected
    bridge.invoke("sync", {})
    args = task_params(bridge)
    store = Store(root)
    calls = []

    def first(*_):
        calls.append("first")
        Tracking(store).set(store.cached()[0], "ignored")

    dispatcher = Dispatcher(
        store,
        {"one": SimpleNamespace(send=first), "two": SimpleNamespace(send=lambda *_: calls.append("second"))},
        [],
        "https://canvas.example",
    )
    result = dispatcher.send_result(
        Message("queued", "t", "b", task_key=args["key"]), ["one", "two"], datetime.now(UTC)
    )
    assert calls == ["first"] and result["channels"]["two"] == "suppressed"
    store.close()


def test_context_and_latest_unknown_are_real_readonly_results(connected):
    _, bridge, _, school = connected
    bridge.invoke("sync", {})
    args = task_params(bridge)
    context = bridge.invoke("assignment_context", args)["data"]
    assert "Report requirements" in context["requirements"] and context["rubric"][0]["points"] == 10
    assert context["files"][0]["file_id"] == 88 and "source_url" not in context["files"][0]
    school.submission = "submitted"
    assert bridge.invoke("verify_submission", args)["data"]["status"] == "Confirmed Submitted"
    school.failure = requests.Timeout()
    result = bridge.invoke("verify_submission", args)["data"]
    current = state(bridge)
    assert result["status"] == "Unknown / Unable to Verify"
    assert current["tasks"][0]["status"] == "Unknown"
    assert current["tasks"][0]["verification"]["error_code"] == "network_or_timeout"
    assert len(current["history"]) == 2 and not current["local_history"]


def test_pushplus_secure_binding_acceptance_and_user_receipt_are_distinct(connected, monkeypatch):
    _, bridge, vault, _ = connected
    posts = []
    session = SimpleNamespace(post=lambda *args, **kwargs: (posts.append(kwargs), Response({"code": 200}))[1])
    monkeypatch.setattr(web_bridge, "PushPlusChannel", lambda token: PushPlusChannel(token, session=session))
    assert bridge.invoke("save_credential", {"kind": "pushplus", "value": "SYNTHETIC-PUSH-ONLY"})["ok"]
    assert not posts and vault.get("pushplus")
    assert not bridge.invoke("test_pushplus", {"confirmed": False})["ok"]
    result = bridge.invoke("test_pushplus", {"confirmed": True})["data"]
    assert len(posts) == 1 and result["status"] == "accepted" and not result["delivery_confirmed"]
    assert "SYNTHETIC-PUSH-ONLY" not in json.dumps(state(bridge))
    assert bridge.invoke("confirm_push_received", {"receipt_id": result["receipt_id"], "confirmed": True})[
        "ok"
    ]
    assert state(bridge)["pushplus"]["last_test"]["delivery_confirmed"] is True
    bridge.invoke("remove_credential", {"kind": "pushplus"})
    assert not vault.get("pushplus") and state(bridge)["pushplus"]["last_test"] is None


def test_settings_scheduler_definition_and_query_use_only_fakes(connected, monkeypatch):
    root, bridge, vault, _ = connected
    operations = []
    monkeypatch.setattr(schedule, "install_task", lambda path: operations.append(("install", path)))
    monkeypatch.setattr(schedule, "remove_all_tasks", lambda path: operations.append(("remove", path)))
    assert bridge.invoke("save_settings", {"settings": {"theme": "pink", "sync_interval_minutes": 30}})["ok"]
    assert not operations
    assert bridge.invoke("save_settings", {"settings": {"monitoring": True}})["ok"]
    assert operations == [("install", root)]
    assert load(root / "config.json")["monitoring"]
    xml = schedule.task_xml(
        root, "FAKE-USER", executable="C:\\QA\\Agent.exe", arguments="--scheduled"
    ).decode("utf-16")
    assert "--scheduled" in xml and str(root) in xml and "LeastPrivilege" in xml
    assert schedule.task_name(root) != schedule.task_name(root / "v1.1")
    monkeypatch.setattr(schedule, "task_info", lambda _: {"exists": True, "state": 3})
    monkeypatch.setattr(schedule, "deadline_task_info", lambda _: {"exists": False})
    assert bridge.invoke("runtime_status", {})["data"]["verified"]
    assert (
        Bridge(root, secrets_factory=lambda _: vault).invoke("get_state", {})["data"]["settings"]["theme"]
        == "pink"
    )
    bridge.invoke("save_settings", {"settings": {"monitoring": False}})
    assert operations[-1] == ("remove", root)


def test_native_copy_is_explicit_and_returns_no_clipboard_read_capability(connected):
    _, bridge, _, _ = connected
    bridge.invoke("sync", {})
    values = []
    bridge._native = SimpleNamespace(copy_text=lambda value: values.append(value))
    args = task_params(bridge) | {"mode": "standard", "confirmed": True}
    assert bridge.invoke("copy_prompt", args)["data"]["status"] == "copied"
    assert "Academic assistance request" in values[0] and "Report requirements" in values[0]
    assert not bridge.invoke("copy_prompt", args | {"confirmed": False})["ok"]
    assert bridge.invoke("emergency_prepare", task_params(bridge))["data"]["eligible"]


def test_qa_never_reads_default_dpapi_and_live_cannot_reuse_qa_profile(tmp_path, monkeypatch):
    from canvas_agent import app
    from canvas_agent.security import Secrets
    from canvas_agent.web_qa import seed

    seed(tmp_path)
    (tmp_path / "QA_ONLY.json").write_text('{"mode":"synthetic_only","schema":1}')
    monkeypatch.setattr(Secrets, "get", lambda *_: pytest.fail("QA must never read DPAPI"))
    bridge = Bridge(tmp_path, qa=True)
    assert set(state(bridge)["credentials"].values()) == {"missing"}
    monkeypatch.setattr("sys.argv", ["agent", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        app.main()


def test_busy_and_closed_bridges_do_not_start_duplicate_work(connected):
    _, bridge, _, school = connected
    bridge._mutex.acquire()
    assert bridge.invoke("sync", {})["error"] == "busy" and not school.calls
    bridge._mutex.release()
    bridge._close()
    assert bridge.invoke("sync", {})["error"] == "window_closed" and not school.calls


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"status": "ok"},
        {"status": "ok", "value": []},
        {"status": "ok", "value": {"summary": "short"}},
    ],
)
def test_ai_malformed_envelopes_have_explicit_safe_failure(response):
    from canvas_agent.ai_presentation import format_result
    from canvas_agent.announcement_intelligence import validate_response

    result = validate_response(response)
    assert result["status"] == "invalid_response" and result["reason"]
    assert "unchanged" in format_result(result)


def test_interval_and_optional_guardian_settings_keep_single_data_service(connected):
    root, bridge, _, _ = connected
    bridge.invoke("sync", {})
    current = load(root / "config.json") | {
        "monitoring": True,
        "sync_interval_minutes": 30,
        "guardian_24h_enabled": True,
        "guardian_repeat_enabled": False,
        "weekly_enabled": False,
    }
    store = Store(root)
    now = datetime.now(UTC)
    store.set("last_attempt", (now - timedelta(minutes=31)).isoformat())
    store.set("last_slot", now.isoformat())
    assert schedule.due_work(current, store, now)["run_id"].startswith("scheduled:interval:")
    plan = rebuild_plan(store, current, now)
    assert any(item["stage"] == "24h" for item in plan) and not any(
        item["stage"] == "repeat" for item in plan
    )
    store.close()


def test_ai_configuration_consent_and_actual_parser_failure_stay_separate(connected, monkeypatch):
    from canvas_agent import ai

    _, bridge, _, _ = connected
    requests_sent = []
    session = SimpleNamespace(
        post=lambda *args, **kwargs: (
            requests_sent.append(kwargs),
            Response({"choices": [{"message": {"content": "{}"}}]}),
        )[1]
    )
    original = ai.AIClient
    monkeypatch.setattr(
        ai, "AIClient", lambda config, key, secrets: original(config, key, session=session, secrets=secrets)
    )
    assert bridge.invoke("save_credential", {"kind": "ai", "value": "SYNTHETIC-AI-ONLY"})["ok"]
    assert not bridge.invoke("test_ai", {"confirmed": False})["ok"]
    assert not requests_sent
    assert bridge.invoke("save_settings", {"settings": {"ai_enabled": True, "ai_consent": True}})["ok"]
    result = bridge.invoke("test_ai", {"confirmed": True})["data"]
    assert result["status"] == "invalid_response" and len(requests_sent) == 1
    assert "Missing or invalid summary" in result["text"]
    assert "SYNTHETIC-AI-ONLY" not in json.dumps(state(bridge))
    assert state(bridge)["tasks"] == []


def test_account_switch_keeps_local_history_in_its_own_namespace(connected):
    root, bridge, _, school = connected
    bridge.invoke("sync", {})
    args = task_params(bridge)
    bridge.invoke("set_tracking", args | {"state": "ignored", "note": "account 71"})
    school.user = 72
    bridge.invoke("sync", {})
    assert not state(bridge)["local_history"] and state(bridge)["tasks"][0]["local"]["state"] == "tracking"
    school.user = 71
    bridge.invoke("sync", {})
    assert state(bridge)["local_history"][0]["note"] == "account 71"
    assert state(bridge)["tasks"][0]["local"]["state"] == "ignored"
    store = Store(root)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    store.close()


def test_full_candidate_cli_defaults_to_qa_and_retains_independent_monitor_routes(monkeypatch):
    import sys

    import integration_entry

    calls = []
    monkeypatch.setattr(integration_entry, "main", lambda: calls.append(sys.argv[1:]) or 0)
    assert integration_entry.entry([]) == 0 and calls[-1] == ["--mock"]
    integration_entry.entry(["--live", "--data-dir", "C:\\isolated-review"])
    assert calls[-1] == ["--data-dir", "C:\\isolated-review"]
    integration_entry.entry(["--scheduled", "--data-dir", "C:\\isolated-review"])
    assert "--mock" not in calls[-1] and "--scheduled" in calls[-1]
    integration_entry.entry(["--guardian", "--data-dir", "C:\\isolated-review"])
    assert "--guardian" in calls[-1] and "--mock" not in calls[-1]
    with pytest.raises(ValueError, match="explicit separate"):
        integration_entry.entry(["--live"])


@pytest.mark.parametrize("during_request", [False, True])
@pytest.mark.parametrize("model_status", ["ok", "busy"])
def test_weekly_ai_queue_and_inflight_supplement_recheck_tracking_revision(
    connected, during_request, model_status
):
    from canvas_agent.ai_jobs import drain, queue_job

    root, bridge, vault, _ = connected
    bridge.invoke("sync", {})
    config = load(root / "config.json") | {"ai_enabled": True, "ai_consent": True, "ai_weekly_enabled": True}
    save(root / "config.json", config)
    state_db = Store(root)
    queue_job(state_db, config, "weekly", {"week": "2026-W43", "body": "Read-only report"})
    if not during_request:
        Tracking(state_db).set(state_db.cached()[0], "ignored")
    state_db.close()
    requests_sent, deliveries = [], []

    class Model:
        def __init__(self, *args, **kwargs):
            pass

        def summarize(self, *args, **kwargs):
            requests_sent.append(True)
            changed = Store(root)
            Tracking(changed).set(changed.cached()[0], "ignored")
            changed.close()
            if model_status == "busy":
                return {"status": "busy"}
            return {"status": "ok", "summary": "Old report supplement", "todos": [], "dates": []}

    drain(
        root,
        ai_factory=Model,
        secrets_factory=lambda _: vault,
        channel_factory=lambda _: {"windows": SimpleNamespace(send=lambda *args: deliveries.append(args))},
    )
    assert bool(requests_sent) is during_request and not deliveries
    state_db = Store(root)
    assert not state_db.get("ai_pending_jobs", [])
    state_db.close()
