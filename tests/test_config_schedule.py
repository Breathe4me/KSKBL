import copy
import json
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree as ET

import pytest

from canvas_agent.config import DEFAULTS, load, save, times, validate
from canvas_agent.schedule import active_times, due_work, next_slot, slots, task_name, task_xml
from canvas_agent.security import AlreadyRunning, ProcessLock
from canvas_agent.storage import Store


@pytest.mark.parametrize("value", [["25:00"], ["9:00"], ["12:60"], [], ["12:00; whoami"], ["00:00"] * 49])
def test_time_validation(value):
    with pytest.raises(ValueError):
        times(value)


def test_time_sort_and_dedup():
    assert times(["18:00", "01:05", "18:00"]) == ["01:05", "18:00"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("strong_hours", 0),
        ("strong_hours", 1.5),
        ("strong_hours", True),
        ("overdue_days", 366),
        ("weekly_day", 7),
        ("ai_max_tokens", 100000),
        ("canvas_url", "http://example.com"),
        ("canvas_url", "https://user:pw@example.com"),
        ("canvas_url", "https://example.com?token=foo"),
        ("mode", "invalid"),
        ("channels", []),
        ("ai_enabled", True),
        ("course_ids", ["1"]),
        ("exam_start", "2026-10-20"),
    ],
)
def test_config_rejects_bad_values(config, key, value):
    config[key] = value
    with pytest.raises(ValueError):
        validate(config)


def test_atomic_config_and_migration(tmp_path):
    path = tmp_path / "config.json"
    assert load(path)["strong_hours"] == 48
    path.write_text(json.dumps({"strong_hours": 24}))
    assert load(path)["strong_hours"] == 24
    save(path, copy.deepcopy(DEFAULTS))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save(path, DEFAULTS | {"strong_hours": 0})
    assert path.read_bytes() == before


def test_future_config_refused(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(DEFAULTS | {"schema_version": 99}))
    with pytest.raises(ValueError):
        load(path)


def test_exam_range_and_mode(config, now):
    assert active_times(config, now.date()) == ["10:00", "18:00"]
    config.update(exam_start="2026-10-19", exam_end="2026-10-25")
    assert len(active_times(config, now.date())) == 4
    assert len(active_times(config, now.date() + timedelta(days=10))) == 2
    config["mode"] = "exam"
    assert len(active_times(config, now.date() + timedelta(days=10))) == 4


def test_missed_slots_coalesced_and_retry_throttle(config, now, tmp_path):
    store = Store(tmp_path)
    work = due_work(config, store, now + timedelta(hours=10))
    assert work["slot"] == now.replace(hour=18)
    store.set("last_slot", work["slot"].isoformat())
    store.set("weekly_done", work["week"])
    store.set("last_attempt", (now + timedelta(hours=10)).isoformat())
    assert due_work(config, store, now + timedelta(hours=10, minutes=1)) is None
    store.set("needs_retry", True)
    assert due_work(config, store, now + timedelta(hours=10, minutes=16))
    store.close()


def test_timezone(config, now):
    config["timezone"] = "Australia/Sydney"
    config["weekly_enabled"] = False
    nxt = next_slot(config, now)
    assert nxt == datetime(2026, 10, 19, 23, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "date,hour,expected",
    [
        ("2026-03-08", "02:30", "2026-03-08T07:30:00+00:00"),
        ("2026-11-01", "01:30", "2026-11-01T05:30:00+00:00"),
    ],
)
def test_dst_gap_and_fold(config, date, hour, expected):
    config.update(timezone="America/New_York", normal_times=[hour], weekly_enabled=False)
    now = datetime.fromisoformat(date).replace(tzinfo=UTC)
    result = [t for t, _ in slots(config, now) if t.date().isoformat() == date]
    assert result == [datetime.fromisoformat(expected)]


def test_lock_collision_and_recovery(tmp_path):
    with ProcessLock(tmp_path):
        with pytest.raises(AlreadyRunning):
            with ProcessLock(tmp_path):
                pass
    with ProcessLock(tmp_path):
        pass


def test_task_xml_least_privilege_and_quoted_paths(tmp_path):
    root = tmp_path / "Path With Spaces"
    xml = task_xml(root, "EXAMPLE\\student", executable="C:\\Program Files\\Canvas\\app.exe")
    tree = ET.fromstring(xml)  # noqa: S314 - XML generated locally by the function under test
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert tree.find(".//t:RunLevel", ns).text == "LeastPrivilege"
    assert tree.find(".//t:LogonType", ns).text == "InteractiveToken"
    assert tree.find(".//t:MultipleInstancesPolicy", ns).text == "Parallel"
    assert '"' in tree.find(".//t:Arguments", ns).text
    assert tree.find(".//t:Interval", ns).text == "PT1M"
    assert task_name(root) != task_name(tmp_path / "other")
