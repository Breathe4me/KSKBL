"""P0 regression: no native GUI imports; fake WebView2 events and temporary resources only."""

import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from canvas_agent import web_shell
from canvas_agent.startup_diagnostics import STAGES, SafeWebviewHandler, StartupDiagnostics
from canvas_agent.webview_native import APP_HOST, APP_URL, bind_webview, route_startup_message


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, function):
        self.handlers.append(function)
        return self

    def fire(self, *args):
        return [callback(*args) for callback in self.handlers]


def test_window_loaded_or_bridge_alone_is_never_startup_success(tmp_path):
    diag = StartupDiagnostics(tmp_path)
    diag.event("pywebview_loaded")
    diag.signal("bridge_ready")
    assert diag.status == "starting"
    diag.deadline(0)
    assert diag.status == "failed" and diag.failure == "startup_timeout"
    for stage in STAGES:
        diag.signal(stage)
    assert diag.status == "failed"  # late signals cannot turn a failed startup into success


def test_all_native_and_real_page_signals_are_required_even_out_of_order(tmp_path):
    diag = StartupDiagnostics(tmp_path)
    observed = []
    diag.on_ready = lambda: observed.append("ready")
    for stage in sorted(STAGES - {"backend_state_ready"}):
        diag.signal(stage)
    assert diag.status == "starting"
    diag.signal("backend_state_ready")
    diag.signal("ui_ready")
    assert diag.status == "ready" and observed == ["ready"]


def test_diagnostic_messages_exceptions_and_library_logs_exclude_secrets(tmp_path):
    diag = StartupDiagnostics(tmp_path)
    secret = "SYNTHETIC-SECRET-MUST-NEVER-ENTER-LOGS"
    try:
        raise RuntimeError(secret)
    except RuntimeError as error:
        diag.exception("fixture", error)
    handler = SafeWebviewHandler(diag)
    handler.emit(logging.LogRecord("pywebview", logging.ERROR, __file__, 1, secret, (), None))
    assert not diag.receive({"channel": "cda-startup-v1", "run_id": "stale", "event": "ui_ready"})
    assert diag.receive(
        {
            "channel": "cda-startup-v1",
            "run_id": diag.run_id,
            "event": "javascript_error",
            "message": secret,
            "line": 12,
        }
    )
    text = (diag.directory / "startup.jsonl").read_text(encoding="utf-8")
    assert secret not in text and "RuntimeError" in text and '"line": 12' in text


def test_frozen_resources_resolve_from_meipass_not_current_directory(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    source = Path(__file__).resolve().parents[1] / "frontend"
    shutil.copytree(source, bundle / "frontend")
    pins = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}
    (bundle / "frontend-sha256.json").write_text(json.dumps(pins), encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    document = web_shell.html_document()
    assert "CDAStartup" in document and "__STARTUP_CONFIG__" not in document
    assert 'id="startup-status"' in document
    (bundle / "frontend/app.js").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash_mismatch"):
        web_shell.html_document()


def test_runtime_binding_uses_existing_matching_version_only(tmp_path):
    directory = tmp_path / "Microsoft/EdgeWebView/Application/155.0.4283.62"
    directory.mkdir(parents=True)
    (directory / "msedgewebview2.exe").write_bytes(b"synthetic fixture; never executed")
    assert (
        web_shell.runtime_directory({"version": "155.0.4283.62"}, {"ProgramFiles(x86)": str(tmp_path)})
        == directory
    )
    assert web_shell.runtime_directory({"version": "154.0.0.0"}, {"ProgramFiles(x86)": str(tmp_path)}) is None


@pytest.fixture
def native(tmp_path):
    diag = StartupDiagnostics(tmp_path)
    (tmp_path / "index.html").write_text("<p>offline</p>", encoding="utf-8")
    core = SimpleNamespace(Settings=SimpleNamespace(), Source=APP_URL)
    for name in (
        "WebResourceRequested",
        "PermissionRequested",
        "DownloadStarting",
        "WebMessageReceived",
        "ProcessFailed",
    ):
        setattr(core, name, Event())
    core.mapping = []
    core.SetVirtualHostNameToFolderMapping = lambda *args: core.mapping.append(args)
    core.AddWebResourceRequestedFilter = lambda *args: None
    core.Environment = SimpleNamespace(CreateWebResourceResponse=lambda *args: "blocked")
    control = SimpleNamespace(
        CoreWebView2=None,
        Source=APP_URL,
        CoreWebView2InitializationCompleted=Event(),
        NavigationStarting=Event(),
        NavigationCompleted=Event(),
    )
    window = SimpleNamespace(native=SimpleNamespace(webview=control))
    bind_webview(window, diag, tmp_path, types=("Deny", "Deny", "All"))
    control.CoreWebView2 = core
    return diag, core, control


def test_virtual_host_mapping_precedes_allowed_navigation_and_ui_ready(native):
    diag, core, control = native
    control.CoreWebView2InitializationCompleted.fire(control, SimpleNamespace(IsSuccess=True))
    assert core.mapping[0][0] == APP_HOST
    args = SimpleNamespace(Uri=APP_URL, Cancel=False)
    control.NavigationStarting.fire(control, args)
    assert not args.Cancel
    control.NavigationCompleted.fire(control, SimpleNamespace(IsSuccess=True))
    for stage in ("dom_ready", "bridge_ready", "ui_ready"):
        route_startup_message(
            SimpleNamespace(
                Source=APP_URL,
                get_WebMessageAsJson=lambda stage=stage: json.dumps(
                    {"channel": "cda-startup-v1", "run_id": diag.run_id, "event": stage}
                ),
            ),
            diag,
        )
    assert diag.status == "starting"
    diag.signal("backend_state_ready")
    assert diag.status == "ready"


@pytest.mark.parametrize("uri", ["https://example.invalid/", "file:///C:/unrelated.html", "about:blank"])
def test_non_application_navigation_is_cancelled(native, uri):
    diag, _, control = native
    args = SimpleNamespace(Uri=uri, Cancel=False)
    control.NavigationStarting.fire(control, args)
    assert args.Cancel and diag.failure == "navigation_blocked"


def test_native_initialization_failure_is_persistent_and_not_silenced(native):
    diag, _, control = native
    seen = []
    diag.on_failure = seen.append
    control.CoreWebView2InitializationCompleted.fire(
        control, SimpleNamespace(IsSuccess=False, InitializationException=RuntimeError("secret omitted"))
    )
    assert seen == ["native_initialization_failed"]
    assert json.loads((diag.directory / "startup-status.json").read_text())["status"] == "failed"


def test_actual_mshtml_renderer_is_rejected_without_creating_a_gui(tmp_path, monkeypatch):
    diag = StartupDiagnostics(tmp_path)
    events = SimpleNamespace(
        **{key: Event() for key in ("initialized", "before_show", "shown", "closed", "loaded")}
    )
    window = SimpleNamespace(events=events)
    fake = SimpleNamespace(
        settings={},
        create_window=lambda *args, **kwargs: window,
        start=lambda **kwargs: events.initialized.fire("mshtml"),
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(web_shell, "webview_runtime", lambda: {"available": True, "version": "155.0.4283.62"})
    monkeypatch.setattr(web_shell, "runtime_directory", lambda *args: None)
    failures = []
    monkeypatch.setattr(web_shell, "native_error_panel", lambda window, diag, code: failures.append(code))
    with pytest.raises(RuntimeError, match="GUI Startup Failure"):
        web_shell.launch(tmp_path, qa=True, diagnostics=diag)
    assert failures == ["renderer_mismatch"]
