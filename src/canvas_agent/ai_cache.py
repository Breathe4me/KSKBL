"""Durable failure reservations and budgets, independent of the monitoring lock."""

from datetime import UTC, datetime

from .security import AlreadyRunning, ProcessLock


def cached_request(store, pointer, digest, config, operation, force=False, now=None):
    now = now or datetime.now(UTC)
    account = store.get("account")
    key = pointer + ":" + digest
    try:
        # Shared by automatic and manual summaries, never the core monitor lock.
        with ProcessLock(store.root / ".ai-request"):
            reserved = store.reserve_ai(key, digest, config["ai_daily_budget"], now, force)
            if reserved is not None:
                return reserved
            try:
                result = operation()
            except Exception:
                result = {"status": "failed_fallback", "reason": "provider_failed"}
            result = result | {"digest": digest, "cached": False, "request_made": True}
            return store.finish_ai(key, pointer, result, account)
    except AlreadyRunning:
        return {"status": "busy", "reason": "another_ai_request"}
