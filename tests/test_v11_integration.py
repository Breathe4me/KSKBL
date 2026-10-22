"""Cross-module acceptance, including HTTP adapter boundaries and minute-gate independence."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_engine import FakeSecrets
from test_v11_copilot import API, guardian_setup

from canvas_agent.config import save
from canvas_agent.engine import run
from canvas_agent.material_files import MAX_FILE, MaterialError, download_material
from canvas_agent.models import Snapshot, timestamp
from canvas_agent.storage import Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "state")
    yield value
    value.close()


class DownloadResponse:
    def __init__(self, data=b"material", status=200, headers=None):
        self.data, self.status_code, self.headers, self.closed = data, status, headers or {}, False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.data), chunk_size):
            yield self.data[offset : offset + chunk_size]

    def close(self):
        self.closed = True


class FileAPI(API):
    def __init__(self, metadata, responses):
        self.metadata, self.responses, self.download_calls = metadata, responses, []
        self.session = self

    def get(self, path, params=None, **kwargs):
        if path == "files/3":
            return self.metadata, None
        self.download_calls.append((path, kwargs))
        return self.responses.pop(0)


def metadata(url="https://canvas.example/files/3/download?verifier=PRIVATE"):
    return {"id": 3, "size": 10, "filename": "teacher notes.md", "url": url}


def test_download_retains_source_and_never_forwards_token_to_cdn(tmp_path):
    responses = [
        DownloadResponse(status=302, headers={"Location": "https://cdn.example/notes?signature=PRIVATE"}),
        DownloadResponse(b"# Teacher instructions"),
    ]
    api = FileAPI(metadata(), responses[:])
    result = download_material(api, 3, tmp_path / "materials", approved_hosts=("cdn.example",))
    assert result["status"] == "ok" and result["source_url"] == "https://canvas.example/files/3"
    assert "PRIVATE" not in str(result)
    assert api.download_calls[0][1]["headers"]["Authorization"] == "Bearer synthetic-key"
    assert api.download_calls[1][1]["headers"] == {}
    assert all(r.closed for r in responses)
    assert all(call[1]["allow_redirects"] is False for call in api.download_calls)


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.example/a",
        "https://bad.example/a",
        "https://u:p@canvas.example/a",
        "https://canvas.example:444/a",
    ],
)
def test_download_refuses_unapproved_sources(tmp_path, url):
    api = FileAPI(metadata(url), [])
    with pytest.raises(MaterialError):
        download_material(api, 3, tmp_path)
    assert not api.download_calls


def test_download_metadata_limits_conflicts_and_stream_bound(tmp_path):
    api = FileAPI(metadata() | {"size": MAX_FILE + 1}, [])
    with pytest.raises(MaterialError):
        download_material(api, 3, tmp_path)
    api = FileAPI(metadata(), [DownloadResponse(b"a" * (MAX_FILE + 1))])
    with pytest.raises(MaterialError):
        download_material(api, 3, tmp_path)
    api = FileAPI(metadata(), [DownloadResponse(b"one"), DownloadResponse(b"two")])
    first = download_material(api, 3, tmp_path)
    with pytest.raises(MaterialError):
        download_material(api, 3, tmp_path)
    from pathlib import Path

    assert Path(first["path"]).read_bytes() == b"one"


def test_independent_guardian_runs_between_daily_slots(config, task, now, tmp_path, monkeypatch):
    config.update(monitoring=True, guardian_enabled=True, canvas_url=API.base, weekly_enabled=False)
    due = now + timedelta(hours=4)
    task = replace(task, due=due.isoformat())
    state = Store(tmp_path)
    api, channel, _ = guardian_setup(state, task, config, now)
    api.identity = lambda: "mock-user"
    state.set("last_slot", now.isoformat())
    state.close()
    save(tmp_path / "config.json", config)
    monkeypatch.setattr("canvas_agent.engine.Secrets", FakeSecrets)
    monkeypatch.setattr("canvas_agent.guardian.update_schedule", lambda *a: None)
    result = run(
        tmp_path,
        scheduled=True,
        now=due - timedelta(minutes=60),
        api_factory=lambda *a: api,
        channel_factory=lambda _: {"windows": channel},
    )
    assert result["status"] == "not_due" and len(channel.calls) == 1
    assert api.calls[-1][0].endswith("/submissions/self")


def test_fresh_sync_emergency_dedup_with_strong_reminder(config, task, now, tmp_path, monkeypatch):
    config.update(monitoring=True, guardian_enabled=True, canvas_url=API.base, weekly_enabled=False)
    task = replace(task, due=(now + timedelta(minutes=50)).isoformat())
    save(tmp_path / "config.json", config)
    api = API()
    api.raw["due_at"] = task.due
    api.identity = lambda: "mock-user"
    api.courses = lambda _: [{"id": 1, "name": "COMP1234"}]
    api.sync = lambda _: Snapshot([{"id": 1}], [task], [], [(1, "assignments")], [])
    from test_ai_notifications import Channel

    channel = Channel()
    monkeypatch.setattr("canvas_agent.engine.Secrets", FakeSecrets)
    monkeypatch.setattr("canvas_agent.guardian.update_schedule", lambda *a: None)
    result = run(
        tmp_path, now=now, api_factory=lambda *a: api, channel_factory=lambda _: {"windows": channel}
    )
    assert result["status"] == "ok" and len(channel.calls) == 1
    assert "Deadline Guardian" in channel.calls[0][0]


def test_confirmed_tasks_have_no_future_deadline_triggers(store, task, config, now):
    from canvas_agent.guardian import rebuild_plan

    guardian_setup(store, replace(task, status="Confirmed Submitted"), config, now)
    assert rebuild_plan(store, config, now) == []


def test_guardian_processing_keeps_reminder(store, task, config):
    from canvas_agent.guardian import tick

    due = timestamp(task.due)
    api, channel, dispatcher = guardian_setup(
        store, task, config, due, submission={"workflow_state": "processing"}
    )
    result = tick(store, config, api, dispatcher, due - timedelta(minutes=15))
    assert result[0]["status"] == "Pending / Processing" and len(channel.calls) == 1
