"""Explicit offline import. Validate and migrate a staging copy before touching live data."""

import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .config import atomic_write, load, save
from .security import ProcessLock
from .storage import Store


def import_backup(root, archive):
    root = Path(root)
    with ProcessLock(root), tempfile.TemporaryDirectory(dir=root, prefix=".import-") as name:
        stage = Path(name)
        with zipfile.ZipFile(archive) as zipped:
            if sorted(zipped.namelist()) != ["config.json", "state.sqlite"] or any(
                entry.file_size > 50_000_000 or entry.compress_size == 0 for entry in zipped.infolist()
            ):
                raise ValueError("Invalid or oversized local backup")
            for filename in ("config.json", "state.sqlite"):
                (stage / filename).write_bytes(zipped.read(filename))
        config = load(stage / "config.json") | {"monitoring": False}
        with closing(sqlite3.connect(stage / "state.sqlite")) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Invalid backup database")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            required = {"meta", "scopes", "delivery", "events"}
            if version not in (1, 2) or not required <= {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }:
                raise ValueError("Unsupported backup database")
        migrated = Store(stage)
        try:
            migrated.set("guardian_plan", [])
            migrated.backup(stage / "ready.sqlite")
        finally:
            migrated.close()
        # A recovery directory is independent of the selected source ZIP and contains no credentials.
        recovery = root / ("before-import-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f"))
        recovery.mkdir()
        previous = Store(root)
        try:
            previous.backup(recovery / "state.sqlite")
        finally:
            previous.close()
        had_config = (root / "config.json").exists()
        if had_config:
            shutil.copy2(root / "config.json", recovery / "config.json")
        # No scheduler registration or removal is required: every wake checks monitoring=False.
        try:
            for suffix in ("-wal", "-shm"):
                (root / ("state.sqlite" + suffix)).unlink(missing_ok=True)
            atomic_write(root / "state.sqlite", (stage / "ready.sqlite").read_bytes())
            save(root / "config.json", config)
        except Exception:
            atomic_write(root / "state.sqlite", (recovery / "state.sqlite").read_bytes())
            if had_config:
                atomic_write(root / "config.json", (recovery / "config.json").read_bytes())
            else:
                (root / "config.json").unlink(missing_ok=True)
            raise
        return {"status": "imported", "backup": str(recovery), "schema": 2}
