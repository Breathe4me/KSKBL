"""Synthetic fixtures shared by offline tests and an explicitly authorized future VM preview."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import DEFAULTS, save
from .models import Announcement, Snapshot, Status, Task
from .storage import Store
from .tracking import Tracking


def backup_config(root):
    path = Path(root) / "config.json"
    if not path.is_file():
        return None
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    directory = Path(root) / "config-backups"
    directory.mkdir(exist_ok=True)
    target = directory / ("config-" + digest + ".json.bak")
    if not target.exists():
        with target.open("xb") as stream:
            stream.write(original)
    if target.read_bytes() != original:
        raise ValueError("QA configuration backup integrity failed")
    return target


def prepare_qa_root(root):
    root = Path(root)
    marker = root / "QA_ONLY.json"
    if root.exists() and any(root.iterdir()):
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != {
            "mode": "synthetic_only",
            "schema": 1,
        }:
            raise ValueError("Refusing to use a nonempty, unmarked data directory")
    else:
        seed(root)
        marker.write_text(json.dumps({"mode": "synthetic_only", "schema": 1}), encoding="utf-8")
    # Preserve before any configuration loading/compatibility inspection. Never reset bad data.
    backup_config(root)
    return root


def seed(root):
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("Synthetic fixture requires a fresh empty directory")
    save(root / "config.json", DEFAULTS | {"language": "zh", "canvas_url": "https://canvas.example"})
    now = datetime.now(UTC)
    definitions = [
        (1, "COMP5618", "Security Review Report", 52, Status.NOT_SUBMITTED),
        (2, "INFO5990", "QA and Testing Plans", 4320, Status.NOT_SUBMITTED),
        (3, "IDEA9106", "Progress Presentation", 8640, Status.SUBMITTED),
        (4, "COMP5048", "Tutorial Quiz", 480, Status.NOT_SUBMITTED),
        (5, "COMP5618", "Optional Reading Exercise", 14400, Status.NOT_SUBMITTED),
    ]
    tasks = [
        Task(
            f"{cid}:assignment:{cid}",
            cid,
            course,
            title,
            "assignments",
            (now + timedelta(minutes=minutes)).isoformat(),
            status,
            "",
        )
        for cid, course, title, minutes, status in definitions
    ]
    store = Store(root)
    try:
        store.set("account", hashlib.sha256(b"synthetic:ui-review-only").hexdigest())
        store.snapshot(
            Snapshot(
                [{"id": cid, "name": course, "course_code": course} for cid, course, *_ in definitions],
                tasks,
                [
                    Announcement(
                        "1:announcement:1",
                        1,
                        "COMP5618",
                        "Synthetic QA announcement",
                        now.isoformat(),
                        now.isoformat(),
                        "Synthetic announcement text. Review the official rubric before submission.",
                        "",
                    )
                ],
                [(cid, "assignments") for cid, *_ in definitions] + [(1, "announcements")],
                [],
            ),
            now,
        )
        Tracking(store).set(tasks[3].to_dict(), "completed", "other_submission")
        Tracking(store).set(tasks[4].to_dict(), "ignored", "optional")
        store.set(
            "verification_history",
            [
                {
                    "key": tasks[2].key,
                    "checked": now.isoformat(),
                    "status": tasks[2].status,
                    "attempt": 1,
                    "error": "Synthetic fixture only; no Canvas request",
                }
            ],
        )
    finally:
        store.close()
