"""SQLite transactions, scope snapshots, notification receipts, bounded event logs."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "state.sqlite", timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.DatabaseError:
            self.db.close()
            raise
        if version > 2:
            self.db.close()
            raise RuntimeError("Database was created by a newer application")
        needs_local_history = (
            version == 2
            and not self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_tracking_history'"
            ).fetchone()
        )
        if version == 1 or needs_local_history:
            # SQLite backup API includes committed WAL pages. Never open v1.1 in place.
            backup_path = self.root / (
                "pre-v12-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f") + ".sqlite"
            )
            with closing(sqlite3.connect(backup_path)) as target:
                self.db.backup(target)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            schema = """
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scopes (
                course_id INTEGER, kind TEXT, data TEXT NOT NULL, checked TEXT NOT NULL,
                PRIMARY KEY(course_id, kind));
            CREATE TABLE IF NOT EXISTS delivery (
                key TEXT, channel TEXT, status TEXT NOT NULL, updated TEXT NOT NULL,
                PRIMARY KEY(key, channel));
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, at TEXT NOT NULL, code TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS local_tracking (
                account TEXT, task_key TEXT, state TEXT NOT NULL, reason TEXT NOT NULL,
                note TEXT NOT NULL, fingerprint TEXT NOT NULL, updated TEXT NOT NULL,
                PRIMARY KEY(account, task_key));
            CREATE TABLE IF NOT EXISTS local_tracking_history (
                id INTEGER PRIMARY KEY, account TEXT NOT NULL, task_key TEXT NOT NULL,
                state TEXT NOT NULL, reason TEXT NOT NULL, note TEXT NOT NULL, at TEXT NOT NULL);
            PRAGMA user_version=2;
            """
            for statement in schema.split(";"):
                if statement.strip():
                    self.db.execute(statement)

    def close(self):
        self.db.close()

    def mark_submitted(self, key, now):
        self.update_task(key, {"status": "Confirmed Submitted", "checked": now.isoformat()})

    def ensure_submission_rules(self):
        # Older caches may have interpreted a historical submitted_at as success.
        # Require fresh verification before those cached confirmations cancel alerts.
        if self.get("submission_rules_version") == 2:
            return
        for task in self.cached():
            if task.get("status") == "Confirmed Submitted":
                self.update_task(task["key"], {"status": "Unknown"})
        self.set("submission_rules_version", 2)

    def update_task(self, key, fields):
        with self.db:
            for row in self.db.execute(
                "SELECT course_id,kind,data FROM scopes WHERE kind != ?", ("announcements",)
            ).fetchall():
                items = json.loads(row["data"])
                changed = False
                for item in items:
                    if item["key"] == key:
                        item.update(fields)
                        changed = True
                if changed:
                    self.db.execute(
                        "UPDATE scopes SET data=? WHERE course_id=? AND kind=?",
                        (json.dumps(items), row["course_id"], row["kind"]),
                    )

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def event(self, code, detail=""):
        # Callers pass stable codes and counts only. Never exception strings or HTTP bodies.
        with self.db:
            self.db.execute(
                "INSERT INTO events(at,code,detail) VALUES(?,?,?)",
                (datetime.now(UTC).isoformat(), code, str(detail)[:1000]),
            )
            self.db.execute("DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-1000 FROM events)")

    def events(self):
        return [
            dict(r) for r in self.db.execute("SELECT at,code,detail FROM events ORDER BY id DESC LIMIT 100")
        ]

    def snapshot(self, snap, now):
        with self.db:
            for cid, kind in snap.successful:
                items = snap.announcements if kind == "announcements" else snap.tasks
                data = [
                    x.to_dict()
                    for x in items
                    if x.course_id == cid and (kind == "announcements" or x.kind == kind)
                ]
                self.db.execute(
                    "INSERT OR REPLACE INTO scopes VALUES (?,?,?,?)",
                    (cid, kind, json.dumps(data), now.isoformat()),
                )
            # A fallback can discover fresh items without enumerating the full scope.
            # Merge them individually; retain old records with their original check time.
            for cid, kind in {(t.course_id, t.kind) for t in snap.tasks} - set(snap.successful):
                row = self.db.execute(
                    "SELECT data,checked FROM scopes WHERE course_id=? AND kind=?", (cid, kind)
                ).fetchone()
                merged = (
                    {x["key"]: x | {"checked": x.get("checked", row[1])} for x in json.loads(row[0])}
                    if row
                    else {}
                )
                for task in snap.tasks:
                    if task.course_id == cid and task.kind == kind:
                        merged[task.key] = task.to_dict() | {"checked": now.isoformat()}
                self.db.execute(
                    "INSERT OR REPLACE INTO scopes VALUES (?,?,?,?)",
                    (cid, kind, json.dumps(list(merged.values())), now.isoformat()),
                )
            for key, value in (
                ("courses", snap.courses),
                ("failures", snap.failures),
                ("capabilities", snap.capabilities),
                ("last_check", now.isoformat()),
                ("last_complete", snap.complete),
                ("last_status", snap.status),
                ("last_sync_ok", not snap.failures),
            ):
                self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))
            if not snap.failures:
                self.db.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('last_success',?)", (json.dumps(now.isoformat()),)
                )
            if snap.complete:
                self.db.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('last_full_success',?)",
                    (json.dumps(now.isoformat()),),
                )

    def cached(self, kind="tasks"):
        query = (
            "SELECT * FROM scopes WHERE kind = ?"
            if kind == "announcements"
            else "SELECT * FROM scopes WHERE kind != ?"
        )
        rows = self.db.execute(query, ("announcements",))
        courses = {c["id"] for c in self.get("courses", [])}
        items = {}
        for row in rows:
            if row["course_id"] not in courses:
                continue
            for item in json.loads(row["data"]):
                item["checked"] = item.get("checked", row["checked"])
                # Prefer the assignment record over a standalone quiz fallback.
                if item["key"] not in items or item.get("kind") == "assignments":
                    items[item["key"]] = item
        return list(items.values())

    def delivery_status(self, key, channel):
        row = self.db.execute(
            "SELECT status FROM delivery WHERE key=? AND channel=?", (key, channel)
        ).fetchone()
        return row[0] if row else None

    def reserve_ai(self, key, digest, limit, now, force=False):
        """Atomic per-content reservation and shared daily budget; never store request text."""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            cached = json.loads(row[0]) if row else None
            if cached and not force:
                return cached | {"cached": True}
            budget_key = "ai_budget:" + now.date().isoformat()
            used = self.get(budget_key, 0)
            if used >= limit:
                return {"status": "daily_budget_exhausted", "cached": False}
            pending = {"status": "request_in_progress", "digest": digest}
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(pending)))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (budget_key, json.dumps(used + 1)))
        return None

    def finish_ai(self, key, pointer, result, expected_account):
        """An old account's slow provider response cannot populate a new account."""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.get("account") != expected_account:
                return {"status": "stale_context"}
            for name in (key, pointer):
                self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (name, json.dumps(result)))
        return result

    def claim(self, key, channel, now):
        with self.db:
            row = self.db.execute(
                "SELECT status FROM delivery WHERE key=? AND channel=?", (key, channel)
            ).fetchone()
            if row and row[0] in ("sent", "uncertain", "rejected"):
                return False
            attempt_key = "delivery_attempt:" + channel + ":" + key
            attempt = self.get(attempt_key, {"count": 0, "at": None})
            if attempt["count"] >= 3 or (
                attempt["at"] and now - datetime.fromisoformat(attempt["at"]) < timedelta(minutes=15)
            ):
                return False
            self.db.execute(
                "INSERT OR REPLACE INTO meta VALUES (?,?)",
                (attempt_key, json.dumps({"count": attempt["count"] + 1, "at": now.isoformat()})),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO delivery VALUES (?,?,?,?)",
                (key, channel, "uncertain", now.isoformat()),
            )
        return True

    def receipt(self, key, channel, ok, now):
        with self.db:
            self.db.execute(
                "UPDATE delivery SET status=?, updated=? WHERE key=? AND channel=?",
                ("sent" if ok else "failed", now.isoformat(), key, channel),
            )

    def backup(self, destination):
        target = sqlite3.connect(destination)
        try:
            self.db.backup(target)
        finally:
            target.close()

    def reset_account(self):
        with self.db:
            for statement in (
                "DELETE FROM meta",
                "DELETE FROM scopes",
                "DELETE FROM delivery",
                "DELETE FROM events",
            ):
                self.db.execute(statement)
