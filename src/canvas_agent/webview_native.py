"""WebView2 event wiring. Imported without loading CLR; fake event sources support headless tests."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

APP_HOST = "cda-ui.invalid"
APP_URL = "https://cda-ui.invalid/index.html"


def same_native_instance(left, right):
    if left is right:
        return True
    if not hasattr(left, "GetType") or not hasattr(right, "GetType"):
        return False  # pure Python test doubles; do not initialize CLR in headless tests
    from System import Object

    return bool(Object.ReferenceEquals(left, right))


def core_identity(core):
    return int(core.GetHashCode()) if hasattr(core, "GetHashCode") else id(core)


def safe_source(source):
    value = str(source)
    return value if value in (APP_URL, "about:blank", "") else "<non-application>"


def route_startup_message(args, diagnostics):
    """Consume our named protocol BEFORE pywebview's [func, JSON args, id] decoder.

    Other messages, including pywebview calls and FilesDropped, remain untouched.
    This is called by the sole control-level handler, not a second Core event listener.
    """
    raw = str(args.get_WebMessageAsJson())
    if not raw.lstrip().startswith("{"):
        return False
    try:
        packet = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if type(packet) is not dict or packet.get("channel") not in {"cda-startup-v1", "cda-operation-v1"}:
        return False
    if packet.get("channel") == "cda-operation-v1":
        if str(args.Source) == APP_URL:
            diagnostics.operations.receive(packet)
        return True  # isolated before pywebview decoder, even if invalid/stale/untrusted
    if str(args.Source) == APP_URL:
        accepted = diagnostics.receive(packet)
        diagnostics.event("startup_message_routed", accepted=accepted, protocol="diagnostic_v1")
    else:
        diagnostics.event("startup_message_rejected", reason="source_mismatch")
    return True


def ordered_initial_navigation(window, diagnostics, page_directory, backend=None, types=None):
    """Scope a lifecycle adapter to this window; never modify installed pywebview files.

    pywebview 6.2.1's original callback sets Source, starting navigation immediately.
    Configure the very same control before delegating to that callback, rather than
    subscribing a second, later InitializationCompleted handler or mapping during navigation.
    """
    if backend is None:
        from webview.platforms import edgechromium as backend
    original = backend.EdgeChrome

    class OrderedEdgeChrome(original):
        def on_script_notify(self, sender, args):
            if self.pywebview_window is window and route_startup_message(args, diagnostics):
                return
            return super().on_script_notify(sender, args)

        def load_url(self, url):
            if self.pywebview_window is window:
                core = self.webview.CoreWebView2
                if not hasattr(self, "_cda_handlers") or not same_native_instance(self._cda_core, core):
                    raise RuntimeError("navigation_before_mapping")
                # The upstream init callback sets this to True after our mapping hook.
                # Reapply the existing denial before its load_url assigns Source.
                core.Settings.AreDefaultScriptDialogsEnabled = False
                diagnostics.event(
                    "navigation_source_assignment", source=safe_source(url), core_id=core_identity(core)
                )
            return super().load_url(url)

        def on_webview_ready(self, sender, args):
            if self.pywebview_window is not window:
                return super().on_webview_ready(sender, args)
            try:
                diagnostics.event("native_initialization_completed", is_success=bool(args.IsSuccess))
                if not args.IsSuccess:
                    if args.InitializationException is not None:
                        diagnostics.exception("webview2_initialization", args.InitializationException)
                    diagnostics.fail("native_initialization_failed")
                    return
                if not same_native_instance(self.webview, sender):
                    raise RuntimeError("initialization_control_mismatch")
                if hasattr(self, "_cda_handlers"):
                    if not same_native_instance(self._cda_core, sender.CoreWebView2):
                        raise RuntimeError("initialized_core_instance_changed")
                    diagnostics.event("duplicate_initialization_ignored")
                    return
                self._cda_handlers = bind_webview(
                    window, diagnostics, page_directory, types=types, native=sender
                )
                self._cda_core = sender.CoreWebView2
                if diagnostics.status == "failed":
                    return
                diagnostics.event("initial_navigation_released", core_id=core_identity(sender.CoreWebView2))
                # Only pywebview performs the navigation. No manual Navigate/Source, no sleep/retry.
                return super().on_webview_ready(sender, args)
            except Exception as error:
                diagnostics.exception("ordered_initial_navigation", error)
                diagnostics.fail("native_policy_failed")

    backend.EdgeChrome = OrderedEdgeChrome
    diagnostics.event("initial_navigation_adapter_installed", strategy="map_before_pywebview_callback")

    def restore():
        if backend.EdgeChrome is OrderedEdgeChrome:
            backend.EdgeChrome = original

    return restore


def enum_name(value):
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", text) else "unknown"


def native_error_panel(window, diagnostics, code):
    # This is an application failure view, never invoked by code-only tests.
    from System import Action
    from System.Drawing import Color
    from System.Windows.Forms import DockStyle, MessageBox, Panel, TextBox

    if window.native is None:
        MessageBox.Show(
            "P0 GUI Startup Failure\nCode: " + code + "\nDiagnostics: " + str(diagnostics.directory),
            "Canvas Deadline Agent · Startup Diagnostic",
        )
        diagnostics.event("native_error_dialog_visible", code=code)
        return

    def display():
        form = window.native
        panel = Panel()
        panel.Dock = DockStyle.Fill
        panel.BackColor = Color.WhiteSmoke
        text = TextBox()
        text.Multiline = True
        text.ReadOnly = True
        text.Dock = DockStyle.Fill
        text.Text = (
            "P0 GUI Startup Failure\r\n\r\nCode: "
            + code
            + "\r\n\r\nUI initialization failed. Diagnostics:\r\n"
            + str(diagnostics.directory)
            + "\r\n\r\nKeep the logs and close this window. Do not send credentials."
        )
        panel.Controls.Add(text)
        form.Controls.Add(panel)
        panel.BringToFront()
        diagnostics.event("native_error_panel_visible", code=code)

    try:
        window.native.BeginInvoke(Action(display))
    except Exception as error:
        diagnostics.exception("native_error_panel", error)


def bind_webview(window, diagnostics, page_directory, types=None, native=None):
    native = window.native.webview if native is None else native
    page_directory = Path(page_directory).resolve(strict=True)
    document = page_directory / "index.html"
    target = urlsplit(APP_URL)
    if target.hostname != APP_HOST or target.path != "/index.html" or not document.is_file():
        raise ValueError("invalid_mapping_target")
    if len(str(page_directory)) >= 260:
        raise ValueError("mapping_directory_exceeds_max_path")
    diagnostics.event(
        "mapping_target_verified",
        host=APP_HOST,
        url=APP_URL,
        folder=str(page_directory),
        document=str(document),
        bytes=document.stat().st_size,
    )
    handlers = []
    installed = False
    mapped_core = None
    if types is None:
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2HostResourceAccessKind,
            CoreWebView2PermissionState,
            CoreWebView2WebResourceContext,
        )

        types = (
            CoreWebView2HostResourceAccessKind.Deny,
            CoreWebView2PermissionState.Deny,
            CoreWebView2WebResourceContext.All,
        )

    def safe(callback):
        def wrapped(*args):
            try:
                return callback(*args)
            except Exception as error:
                diagnostics.exception(callback.__name__, error)
                diagnostics.fail("native_policy_failed")

        handlers.append(wrapped)
        return wrapped

    @safe
    def resource(_sender, request):
        uri = str(request.Request.Uri)
        if uri != APP_URL and not uri.startswith("data:"):
            request.Response = native.CoreWebView2.Environment.CreateWebResourceResponse(
                None, 403, "Blocked", "Content-Type: text/plain"
            )
            diagnostics.event("resource_blocked", resource="non_application_resource")

    @safe
    def permission(_sender, request):
        request.State = types[1]

    @safe
    def download(_sender, request):
        request.Cancel = True

    @safe
    def process_failed(_sender, args):
        diagnostics.event("webview_process_failed", kind=enum_name(args.ProcessFailedKind))
        diagnostics.fail("process_failed")

    def install(core):
        nonlocal installed, mapped_core
        if installed:
            if not same_native_instance(mapped_core, core):
                raise RuntimeError("mapped_core_instance_changed")
            return
        # Mapping exists before any allowed main document request. No HTTP server or network.
        core.SetVirtualHostNameToFolderMapping(APP_HOST, str(page_directory), types[0])
        core.Settings.IsPasswordAutosaveEnabled = False
        core.Settings.IsGeneralAutofillEnabled = False
        core.Settings.AreDefaultScriptDialogsEnabled = False
        core.AddWebResourceRequestedFilter("*", types[2])
        core.WebResourceRequested += resource
        core.PermissionRequested += permission
        core.DownloadStarting += download
        core.ProcessFailed += process_failed
        installed = True
        mapped_core = core
        diagnostics.event(
            "virtual_host_mapping_installed",
            origin=APP_URL,
            folder=str(page_directory),
            core_id=core_identity(core),
        )
        diagnostics.signal("core_ready")

    @safe
    def initialized(sender, args):
        if not args.IsSuccess:
            error = args.InitializationException
            if error is not None:
                diagnostics.exception("webview2_initialization", error)
            diagnostics.fail("native_initialization_failed")
            return
        install(sender.CoreWebView2)

    @safe
    def starting(sender, args):
        args.Cancel = True
        current_core = sender.CoreWebView2
        diagnostics.event(
            "navigation_starting",
            uri=safe_source(args.Uri),
            core_id=core_identity(current_core),
            navigation_id=int(getattr(args, "NavigationId", 0)),
            redirected=bool(getattr(args, "IsRedirected", False)),
        )
        if str(args.Uri) != APP_URL:
            args.Cancel = True
            diagnostics.event("navigation_blocked", target="non_application_document")
            diagnostics.fail("navigation_blocked")
            return
        # Mapping here is too late: Chromium may already have made the resource loader.
        if not installed or not same_native_instance(current_core, mapped_core):
            args.Cancel = True
            diagnostics.fail("native_policy_failed")
            return
        diagnostics.signal("navigation_started")
        args.Cancel = False

    @safe
    def completed(sender, args):
        diagnostics.event(
            "navigation_result",
            is_success=bool(args.IsSuccess),
            web_error_status=enum_name(getattr(args, "WebErrorStatus", "Unknown")),
            source=safe_source(sender.Source),
            core_id=core_identity(sender.CoreWebView2),
            navigation_id=int(getattr(args, "NavigationId", 0)),
            http_status=int(getattr(args, "HttpStatusCode", 0)),
        )
        if str(sender.Source) != APP_URL:
            return
        if not same_native_instance(sender.CoreWebView2, mapped_core):
            diagnostics.fail("native_policy_failed")
            return
        if args.IsSuccess:
            diagnostics.signal("navigation_completed")
        else:
            diagnostics.event("navigation_error", status=enum_name(args.WebErrorStatus))
            diagnostics.fail("navigation_failed")

    native.CoreWebView2InitializationCompleted += initialized
    native.NavigationStarting += starting
    native.NavigationCompleted += completed
    if native.CoreWebView2 is not None:
        install(native.CoreWebView2)
    diagnostics.event("native_handlers_attached")
    return handlers
