"""Correlated operation tracing is independent of the business lock and cannot log raw secrets."""

import json
from types import SimpleNamespace

from canvas_agent.operation_diagnostics import OperationLog, build_identity
from canvas_agent.startup_diagnostics import StartupDiagnostics
from canvas_agent.web_bridge import Bridge
from canvas_agent.web_qa import prepare_qa_root
from canvas_agent.webview_native import APP_URL, route_startup_message


def rows(diag):
    file = diag.directory / "operations.jsonl"
    return (
        [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()] if file.exists() else []
    )


def test_shared_request_id_has_actual_entry_commit_reply_and_release(tmp_path):
    root = prepare_qa_root(tmp_path / "qa")
    diag = StartupDiagnostics(root, operations_enabled=True)
    bridge = Bridge(root, qa=True)
    bridge._diagnostics = diag
    state = bridge.invoke("get_state", {})["data"]
    params = {
        "key": state["tasks"][0]["key"],
        "account_scope": state["account_scope"],
        "state": "ignored",
        "note": "SYNTHETIC_SECRET",
    }
    rid = "1" * 32
    result = bridge.invoke("set_tracking", params, {"request_id": rid})
    assert result["ok"]
    records = [row for row in rows(diag) if row["request_id"] == rid]
    assert [row["stage"] for row in records] == [
        "python_rpc_enter",
        "bridge_lock_acquired",
        "mutation_enter",
        "profile_lock_acquired",
        "sqlite_write_enter",
        "sqlite_commit",
        "bridge_lock_released",
        "python_rpc_exit",
    ]
    assert "SYNTHETIC_SECRET" not in json.dumps(rows(diag))


def test_frontend_rejection_written_while_business_mutex_held(tmp_path):
    root = prepare_qa_root(tmp_path / "qa")
    diag = StartupDiagnostics(root, operations_enabled=True)
    bridge = Bridge(root, qa=True)
    bridge._diagnostics = diag
    packet = {
        "channel": "cda-operation-v1",
        "run_id": diag.run_id,
        "request_id": "2" * 32,
        "stage": "frontend_guard_rejected",
        "busy": True,
        "operation": "set_tracking",
        "reason": "frontend_busy",
    }
    bridge._mutex.acquire()
    try:
        args = SimpleNamespace(Source=APP_URL, get_WebMessageAsJson=lambda: json.dumps(packet))
        assert route_startup_message(args, diag)
        assert rows(diag)[0]["stage"] == "frontend_guard_rejected"
    finally:
        bridge._mutex.release()


def test_invalid_trace_metadata_fails_without_writing_or_logging_values(tmp_path):
    root = prepare_qa_root(tmp_path / "qa")
    diag = StartupDiagnostics(root, operations_enabled=True)
    bridge = Bridge(root, qa=True)
    bridge._diagnostics = diag
    for trace in ({"request_id": "SENSITIVE"}, {"request_id": "3" * 32, "token": "SECRET"}, []):
        assert bridge.invoke("get_state", {}, trace) == {"ok": False, "error": "invalid_request"}
    assert "SECRET" not in json.dumps(rows(diag)) and "SENSITIVE" not in json.dumps(rows(diag))
    assert not any(row["stage"] == "bridge_lock_acquired" for row in rows(diag))


def test_trace_channel_rejects_fake_python_stages_stale_source_and_secret_fields(tmp_path):
    diag = StartupDiagnostics(tmp_path, operations_enabled=True)
    packet = {
        "channel": "cda-operation-v1",
        "run_id": diag.run_id,
        "request_id": "4" * 32,
        "stage": "click_received",
        "operation": "SYNTHETIC_SECRET",
        "token": "SECRET",
        "reason": "SECRET",
        "origin": "python",
    }
    assert diag.operations.receive(packet)
    assert rows(diag)[0]["origin"] == "frontend" and "SECRET" not in json.dumps(rows(diag))
    for data in (packet | {"stage": "sqlite_commit"}, packet | {"run_id": "stale"}, packet | {"stage": []}):
        assert not diag.operations.receive(data)
    args = SimpleNamespace(Source="https://other.invalid/", get_WebMessageAsJson=lambda: json.dumps(packet))
    assert route_startup_message(args, diag) and len(rows(diag)) == 1


def test_trace_is_bounded_optional_and_does_not_affect_ready(tmp_path):
    diag = StartupDiagnostics(tmp_path, operations_enabled=True)
    diag.operations._count = 6000
    assert not diag.operations.record("click_received", "5" * 32, "frontend")
    assert not rows(diag) and not diag.flags
    disabled = OperationLog(tmp_path, "run", False)
    assert not disabled.record("python_rpc_enter", "5" * 32)


def test_diagnostic_io_failure_does_not_change_saved_result(tmp_path, monkeypatch):
    root = prepare_qa_root(tmp_path / "qa")
    diag = StartupDiagnostics(root, operations_enabled=True)
    bridge = Bridge(root, qa=True)
    bridge._diagnostics = diag
    diag.operations.directory = tmp_path / "does-not-exist"
    result = bridge.invoke("get_state", {}, {"request_id": "6" * 32})
    assert result["ok"] and diag.operations.write_failed


def test_identity_attests_exact_frontend_and_frozen_executable(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    for name in ("index.html", "prototype.css", "app.css", "app.js", "startup.js"):
        (frontend / name).write_text(name)
    exe = tmp_path / "test.exe"
    exe.write_bytes(b"nonexecutable identity fixture")
    one = build_identity(tmp_path, exe, True)
    exe.write_bytes(b"different fixture")
    two = build_identity(tmp_path, exe, True)
    assert one["executable_sha256"] != two["executable_sha256"]
    assert one["frontend_set_sha256"] == two["frontend_set_sha256"]
    assert "executable_sha256" not in build_identity(tmp_path, exe, False)


def test_new_operation_packets_do_not_reach_installed_pywebview_decoder(tmp_path):
    from test_message_protocol import installed_decoder, message

    from canvas_agent.webview_native import ordered_initial_navigation

    errors, calls = [], []
    backend = SimpleNamespace(EdgeChrome=installed_decoder(errors, calls))
    diag, window = StartupDiagnostics(tmp_path, operations_enabled=True), SimpleNamespace()
    ordered_initial_navigation(window, diag, tmp_path, backend=backend)
    decoder = backend.EdgeChrome()
    decoder.pywebview_window = window
    decoder.on_script_notify(
        None,
        message(
            {
                "channel": "cda-operation-v1",
                "run_id": diag.run_id,
                "request_id": "7" * 32,
                "stage": "click_received",
                "operation": "set_tracking",
            }
        ),
    )
    assert not errors and not calls and rows(diag)[0]["stage"] == "click_received"
