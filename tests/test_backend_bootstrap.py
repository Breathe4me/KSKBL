"""Config/Bridge startup regression: existing QA data, not only fresh defaults."""

import json

import pytest

from canvas_agent.backend_check import check_backend
from canvas_agent.config import DEFAULTS, ConfigurationError, load, validate
from canvas_agent.startup_diagnostics import StartupDiagnostics
from canvas_agent.web_bridge import Bridge
from canvas_agent.web_qa import prepare_qa_root

ADDED = ("sync_interval_minutes", "guardian_repeat_enabled", "guardian_24h_enabled")


@pytest.mark.parametrize("precreate", [False, True])
def test_first_launch_and_empty_directory_initialize_real_state(tmp_path, precreate):
    root = tmp_path / "synthetic"
    if precreate:
        root.mkdir()
    assert validate(DEFAULTS) == DEFAULTS
    result = check_backend(root)
    assert result["status"] == "passed" and result["tasks"] == 5
    assert result["stages"] == ["backend_state_ready"] and result["ui_ready"] is False
    assert set(result["credentials"].values()) == {"missing"}


def test_existing_qa_config_is_backed_up_and_missing_fields_are_completed_without_rewrite(tmp_path):
    root = prepare_qa_root(tmp_path / "old-qa")
    config = DEFAULTS | {"language": "zh", "theme": "pink", "canvas_url": "https://canvas.example"}
    for key in ADDED:
        del config[key]
    path = root / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    original = path.read_bytes()
    result = check_backend(root)
    assert result["status"] == "passed" and path.read_bytes() == original
    migrated = load(path)
    assert {key: migrated[key] for key in ADDED} == {key: DEFAULTS[key] for key in ADDED}
    assert migrated["theme"] == "pink" and migrated["language"] == "zh"
    assert any(file.read_bytes() == original for file in (root / "config-backups").iterdir())
    assert check_backend(root)["status"] == "passed"


@pytest.mark.parametrize(
    "key,value,reason",
    [
        ("monitoring", "false", "boolean_required"),
        ("guardian_minutes", True, "integer_out_of_range"),
        ("sync_interval_minutes", 1, "integer_out_of_range"),
        ("normal_times", "10:00", "list_required"),
        ("ai_url", "http://SYNTHETIC-SECRET", "invalid_value"),
        ("schema_version", 9, "unsupported_schema_version"),
    ],
)
def test_invalid_config_is_recoverable_without_reset_or_sensitive_values(tmp_path, key, value, reason):
    root = prepare_qa_root(tmp_path / "invalid-qa")
    path = root / "config.json"
    valid = path.read_bytes()
    data = json.loads(valid)
    data[key] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    invalid_bytes = path.read_bytes()
    result = check_backend(root)
    assert result["status"] == "failed" and result["code"] == "configuration_invalid"
    assert result["reason"] == reason and result["fields"] == [key]
    assert path.read_bytes() == invalid_bytes and result["stages"] == []
    logs = open_log(result)
    assert "SYNTHETIC-SECRET" not in logs
    assert '"configuration_error"' in logs and '"stage": "bridge_invoke"' in logs
    assert any(file.read_bytes() == invalid_bytes for file in (root / "config-backups").iterdir())
    path.write_bytes(valid)  # explicit repair of this test-only fixture, no product auto-reset
    assert check_backend(root)["status"] == "passed"


def open_log(result):
    from pathlib import Path

    return (Path(result["diagnostics"]) / "startup.jsonl").read_text(encoding="utf-8")


def test_malformed_json_and_unknown_fields_remain_invalid_and_preserved(tmp_path):
    root = prepare_qa_root(tmp_path / "qa")
    path = root / "config.json"
    path.write_text('{"SENSITIVE-KEY":', encoding="utf-8")
    assert check_backend(root)["reason"] == "invalid_json"
    assert path.read_text() == '{"SENSITIVE-KEY":'
    path.write_text(json.dumps(DEFAULTS | {"SENSITIVE-KEY": "SENSITIVE-VALUE"}))
    result = check_backend(root)
    assert result["reason"] == "unknown_fields" and result["fields"] == ["<unknown_field>"]
    assert "SENSITIVE" not in open_log(result) and "SENSITIVE" not in json.dumps(result)


def test_state_ready_is_after_full_state_and_scrub_success_only(tmp_path, monkeypatch):
    root = prepare_qa_root(tmp_path / "qa")
    bridge = Bridge(root, qa=True)
    diagnostics = StartupDiagnostics(root)
    bridge._diagnostics = diagnostics
    monkeypatch.setattr(bridge, "_scrub", lambda _: (_ for _ in ()).throw(RuntimeError("not logged")))
    assert bridge.invoke("get_state", {})["ok"] is False
    assert "backend_state_ready" not in diagnostics.flags and "ui_ready" not in diagnostics.flags


def test_missing_noncompatible_field_and_bad_default_are_not_silently_accepted(tmp_path, monkeypatch):
    raw = DEFAULTS.copy()
    del raw["normal_times"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigurationError) as error:
        load(path)
    assert error.value.reason == "missing_fields" and "normal_times" in error.value.fields
    monkeypatch.setitem(DEFAULTS, "guardian_minutes", False)
    with pytest.raises(ConfigurationError):
        load(tmp_path / "absent.json")
