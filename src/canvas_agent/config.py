"""Versioned non-secret configuration; validate before replacing any file."""

import copy
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

DEFAULTS = {
    "schema_version": 1,
    "canvas_url": "",
    "timezone": "Australia/Sydney",
    "language": "en",
    "theme": "sage",
    "course_ids": None,
    "include_ended": False,
    "monitoring": False,
    "sync_interval_minutes": 0,
    "normal_times": ["10:00", "18:00"],
    "exam_times": ["10:00", "15:00", "18:00", "21:00"],
    "mode": "normal",
    "exam_start": "",
    "exam_end": "",
    "strong_enabled": True,
    "strong_hours": 48,
    "overdue_enabled": True,
    "overdue_days": 7,
    "weekly_enabled": True,
    "weekly_day": 0,
    "weekly_time": "10:00",
    "weekly_channels": ["windows"],
    "channels": ["windows"],
    "ai_enabled": False,
    "ai_consent": False,
    "ai_provider": "DeepSeek",
    "ai_url": "https://api.deepseek.com",
    "ai_model": "deepseek-chat",
    "ai_temperature": 0.2,
    "ai_max_tokens": 1200,
    "guardian_enabled": True,
    "guardian_minutes": 60,
    "guardian_repeat_minutes": 15,
    "guardian_repeat_enabled": True,
    "guardian_24h_enabled": False,
    "ai_announcement_limit": 3,
    "ai_announcements_enabled": False,
    "ai_weekly_enabled": False,
    "ai_daily_budget": 20,
}

# Explicit additions only. Unknown/misspelled production fields remain invalid.
COMPATIBLE_ADDITIONS = (
    "theme",
    "guardian_enabled",
    "guardian_minutes",
    "guardian_repeat_minutes",
    "ai_announcement_limit",
    "ai_announcements_enabled",
    "ai_weekly_enabled",
    "ai_daily_budget",
    "sync_interval_minutes",
    "guardian_repeat_enabled",
    "guardian_24h_enabled",
)


class ConfigurationError(ValueError):
    code = "configuration_invalid"

    def __init__(self, reason, *fields):
        self.reason = reason
        self.fields = tuple(
            field if field in DEFAULTS or field == "$document" else "<unknown_field>" for field in fields
        )
        super().__init__(self.code)  # never include config values or raw parse errors


def invalid(reason, *fields):
    raise ConfigurationError(reason, *fields)


def checked(field, operation, value):
    try:
        return operation(value)
    except (ValueError, TypeError, KeyError, AttributeError):
        invalid("invalid_value", field)


def data_directory():
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise RuntimeError("LOCALAPPDATA unavailable; use an explicit test data directory")
    return Path(root) / "CanvasDeadlineAgent-v1.2"


def https_url(value):
    p = urlsplit(value.strip())
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("Use an HTTPS URL without credentials, query or fragment")
    if p.port not in (None, 443):
        raise ValueError("Only HTTPS port 443 is supported")
    return value.strip().rstrip("/")


def times(values):
    if (
        not values
        or len(values) > 48
        or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", x) for x in values)
    ):
        raise ValueError("Use 1–48 daily times in HH:MM, 24-hour format")
    return sorted(set(values))


