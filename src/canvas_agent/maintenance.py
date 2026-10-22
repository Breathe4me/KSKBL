"""Explicit, local backup/restore. Credentials never enter backups or diagnostics."""

import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from . import __version__
from .config import atomic_write, load, save
from .security import ProcessLock
from .storage import Store


def diagnostics(root, destination):
    store = Store(root)
    try:
        result = {
            "version": __version__,
            "last_complete": store.get("last_complete"),
            "last_check": store.get("last_check"),
            "events": store.events(),
            "failed_scopes": [{"kind": x["kind"], "code": x["code"]} for x in store.get("failures", [])],
        }
        atomic_write(destination, json.dumps(result, indent=2).encode())
    finally:
        store.close()


def backup(root, destination):
    with ProcessLock(root), tempfile.TemporaryDirectory() as tmp:
        store = Store(root)
        try:
            store.backup(Path(tmp) / "state.sqlite")
        finally:
            store.close()
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(Path(tmp) / "state.sqlite", "state.sqlite")
            z.writestr("config.json", json.dumps(load(root / "config.json") | {"monitoring": False}))


def restore(root, source):
    with ProcessLock(root), tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(source) as z:
            if sorted(z.namelist()) != ["config.json", "state.sqlite"] or any(
                i.file_size > 50_000_000 or i.compress_size == 0 for i in z.infolist()
            ):
                raise ValueError("Invalid or oversized backup")
            for name in ("state.sqlite", "config.json"):
                (Path(tmp) / name).write_bytes(z.read(name))
        config = load(Path(tmp) / "config.json") | {"monitoring": False}
        db = sqlite3.connect(f"file:{(Path(tmp) / 'state.sqlite').as_posix()}?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute(
                "PRAGMA user_version"
            ).fetchone()[0] not in (1, 2):
                raise ValueError("Invalid database backup")
            required = {"meta", "scopes", "delivery", "events"}
            if not required <= {
                r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }:
                raise ValueError("Invalid database schema")
        finally:
            db.close()
        # Preserve a consistent recovery backup before replacing either file.
        previous = Store(root)
        try:
            previous.backup(root / "pre-restore.sqlite")
        finally:
            previous.close()
        if (root / "config.json").exists():
            shutil.copy2(root / "config.json", root / "pre-restore-config.json")
        from .schedule import remove_all_tasks as remove_task

        remove_task(root)
        for suffix in ("-wal", "-shm"):
            (root / f"state.sqlite{suffix}").unlink(missing_ok=True)
        atomic_write(root / "state.sqlite", (Path(tmp) / "state.sqlite").read_bytes())
        save(root / "config.json", config)


def clear(root):
    from .schedule import remove_all_tasks as remove_task

    with ProcessLock(root):
        remove_task(root)
        materials = root.resolve() / "materials"
        if materials.exists():
            from .material_files import _no_reparse

            _no_reparse(materials)
            for path in materials.rglob("*"):
                _no_reparse(path)
            shutil.rmtree(materials)
        for name in (
            "config.json",
            "state.sqlite",
            "state.sqlite-wal",
            "state.sqlite-shm",
            "canvas.dpapi",
            "pushplus.dpapi",
            "ai.dpapi",
            "pre-restore.sqlite",
            "pre-restore-config.json",
        ):
            (root / name).unlink(missing_ok=True)
        for file in root.glob("ai-*.dpapi"):
            if re.fullmatch(r"ai-[a-f0-9]{64}\.dpapi", file.name):
                file.unlink(missing_ok=True)
