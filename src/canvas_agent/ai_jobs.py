"""Optional AI jobs. Network work never holds the monitor lock or the GUI busy flag."""

import hashlib
import json
import threading
from datetime import UTC, datetime

from .ai import AIClient
from .ai_cache import cached_request
from .announcement_intelligence import summarize_one
from .config import load
from .models import Announcement
from .notifications import Dispatcher, PushPlusChannel, WindowsChannel
from .rules import Message
from .security import AlreadyRunning, ProcessLock, Secrets, ai_key
from .storage import Store

_WORKERS = {}
_WORKERS_LOCK = threading.Lock()


def _eligible(config, purpose):
    return (
        config["ai_enabled"]
        and config["ai_consent"]
        and config["ai_weekly_enabled" if purpose == "weekly" else "ai_announcements_enabled"]
    )


def queue_job(store, config, purpose, value):
    if not _eligible(config, purpose):
        return
    job = {
        "purpose": purpose,
        "value": value,
        "account": store.get("account"),
        "course_scope": config["course_ids"],
    }
    if purpose == "weekly":
        job["tracking_revision"] = store.get("tracking_revision", 0)
    job["id"] = hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        jobs = store.get("ai_pending_jobs", [])
        if not any(j["id"] == job["id"] for j in jobs):
            # A bounded queue; existing jobs survive. Future syncs can enqueue the remainder.
            jobs.append(job)
        store.db.execute(
            "INSERT OR REPLACE INTO meta VALUES (?,?)",
            ("ai_pending_jobs", json.dumps(jobs[:200])),
        )


def _pop(store):
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        jobs = store.get("ai_pending_jobs", [])
        if not jobs:
            return None
        job = jobs.pop(0)
        store.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", ("ai_pending_jobs", json.dumps(jobs)))
    return job


def drain(root, now=None, ai_factory=AIClient, secrets_factory=Secrets, channel_factory=None):
    """Single independent worker across processes, with per-request durable reservations."""
    now = now or datetime.now(UTC)
    requested = 0
    try:
        with ProcessLock(root / ".ai-worker"):
            state = Store(root)
            try:
                for _ in range(200):
                    config = load(root / "config.json")
                    if requested >= config["ai_announcement_limit"]:
                        break
                    job = _pop(state)
                    if job is None:
                        break
                    if (
                        not _eligible(config, job["purpose"])
                        or state.get("account") != job["account"]
                        or job.get("course_scope") != config["course_ids"]
                        or (
                            job["purpose"] == "weekly"
                            and job.get("tracking_revision", 0) != state.get("tracking_revision", 0)
                        )
                    ):
                        continue
                    secrets = secrets_factory(root)
                    token = secrets.get("canvas")
                    scope = hashlib.sha256((config["canvas_url"] + ":" + token).encode()).hexdigest()
                    if scope != state.get("credential_scope"):
                        continue
                    client = ai_factory(config, ai_key(secrets, config), secrets=secrets.values())
                    if job["purpose"] == "announcement":
                        ann = next(
                            (a for a in state.cached("announcements") if a["key"] == job["value"]),
                            None,
                        )
                        if ann is None or (
                            config["course_ids"] is not None and ann["course_id"] not in config["course_ids"]
                        ):
                            continue
                        result = summarize_one(ann, client, state, config["language"])
                        if state.get("account") == job["account"]:
                            state.set(
                                "ai_result", result | {"dates": [d["text"] for d in result.get("dates", [])]}
                            )
                    else:
                        value = job["value"]
                        digest = hashlib.sha256(
                            json.dumps(
                                [
                                    value,
                                    config["ai_url"],
                                    config["ai_model"],
                                    config["language"],
                                    config["ai_temperature"],
                                    config["ai_max_tokens"],
                                ],
                                sort_keys=True,
                            ).encode()
                        ).hexdigest()
                        source = Announcement(
                            "weekly-summary", 0, "", "Weekly learning report", None, None, value["body"], ""
                        )
                        result = cached_request(
                            state,
                            "ai_weekly_result",
                            digest,
                            config,
                            lambda client=client, source=source, language=config["language"]: (
                                client.summarize([source], language, purpose="weekly learning summary")
                            ),
                            now=now,
                        )
                        # A separate optional supplement; the official weekly report was already delivered.
                        current = load(root / "config.json")
                        if (
                            result["status"] == "ok"
                            and state.get("account") == job["account"]
                            and _eligible(current, "weekly")
                            and current["course_ids"] == job.get("course_scope")
                            and state.get("tracking_revision", 0) == job.get("tracking_revision", 0)
                        ):
                            channels = (
                                channel_factory(secrets)
                                if channel_factory
                                else {
                                    "windows": WindowsChannel(),
                                    "pushplus": PushPlusChannel(secrets.get("pushplus")),
                                }
                            )
                            supplement = Message(
                                "weekly-ai:" + value["week"],
                                "AI weekly supplement / AI 周报补充（非官方）",
                                result["label"]
                                + "\n"
                                + result["summary"]
                                + "\n"
                                + "\n".join(result["todos"] + result["dates"]),
                                weekly=True,
                                tracking_revision=job.get("tracking_revision", 0),
                            )
                            Dispatcher(state, channels, secrets.values(), current["canvas_url"]).send(
                                supplement, current["weekly_channels"], now
                            )
                    requested += bool(result.get("request_made") and not result.get("cached"))
                    if result["status"] in ("busy", "daily_budget_exhausted") and (
                        job["purpose"] != "weekly"
                        or state.get("tracking_revision", 0) == job.get("tracking_revision", 0)
                    ):
                        queue_job(state, config, job["purpose"], job["value"])
                        break
            finally:
                state.close()
    except AlreadyRunning:
        pass
    return requested


def start_worker(root):
    config = load(root / "config.json")
    if not any(_eligible(config, purpose) for purpose in ("weekly", "announcement")):
        return None
    key = str(root.resolve())
    with _WORKERS_LOCK:
        previous = _WORKERS.get(key)
        if previous and previous.is_alive():
            return previous

        def work():
            try:
                drain(root)
            except Exception:
                state = Store(root)
                try:
                    state.event("ai_worker_failed")  # stable code only
                finally:
                    state.close()
            finally:
                with _WORKERS_LOCK:
                    if _WORKERS.get(key) is threading.current_thread():
                        _WORKERS.pop(key, None)

        # Non-daemon keeps a scheduled process alive to finish its own isolated AI job.
        # Scheduler Parallel + the short core ProcessLock keeps minute checks independent.
        worker = threading.Thread(target=work, name="CanvasAIWorker", daemon=False)
        _WORKERS[key] = worker
        worker.start()
        return worker