def validate(config):
    if type(config) is not dict:
        invalid("object_required", "$document")
    c = copy.deepcopy(config)
    if set(c) - set(DEFAULTS):
        invalid("unknown_fields", *sorted(set(c) - set(DEFAULTS)))
    if set(DEFAULTS) - set(c):
        invalid("missing_fields", *sorted(set(DEFAULTS) - set(c)))
    if type(c["schema_version"]) is not int or c["schema_version"] != 1:
        invalid("unsupported_schema_version", "schema_version")
    for key, default in DEFAULTS.items():
        if isinstance(default, str) and type(c[key]) is not str:
            invalid("text_required", key)
        if isinstance(default, list) and type(c[key]) is not list:
            invalid("list_required", key)
    if c["canvas_url"]:
        c["canvas_url"] = checked("canvas_url", https_url, c["canvas_url"])
    checked("timezone", ZoneInfo, c["timezone"])
    if c["language"] not in ("en", "zh") or c["mode"] not in ("normal", "exam"):
        invalid("invalid_choice", "language" if c["language"] not in ("en", "zh") else "mode")
    if c["theme"] not in ("sage", "pink"):
        invalid("invalid_choice", "theme")
    for k, v in DEFAULTS.items():
        if isinstance(v, bool) and type(c[k]) is not bool:
            invalid("boolean_required", k)
    for key, low, high in [
        ("strong_hours", 1, 8760),
        ("overdue_days", 1, 365),
        ("weekly_day", 0, 6),
        ("ai_max_tokens", 100, 4096),
        ("guardian_minutes", 16, 1440),
        ("guardian_repeat_minutes", 1, 15),
        ("ai_announcement_limit", 1, 10),
        ("ai_daily_budget", 1, 100),
    ]:
        if type(c[key]) is not int or not low <= c[key] <= high:
            invalid("integer_out_of_range", key)
    for key in ("normal_times", "exam_times"):
        c[key] = checked(key, times, c[key])
    if type(c["sync_interval_minutes"]) is not int or not (
        c["sync_interval_minutes"] == 0 or 15 <= c["sync_interval_minutes"] <= 1440
    ):
        invalid("integer_out_of_range", "sync_interval_minutes")
    checked("weekly_time", times, [c["weekly_time"]])
    if bool(c["exam_start"]) != bool(c["exam_end"]):
        invalid("paired_dates_required", "exam_start", "exam_end")
    if c["exam_start"] and checked("exam_start", date.fromisoformat, c["exam_start"]) > checked(
        "exam_end", date.fromisoformat, c["exam_end"]
    ):
        invalid("invalid_date_order", "exam_start", "exam_end")
    for key in ("channels", "weekly_channels"):
        if (
            not c[key]
            or any(type(value) is not str for value in c[key])
            or not set(c[key]) <= {"windows", "pushplus"}
        ):
            invalid("invalid_channel_selection", key)
        c[key] = sorted(set(c[key]))
    if c["course_ids"] is not None and (
        not isinstance(c["course_ids"], list) or any(type(x) is not int or x <= 0 for x in c["course_ids"])
    ):
        invalid("invalid_course_selection", "course_ids")
    c["ai_url"] = checked("ai_url", https_url, c["ai_url"])
    if c["ai_provider"] not in ("DeepSeek", "OpenAI", "Custom"):
        invalid("invalid_choice", "ai_provider")
    if not isinstance(c["ai_model"], str) or not 1 <= len(c["ai_model"]) <= 200:
        invalid("text_length_invalid", "ai_model")
    if type(c["ai_temperature"]) not in (int, float) or not 0 <= c["ai_temperature"] <= 2:
        invalid("number_out_of_range", "ai_temperature")
    if c["ai_enabled"] and not c["ai_consent"]:
        invalid("explicit_consent_required", "ai_consent")
    if c["guardian_repeat_minutes"] >= c["guardian_minutes"]:
        invalid("invalid_reminder_order", "guardian_repeat_minutes", "guardian_minutes")
    return c


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def load(path):
    if not path.exists():
        return validate(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        invalid("invalid_json", "$document")
    if type(raw) is not dict:
        invalid("object_required", "$document")
    # Only pre-release v0 configuration can be migrated automatically.
    if raw.get("schema_version", 0) == 0:
        if set(raw) - set(DEFAULTS):
            invalid("unknown_fields", *sorted(set(raw) - set(DEFAULTS)))
        raw = DEFAULTS | raw | {"schema_version": 1}
    # v1.1 reads legacy copies without modifying their files or the original installation.
    for key in COMPATIBLE_ADDITIONS:
        raw.setdefault(key, DEFAULTS[key])
    return validate(raw)


def save(path, config):
    c = validate(config)
    atomic_write(path, json.dumps(c, indent=2, ensure_ascii=False).encode("utf-8"))
    return c
