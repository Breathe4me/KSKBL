import json
import os
import sqlite3
import zipfile

import pytest

from canvas_agent.config import DEFAULTS, save
from canvas_agent.maintenance import backup, diagnostics, restore
from canvas_agent.models import Snapshot
from canvas_agent.security import Secrets, dpapi, plain, redact, safe_link
from canvas_agent.storage import Store


def test_partial_keeps_cache_without_calling_it_fresh(tmp_path, task, now):
    store = Store(tmp_path)
    store.snapshot(Snapshot([{"id": 1, "name": "C"}], [task], [], [(1, "assignments")], []), now)
    store.snapshot(
        Snapshot(
            [{"id": 1, "name": "C"}], [], [], [], [{"course_id": 1, "kind": "assignments", "code": "failed"}]
        ),
        now,
    )
    assert len(store.cached()) == 1 and store.get("last_complete") is False
    store.close()
    store = Store(tmp_path)
    assert len(store.cached()) == 1
    store.close()


def test_removed_course_hidden(tmp_path, task, now):
    store = Store(tmp_path)
    store.snapshot(Snapshot([{"id": 1}], [task], [], [(1, "assignments")], []), now)
    store.snapshot(Snapshot([], [], [], [], []), now)
    assert not store.cached()
    store.close()


def test_durable_claim(tmp_path, now):
    store = Store(tmp_path)
    assert store.claim("round:1", "windows", now)
    store.close()
    store = Store(tmp_path)
    assert not store.claim("round:1", "windows", now)
    assert store.claim("round:2", "windows", now)
    assert store.claim("round:1", "pushplus", now)
    store.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_real_dpapi_and_secret_file(tmp_path):
    secret = "synthetic-test-value-123"
    encrypted = dpapi(secret.encode(), True)
    assert secret.encode() not in encrypted
    assert dpapi(encrypted, False).decode() == secret
    vault = Secrets(tmp_path)
    vault.set("canvas", secret)
    assert vault.get("canvas") == secret
    assert secret.encode() not in (tmp_path / "canvas.dpapi").read_bytes()
    vault.set("canvas", "")
    assert vault.get("canvas") == ""


def test_redaction_and_link():
    assert "synthetic" not in redact("Bearer synthetic; token=synthetic", ["synthetic"])
    assert safe_link("https://canvas.example/a", "https://canvas.example")
    for url in ["javascript:alert(1)", "https://other.example/a", "https://canvas.example/a?token=oops"]:
        assert not safe_link(url, "https://canvas.example")
    assert "<" not in plain("<b>hello</b>")


def test_backup_restore_no_credentials(tmp_path, task, now, monkeypatch):
    monkeypatch.setattr("canvas_agent.schedule.remove_task", lambda _: None)
    monkeypatch.setattr("canvas_agent.schedule.remove_deadline_task", lambda _: None)
    save(tmp_path / "config.json", DEFAULTS)
    store = Store(tmp_path)
    store.snapshot(Snapshot([{"id": 1}], [task], [], [(1, "assignments")], []), now)
    store.close()
    archive = tmp_path / "backup.zip"
    backup(tmp_path, archive)
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == {"state.sqlite", "config.json"}
    store = Store(tmp_path)
    store.reset_account()
    store.close()
    restore(tmp_path, archive)
    store = Store(tmp_path)
    assert len(store.cached()) == 1
    store.close()
    diag = tmp_path / "diagnostics.json"
    diagnostics(tmp_path, diag)
    assert task.title not in diag.read_text()
    assert "courses" not in json.loads(diag.read_text())


def test_unsafe_backup_rejected(tmp_path):
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("../config.json", "{}")
    with pytest.raises(ValueError):
        restore(tmp_path, zpath)


def test_corrupt_and_future_database_not_reset(tmp_path):
    dbpath = tmp_path / "state.sqlite"
    dbpath.write_bytes(b"corrupt database")
    with pytest.raises(sqlite3.DatabaseError):
        Store(tmp_path)
    assert dbpath.read_bytes().startswith(b"corrupt")
    dbpath.unlink()
    db = sqlite3.connect(dbpath)
    db.execute("PRAGMA user_version=99")
    db.close()
    with pytest.raises(RuntimeError, match="newer"):
        Store(tmp_path)
