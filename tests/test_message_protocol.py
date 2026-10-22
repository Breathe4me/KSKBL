"""Execute the installed pywebview decoder; no CLR or GUI imports."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from canvas_agent.startup_diagnostics import StartupDiagnostics
from canvas_agent.webview_native import APP_URL, ordered_initial_navigation


def installed_decoder(logs, business):
    path = Path(__file__).resolve().parents[1] / ".ui-deps/webview/platforms/edgechromium.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EdgeChrome")
    function = next(
        node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "on_script_notify"
    )
    import sys

    namespace = {
        "json": json,
        "logger": SimpleNamespace(exception=lambda *_: logs.append(type(sys.exception()).__name__)),
        "js_bridge_call": lambda window, name, params, uid: business.append((name, params, uid)),
        "_dnd_state": {"num_listeners": 0},
    }
    # Only the reviewed local callback AST is executed; importing the whole module would load CLR.
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return type("InstalledDecoder", (), {"on_script_notify": namespace["on_script_notify"]})


def message(packet, source=APP_URL):
    return SimpleNamespace(Source=source, get_WebMessageAsJson=lambda: json.dumps(packet))


def test_old_diagnostic_object_independently_reproduces_jsondecodeerror():
    logs, business = [], []
    decoder = installed_decoder(logs, business)()
    decoder.pywebview_window = object()
    decoder.on_script_notify(
        None, message({"channel": "cda-startup-v1", "run_id": "run", "event": "dom_ready"})
    )
    assert logs == ["JSONDecodeError"] and business == []
    # No config load/get_state was involved, proving this is a separate error path.


def test_router_isolates_diagnostics_and_preserves_real_pywebview_messages(tmp_path):
    logs, business = [], []
    backend = SimpleNamespace(EdgeChrome=installed_decoder(logs, business))
    window = SimpleNamespace()
    diag = StartupDiagnostics(tmp_path)
    original = backend.EdgeChrome
    restore = ordered_initial_navigation(window, diag, tmp_path, backend=backend)
    decoder = backend.EdgeChrome()
    decoder.pywebview_window = window
    for event in ("dom_ready", "bridge_ready", "ui_ready"):
        decoder.on_script_notify(
            None, message({"channel": "cda-startup-v1", "run_id": diag.run_id, "event": event})
        )
    packet = ["invoke", json.dumps(["get_state", {}]), "request-1"]
    decoder.on_script_notify(None, message(packet))
    decoder.on_script_notify(None, message("FilesDropped"))
    assert business == [("invoke", ["get_state", {}], "request-1")] and logs == []
    assert {"dom_ready", "bridge_ready", "ui_ready"} <= diag.flags
    assert "backend_state_ready" not in diag.flags and diag.status != "ready"
    restore()
    assert backend.EdgeChrome is original


def test_untrusted_source_and_stale_run_cannot_publish_readiness(tmp_path):
    logs, business = [], []
    backend = SimpleNamespace(EdgeChrome=installed_decoder(logs, business))
    window, diag = SimpleNamespace(), StartupDiagnostics(tmp_path)
    restore = ordered_initial_navigation(window, diag, tmp_path, backend=backend)
    decoder = backend.EdgeChrome()
    decoder.pywebview_window = window
    packet = {"channel": "cda-startup-v1", "run_id": diag.run_id, "event": "ui_ready"}
    decoder.on_script_notify(None, message(packet, "https://untrusted.invalid/"))
    decoder.on_script_notify(None, message(packet | {"run_id": "stale"}))
    assert not diag.flags and not business and not logs
    restore()
