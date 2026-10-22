"""Exercise the installed upstream init callback without importing CLR or creating a GUI."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from canvas_agent.startup_diagnostics import STAGES, StartupDiagnostics
from canvas_agent.web_shell import mapping_probe_document
from canvas_agent.webview_native import APP_HOST, APP_URL, bind_webview, ordered_initial_navigation


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, callback):
        self.handlers.append(callback)
        return self

    def fire(self, *args):
        for callback in tuple(self.handlers):
            callback(*args)


def upstream_base():
    """Compile only the installed Python callback, not the Windows/.NET module."""
    path = Path(__file__).resolve().parents[1] / ".ui-deps/webview/platforms/edgechromium.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EdgeChrome")
    callback = next(
        node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "on_webview_ready"
    )
    namespace = {
        "_state": {"ssl": False, "debug": False, "user_agent": None, "private_mode": False},
        "webview_settings": {"IGNORE_SSL_ERRORS": False},
        "CoreWebView2WebResourceContext": SimpleNamespace(All="All"),
    }
    # Execute only the installed, reviewed Python callback AST, never the CLR/GUI module.
    exec(compile(ast.Module(body=[callback], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return type("UpstreamCallback", (), {"on_webview_ready": namespace["on_webview_ready"]})


@pytest.fixture
def fixture(tmp_path):
    directory = tmp_path / "runtime-page"
    directory.mkdir()
    (directory / "index.html").write_text("<p>one offline paragraph</p>", encoding="utf-8")
    diag = StartupDiagnostics(tmp_path / "data")
    core = SimpleNamespace(Settings=SimpleNamespace(), mapped=False)
    for name in (
        "SourceChanged",
        "NewWindowRequested",
        "WebResourceResponseReceived",
        "WebResourceRequested",
        "PermissionRequested",
        "DownloadStarting",
        "WebMessageReceived",
        "ProcessFailed",
    ):
        setattr(core, name, Event())
    control = SimpleNamespace(CoreWebView2=core, Source="about:blank")
    for name in ("CoreWebView2InitializationCompleted", "NavigationStarting", "NavigationCompleted"):
        setattr(control, name, Event())
    observed = []

    def mapping(host, folder, access):
        assert host == APP_HOST and Path(folder) == directory and access == "Deny"
        core.mapped = True
        observed.append("map")

    core.SetVirtualHostNameToFolderMapping = mapping
    core.AddWebResourceRequestedFilter = lambda *args: None
    window = SimpleNamespace(native=SimpleNamespace(webview=control), real_url=APP_URL)
    backend = SimpleNamespace(EdgeChrome=upstream_base())

    def load_url(browser, url):
        assert url == APP_URL
        # Model Chromium's loader snapshot at Source assignment, before NavigationStarting.
        mapped_at_source_assignment = core.mapped
        if mapped_at_source_assignment:
            assert core.Settings.AreDefaultScriptDialogsEnabled is False
        observed.append("navigate_mapped" if mapped_at_source_assignment else "navigate_unmapped")
        control.Source = url
        args = SimpleNamespace(Uri=url, Cancel=False, NavigationId=7, IsRedirected=False)
        control.NavigationStarting.fire(control, args)
        browser.result = SimpleNamespace(
            IsSuccess=mapped_at_source_assignment and not args.Cancel,
            WebErrorStatus="Unknown" if mapped_at_source_assignment else "Disconnected",
            NavigationId=7,
            HttpStatusCode=200 if mapped_at_source_assignment else 0,
        )

    backend.EdgeChrome.load_url = load_url
    for name in (
        "on_source_changed",
        "on_new_window_request",
        "on_web_resource_response",
        "on_web_resource_request",
        "on_certificate_error",
        "on_download_starting",
    ):
        setattr(backend.EdgeChrome, name, lambda *args: None)
    return directory, diag, core, control, observed, window, backend


def browser_instance(backend, control, window):
    browser = backend.EdgeChrome()
    browser.webview, browser.pywebview_window = control, window
    return browser


def test_old_upstream_callback_starts_loader_before_later_mapping(fixture):
    directory, diag, core, control, observed, window, backend = fixture
    browser = browser_instance(backend, control, window)
    # Exact previous subscription order: upstream handler first, mapping handler second.
    control.CoreWebView2InitializationCompleted += browser.on_webview_ready
    control.CoreWebView2InitializationCompleted += lambda *_: bind_webview(
        window, diag, directory, types=("Deny", "Deny", "All")
    )
    control.CoreWebView2InitializationCompleted.fire(control, SimpleNamespace(IsSuccess=True))
    assert core.mapped and observed == ["navigate_unmapped", "map"]
    assert browser.result.WebErrorStatus == "Disconnected"
    control.NavigationCompleted.fire(control, browser.result)
    assert diag.failure == "navigation_failed" and "navigation_completed" not in diag.flags


def test_adapter_maps_same_core_before_only_initial_navigation(fixture):
    directory, diag, _, control, observed, window, backend = fixture
    original = backend.EdgeChrome
    restore = ordered_initial_navigation(window, diag, directory, backend, types=("Deny", "Deny", "All"))
    browser = browser_instance(backend, control, window)
    browser.on_webview_ready(control, SimpleNamespace(IsSuccess=True))
    browser.on_webview_ready(control, SimpleNamespace(IsSuccess=True))
    assert observed == ["map", "navigate_mapped"]
    control.NavigationCompleted.fire(control, browser.result)
    assert {"core_ready", "navigation_started", "navigation_completed"} <= diag.flags
    assert diag.status == "starting"  # local navigation alone is not UI success
    for stage in STAGES - diag.flags:
        diag.signal(stage)
    assert diag.status == "ready"
    logs = [json.loads(line) for line in (diag.directory / "startup.jsonl").read_text().splitlines()]
    ids = [item["core_id"] for item in logs if "core_id" in item]
    assert len(set(ids)) == 1
    result = next(item for item in logs if item["event"] == "navigation_result")
    assert result["source"] == APP_URL and result["is_success"] and result["navigation_id"] == 7
    restore()
    assert backend.EdgeChrome is original


def test_mapping_exception_prevents_upstream_navigation(fixture):
    directory, diag, core, control, observed, window, backend = fixture
    core.SetVirtualHostNameToFolderMapping = lambda *args: (_ for _ in ()).throw(OSError("not logged"))
    restore = ordered_initial_navigation(window, diag, directory, backend, types=("Deny", "Deny", "All"))
    try:
        browser_instance(backend, control, window).on_webview_ready(control, SimpleNamespace(IsSuccess=True))
        assert observed == [] and diag.failure == "native_policy_failed"
    finally:
        restore()


def test_replaced_core_cancels_navigation_instead_of_mapping_too_late(fixture):
    directory, diag, core, control, _, window, _ = fixture
    bind_webview(window, diag, directory, types=("Deny", "Deny", "All"))
    control.CoreWebView2 = SimpleNamespace()
    args = SimpleNamespace(Uri=APP_URL, Cancel=False)
    control.NavigationStarting.fire(control, args)
    assert args.Cancel and core.mapped and diag.failure == "native_policy_failed"


def test_missing_mapped_document_prevents_navigation(fixture):
    directory, diag, _, control, observed, window, backend = fixture
    (directory / "index.html").unlink()
    restore = ordered_initial_navigation(window, diag, directory, backend, types=("Deny", "Deny", "All"))
    try:
        browser_instance(backend, control, window).on_webview_ready(control, SimpleNamespace(IsSuccess=True))
        assert observed == [] and diag.failure == "native_policy_failed"
    finally:
        restore()


def test_probe_is_one_paragraph_and_separate_from_application_acceptance(tmp_path):
    diag = StartupDiagnostics(tmp_path, mode="mapping_probe")
    document = mapping_probe_document(diag)
    assert document.count("<p>") == 1 and "app.js" not in document and "navitem" not in document
    assert "get_state" in document and "dom_ready" in document and "ui_ready" in document
    diag.signal("core_ready")
    assert json.loads((diag.directory / "startup-status.json").read_text())["mode"] == "mapping_probe"
