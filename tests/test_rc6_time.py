from datetime import UTC, datetime, timedelta

from canvas_agent.config import DEFAULTS
from canvas_agent.rules import local_time_label
from canvas_agent.schedule import due_work, next_slot, rebase_timezone
from canvas_agent.storage import Store


def test_default_sydney_and_daylight_saving_display():
    assert DEFAULTS["timezone"] == "Australia/Sydney"
    assert local_time_label("2026-10-20T07:28:00Z", "Australia/Sydney", True) == "2026-10-20 18:28:00 AEDT"
    assert local_time_label("2026-07-20T07:28:00Z", "Australia/Sydney", True) == "2026-07-20 17:28:00 AEST"
    assert local_time_label(None, "Australia/Sydney") == "—"
    assert local_time_label("—", "Australia/Sydney") == "—"


def test_timezone_rebase_does_not_replay_past_reminders_or_weekly_report(tmp_path, config):
    config["timezone"] = "Australia/Sydney"
    now = datetime(2026, 10, 20, 7, 28, tzinfo=UTC)
    store = Store(tmp_path)
    try:
        store.set("last_slot", "2026-10-19T18:00:00+00:00")
        store.set("needs_retry", True)
        store.set("retry_slot", "old-utc-slot")
        rebase_timezone(config, store, now)
        assert store.get("last_slot") == "2026-10-20T07:00:00+00:00"
        assert store.get("weekly_done") is None
        assert due_work(config, store, now + timedelta(minutes=1)) is None
        following = next_slot(config, now)
        assert following == datetime(2026, 10, 20, 23, tzinfo=UTC)
        assert local_time_label(following, config["timezone"]) == "2026-10-21 10:00 AEDT"
        assert due_work(config, store, following)["slot"] == following
    finally:
        store.close()
