from dataclasses import replace
from datetime import timedelta

from test_ai_notifications import Channel

from canvas_agent.api import APIError
from canvas_agent.config import save
from canvas_agent.engine import run
from canvas_agent.models import Announcement, Snapshot
from canvas_agent.storage import Store


class FakeSecrets:
    def __init__(self, root):
        pass

    def get(self, name):
        return "synthetic-credential"

    def values(self):
        return ["synthetic-credential"]


def setup(tmp_path, config, monkeypatch, task):
    config.update(canvas_url="https://canvas.example", monitoring=True, weekly_enabled=False)
    save(tmp_path / "config.json", config)
    monkeypatch.setattr("canvas_agent.engine.Secrets", FakeSecrets)

    class FakeAPI:
        base = "https://canvas.example"
        failed = False
        tasks = [task]
        announcements = [
            Announcement("1:announcement:5", 1, "C", "Old", None, "2026-10-01T00:00:00Z", "Body", "")
        ]
        partial = False

        def __init__(self, *args):
            pass

        def identity(self):
            if self.failed:
                raise APIError("network_or_timeout")
            return "123"

        def get(self, path, params=None):
            item = next(t for t in self.tasks if t.key.split(":")[-1] == path.split("/")[3])
            if path.endswith("/submissions/self"):
                state = "submitted" if item.completed else "unsubmitted"
                return {"assignment_id": int(item.key.split(":")[-1]), "workflow_state": state}, None
            return {"id": int(item.key.split(":")[-1]), "due_at": item.due}, None

        def courses(self, include_ended):
            return [{"id": 1, "name": "C"}]

        def sync(self, courses):
            return Snapshot(
                courses,
                self.tasks if not self.partial else [],
                self.announcements,
                [(1, "announcements")]
                if self.partial
                else [(1, "assignments"), (1, "quizzes"), (1, "announcements")],
                [{"course_id": 1, "kind": "assignments", "code": "failed"}] if self.partial else [],
            )

    channel = Channel()

    def factory(_):
        return {"windows": channel}

    return FakeAPI, channel, factory


def test_restart_strong_repeats_and_submitted_stops(tmp_path, config, monkeypatch, task, now):
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    run(tmp_path, now=now, api_factory=api, channel_factory=factory)
    assert len(channel.calls) == 1  # historical announcements baselined
    run(tmp_path, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)
    assert len(channel.calls) == 2
    api.tasks = [replace(task, status="Confirmed Submitted")]
    run(tmp_path, now=now + timedelta(minutes=40), api_factory=api, channel_factory=factory)
    assert len(channel.calls) == 2


def test_failed_scope_never_reminds_from_stale_data(tmp_path, config, monkeypatch, task, now):
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    run(tmp_path, now=now, api_factory=api, channel_factory=factory)
    api.partial = True
    result = run(tmp_path, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)
    assert result["status"] == "partial" and len(channel.calls) == 1
    store = Store(tmp_path)
    assert len(store.cached()) == 1 and store.get("last_complete") is False
    store.close()


def test_network_failure_not_empty_success(tmp_path, config, monkeypatch, task, now):
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    run(tmp_path, now=now, api_factory=api, channel_factory=factory)
    api.failed = True
    result = run(tmp_path, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)
    assert result["complete"] is False and len(channel.calls) == 1
    store = Store(tmp_path)
    assert store.cached() and store.get("failures")[0]["code"] == "network_or_timeout"
    store.close()


def test_announcement_updated_once(tmp_path, config, monkeypatch, task, now):
    config["strong_enabled"] = False
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    run(tmp_path, now=now, api_factory=api, channel_factory=factory)
    assert not channel.calls
    api.announcements = [replace(api.announcements[0], body="Updated body")]
    run(tmp_path, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)
    run(tmp_path, now=now + timedelta(minutes=40), api_factory=api, channel_factory=factory)
    assert len(channel.calls) == 1


def test_scheduled_gate_weekly_once(tmp_path, config, monkeypatch, task, now):
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    config["weekly_enabled"] = True
    config["strong_enabled"] = False
    save(tmp_path / "config.json", config)
    result = run(tmp_path, scheduled=True, now=now, api_factory=api, channel_factory=factory)
    assert result["status"] == "ok" and len(channel.calls) == 1
    result = run(
        tmp_path, scheduled=True, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory
    )
    assert result["status"] == "not_due" and len(channel.calls) == 1


def test_new_task_normal_notification_outside_strong_window(tmp_path, config, monkeypatch, task, now):
    config["strong_enabled"] = False
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    run(tmp_path, now=now, api_factory=api, channel_factory=factory)
    api.tasks = [task, replace(task, key="1:assignment:3", title="New task", due="2026-11-01T00:00:00Z")]
    run(tmp_path, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)
    assert len(channel.calls) == 1 and "New task" in channel.calls[0][1]


def test_partial_linked_quiz_does_not_override_confirmed_assignment(tmp_path, config, monkeypatch, task, now):
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    api.tasks = [replace(task, status="Confirmed Submitted")]
    run(tmp_path, now=now, api_factory=api, channel_factory=factory)

    def partial(_self, courses):
        return Snapshot(
            courses,
            [replace(task, kind="quizzes", status="Unknown")],
            [],
            [(1, "quizzes")],
            [{"course_id": 1, "kind": "assignments", "code": "failed"}],
        )

    monkeypatch.setattr(api, "sync", partial)
    run(tmp_path, now=now + timedelta(minutes=20), api_factory=api, channel_factory=factory)
    assert not channel.calls


def test_weekly_ai_failure_keeps_regular_report(tmp_path, config, monkeypatch, task, now):
    api, channel, factory = setup(tmp_path, config, monkeypatch, task)
    config.update(
        weekly_enabled=True, strong_enabled=False, ai_enabled=True, ai_consent=True, ai_weekly_enabled=True
    )
    save(tmp_path / "config.json", config)
    calls = []

    class FakeAI:
        def __init__(self, *args, **kwargs):
            pass

        def summarize(self, *args, **kwargs):
            calls.append(kwargs)
            return {"status": "failed_fallback"}

    from canvas_agent.ai_jobs import drain

    monkeypatch.setattr("canvas_agent.ai_jobs.start_worker", lambda root: None)
    run(tmp_path, scheduled=True, now=now, api_factory=api, channel_factory=factory)
    assert not calls and len(channel.calls) == 1
    drain(tmp_path, now=now, ai_factory=FakeAI, secrets_factory=FakeSecrets, channel_factory=factory)
    assert len(calls) == 1 and len(channel.calls) == 1
    assert "Current synchronized data" in channel.calls[0][1]
