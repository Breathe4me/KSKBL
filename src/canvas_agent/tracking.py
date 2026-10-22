"""Account-scoped local choices; Canvas status is never rewritten by a local action."""

import hashlib
import json
from datetime import UTC, datetime

STATES = ("tracking", "completed", "ignored")
REASONS = ("", "other_submission", "group_submission", "optional", "other")


def fingerprint(task):
    return hashlib.sha256(
        json.dumps(
            {k: task.get(k) for k in ("title", "due", "unlock", "lock", "points")},
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


class Tracking:
    def __init__(self, store):
        self.store = store

    def scope(self):
        return self.store.get("account")

    def get(self, task):
        scope = self.scope()
        row = self.store.db.execute(
            "SELECT state,reason,note,fingerprint,updated FROM local_tracking WHERE account=? AND task_key=?",
            (scope or "", task["key"]),
        ).fetchone()
        if not row:
            return {"state": "tracking", "reason": "", "note": "", "content_changed": False}
        result = dict(row)
        result["content_changed"] = result.pop("fingerprint") != fingerprint(task)
        return result

    def set(self, task, state, reason="", note="", now=None):
        scope = self.scope()
        if not scope:
            raise ValueError("Verify a Canvas account before setting local tracking")
        if state not in STATES or reason not in REASONS or not isinstance(note, str) or len(note) > 500:
            raise ValueError("Invalid local tracking choice")
        if not str(task["key"]).startswith(str(int(task["course_id"])) + ":"):
            raise ValueError("Invalid task identity")
        with self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO local_tracking VALUES (?,?,?,?,?,?,?)",
                (
                    scope,
                    task["key"],
                    state,
                    reason,
                    note,
                    fingerprint(task),
                    (now or datetime.now(UTC)).isoformat(),
                ),
            )
            # Cancel a previously planned Guardian immediately, even before a re-sync.
            self.store.db.execute("DELETE FROM meta WHERE key='guardian_plan'")
            self.store.db.execute(
                "INSERT OR REPLACE INTO meta VALUES (?,?)",
                ("tracking_revision", json.dumps(self.store.get("tracking_revision", 0) + 1)),
            )
            self.store.db.execute(
                "INSERT INTO local_tracking_history(account,task_key,state,reason,note,at) VALUES(?,?,?,?,?,?)",
                (scope, task["key"], state, reason, note, (now or datetime.now(UTC)).isoformat()),
            )
            self.store.db.execute(
                "DELETE FROM local_tracking_history WHERE account=? AND id NOT IN "
                "(SELECT id FROM local_tracking_history WHERE account=? ORDER BY id DESC LIMIT 500)",
                (scope, scope),
            )

    def history(self):
        return [
            dict(row)
            for row in self.store.db.execute(
                "SELECT task_key AS key,state,reason,note,at FROM local_tracking_history "
                "WHERE account=? ORDER BY id DESC LIMIT 100",
                (self.scope() or "",),
            )
        ]

    def active(self, task):
        return self.get(task)["state"] == "tracking"

    def rows(self):
        return [task | {"local": self.get(task)} for task in self.store.cached()]
