"""Offline WebView2 shell with local virtual-host mapping and event-based startup diagnostics."""

import json
import logging
import os
import re
import secrets
import sys
import threading
from pathlib import Path

from .operation_diagnostics import build_identity
from .startup_diagnostics import SafeWebviewHandler, StartupDiagnostics, checked_resources, error_document
from .web_bridge import Bridge
from .webview_native import APP_URL, native_error_panel, ordered_initial_navigation


def runtime_details(versions):
    valid = [v for v in versions if isinstance(v, str) and re.fullmatch(r"\d+(?:\.\d+){1,3}", v)]
    if not valid:
        return {"available": False, "reason": "webview2_runtime_missing"}
    version = max(valid, key=lambda v: tuple(map(int, v.split("."))))
    return {"available": int(version.split(".")[0]) >= 120, "version": version, "minimum_major": 120}


def webview_runtime():
    if os.name != "nt":
        return {"available": False, "reason": "windows_required"}
    import winreg

    versions = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(
                    hive, r"SOFTWARE\Microsoft\EdgeUpdate\Clients", 0, winreg.KEY_READ | view
                ) as clients:
                    for index in range(winreg.QueryInfoKey(clients)[0]):
                        with winreg.OpenKey(clients, winreg.EnumKey(clients, index)) as key:
                            try:
                                name = winreg.QueryValueEx(key, "name")[0]
                                version = winreg.QueryValueEx(key, "pv")[0]
                            except OSError:
                                continue
                            if isinstance(name, str) and "webview2" in name.lower():
                                versions.append(version)
            except OSError:
                continue
    return runtime_details(versions)


def runtime_directory(runtime, environment=None):
    env = os.environ if environment is None else environment
    version = runtime.get("version", "")
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
        return None
    for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        if not env.get(key):
            continue
        directory = Path(env[key]) / "Microsoft/EdgeWebView/Application" / version
        if (directory / "msedgewebview2.exe").is_file():
            return directory.resolve()
    return None


def resource_base():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def html_document(diagnostics=None):
    base = resource_base()
    if getattr(sys, "frozen", False) and not (base / "frontend-sha256.json").is_file():
        raise ValueError("missing_frontend_integrity_manifest")
    directory = checked_resources(base, diagnostics)
    template = (directory / "index.html").read_text(encoding="utf-8")
    css = (
        (directory / "prototype.css").read_text(encoding="utf-8")
        + "\n"
        + (directory / "app.css").read_text(encoding="utf-8")
    )
    script = (directory / "app.js").read_text(encoding="utf-8")
    bootstrap = (directory / "startup.js").read_text(encoding="utf-8")
    config = {
        "run_id": diagnostics.run_id if diagnostics else "headless-development",
        "diagnostics": str(diagnostics.directory)
        if diagnostics
        else "Headless / browser preview; no native QA log",
        "deadline_ms": 20000,
        "operations_enabled": diagnostics.operations.enabled if diagnostics else True,
        "identity": build_identity(base, sys.executable, bool(getattr(sys, "frozen", False))),
    }
    if diagnostics:
        identity = config["identity"]
        (diagnostics.directory / "build-identity.json").write_text(
            json.dumps(identity, indent=2), encoding="utf-8"
        )
        diagnostics.event("build_identity", **identity)
    bootstrap = bootstrap.replace(
        "__STARTUP_CONFIG__", json.dumps(config, ensure_ascii=False).replace("<", "\\u003c")
    )
    if any("</script" in code.lower() for code in (script, bootstrap)) or "</style" in css.lower():
        raise ValueError("invalid_bundled_frontend")
    template = template.replace("script-src 'nonce-__NONCE__'", "script-src 'nonce-__NONCE__' 'unsafe-eval'")
    template = template.replace(
        "</head>",
        '<link rel="icon" href="data:,"><script nonce="__NONCE__">' + bootstrap + "</script></head>",
    )
    overlay = (
        '<section id="startup-status" role="alert" style="position:fixed;inset:0;z-index:100;background:#f6f7f4;padding:48px;font:16px/1.7 Segoe UI,Microsoft YaHei UI,sans-serif">'
        "<h1 data-startup-title>正在加载界面 / Initializing UI</h1><p data-startup-code>Waiting for the real page and Python bridge.</p>"
        "<p>诊断目录 / Diagnostics:</p><pre data-startup-path></pre></section>"
    )
    css += "\n#startup-status[hidden]{display:none!important}#startup-status pre{white-space:pre-wrap;overflow-wrap:anywhere}"
    template = template.replace("<body>", "<body>" + overlay)
    return (
        template.replace("__CSS__", css)
        .replace("__JS__", script)
        .replace("__NONCE__", secrets.token_urlsafe(24))
    )


def mapping_probe_document(diagnostics):
    """One visible paragraph, no app frontend: isolates native local mapping from UI failures."""
    nonce = secrets.token_urlsafe(24)
    packet = json.dumps({"channel": "cda-startup-v1", "run_id": diagnostics.run_id})
    script = """
    (()=>{const base=__PACKET__;let started=false;
    const send=event=>window.chrome.webview.postMessage({...base,event});
    const dom=new Promise(resolve=>document.addEventListener('DOMContentLoaded',()=>{send('dom_ready');resolve();},{once:true}));
    async function bridge(){if(started||!window.pywebview?.api?.invoke)return;started=true;
      send('bridge_ready');try{await dom;const result=await window.pywebview.api.invoke('get_state',{});
      if(!result?.ok)throw new Error();document.querySelector('p').textContent='Offline local mapping probe: READY';
      send('ui_ready');}catch{send('backend_bootstrap_failed');}}
    window.addEventListener('pywebviewready',bridge);
    document.addEventListener('DOMContentLoaded',bridge,{once:true});
    window.addEventListener('error',()=>send('javascript_error'));
    })();""".replace("__PACKET__", packet)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'nonce-{nonce}' 'unsafe-eval'; connect-src 'none'\">"
        '<link rel="icon" href="data:,"><title>Offline mapping probe</title>'
        f'<script nonce="{nonce}">{script}</script></head>'
        "<body><p>Offline local mapping probe: waiting for Python bridge.</p></body></html>"
    )


def launch(root, qa=False, width=1440, height=900, smoke_test=False, diagnostics=None, mapping_probe=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    diagnostics = diagnostics or StartupDiagnostics(root, operations_enabled=qa)
    diagnostics.event(
        "paths",
        executable=str(Path(sys.executable).resolve()),
        cwd=str(Path.cwd()),
        resource_base=str(resource_base()),
        data_directory=str(root.resolve()),
        frozen=bool(getattr(sys, "frozen", False)),
    )
    logger = logging.getLogger("pywebview")
    handler = SafeWebviewHandler(diagnostics)
    previous_level = logger.level
    previous_handlers, previous_propagate = logger.handlers[:], logger.propagate
    logger.handlers, logger.propagate = [handler], False
    logger.setLevel(logging.DEBUG)
    old_sys_hook, old_thread_hook = sys.excepthook, threading.excepthook
    restore_navigation_adapter = None

    def unhandled(_kind, error, _trace):
        diagnostics.exception("unhandled_python", error)
        diagnostics.fail("python_exception")

    def thread_error(args):
        unhandled(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook, threading.excepthook = unhandled, thread_error
    try:
        runtime = webview_runtime()
        (root / "webview-preflight.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
        diagnostics.event("runtime_preflight", **runtime)
        if not runtime["available"]:
            diagnostics.fail("runtime_missing")
            raise RuntimeError("WebView2 Runtime 120+ is required; no automatic installation.")
        try:
            document = mapping_probe_document(diagnostics) if mapping_probe else html_document(diagnostics)
        except Exception as error:
            diagnostics.exception("resource_assembly", error)
            diagnostics.fail("resource_integrity_failed")
            raise
        page_directory = diagnostics.directory / "runtime-page"
        page_directory.mkdir()
        (page_directory / "index.html").write_text(document, encoding="utf-8")
        diagnostics.event("document_prepared", url=APP_URL, html_bytes=len(document.encode("utf-8")))
        import webview

        binary_directory = runtime_directory(runtime)
        webview.settings.update(
            {
                "ALLOW_DOWNLOADS": False,
                "ALLOW_FILE_URLS": False,
                "OPEN_EXTERNAL_LINKS_IN_BROWSER": False,
                "OPEN_DEVTOOLS_IN_DEBUG": False,
                "REMOTE_DEBUGGING_PORT": None,
                "IGNORE_SSL_ERRORS": False,
                "WEBVIEW2_RUNTIME_PATH": str(binary_directory) if binary_directory else None,
            }
        )
        diagnostics.event(
            "runtime_binding", directory=str(binary_directory) if binary_directory else "system_lookup"
        )
        api = Bridge(root, qa=qa)
        api._diagnostics = diagnostics
        window = webview.create_window(
            "Canvas Deadline Agent · UI Review" if qa else "Canvas Deadline Agent",
            url=APP_URL,
            js_api=api,
            width=width,
            height=height,
            min_size=(760, 580),
            background_color="#F6F7F4",
            text_select=True,
        )
        from .web_actions import NativeActions

        api._native = NativeActions(window)

        def failed(code):
            (diagnostics.directory / "failure.html").write_text(
                error_document(code, diagnostics.directory), encoding="utf-8"
            )
            native_error_panel(window, diagnostics, code)

        diagnostics.on_failure = failed

        def selected(renderer):
            nonlocal restore_navigation_adapter
            diagnostics.event(
                "renderer_selected",
                renderer=str(renderer) if renderer in ("edgechromium", "mshtml") else "unexpected",
            )
            if renderer != "edgechromium":
                diagnostics.fail("renderer_mismatch")
                return False  # abort pywebview initialization; never silently use MSHTML
            try:
                restore_navigation_adapter = ordered_initial_navigation(window, diagnostics, page_directory)
            except Exception as error:
                diagnostics.exception("initial_navigation_adapter", error)
                diagnostics.fail("native_policy_failed")
                return False

        def shown():
            diagnostics.event("window_shown")
            threading.Thread(target=diagnostics.deadline, daemon=True).start()

        def ready():
            if smoke_test:
                (root / "gui-smoke-result.json").write_text(
                    json.dumps(
                        {
                            "status": "passed",
                            "renderer": "edgechromium",
                            "evidence": "real_page_ready_handshake",
                        }
                    ),
                    encoding="utf-8",
                )
                threading.Thread(target=window.destroy, daemon=True).start()

        diagnostics.on_ready = ready
        window.events.initialized += selected
        window.events.shown += shown
        window.events.closed += diagnostics.close
        window.events.closed += api._close
        window.events.loaded += lambda: diagnostics.event("pywebview_loaded", evidence="not_ui_success")
        diagnostics.event("backend_start_requested", renderer="edgechromium", http_server=False)
        webview.start(
            gui="edgechromium",
            http_server=False,
            debug=False,
            private_mode=True,
            storage_path=str(root / "webview-cache"),
        )
        if diagnostics.status == "failed" or (smoke_test and diagnostics.status != "ready"):
            raise RuntimeError("GUI Startup Failure; see persistent QA diagnostics")
    except Exception as error:
        diagnostics.exception("launch", error)
        diagnostics.fail("python_exception")
        (diagnostics.directory / "failure.html").write_text(
            error_document(diagnostics.failure or "python_exception", diagnostics.directory), encoding="utf-8"
        )
        raise
    finally:
        if restore_navigation_adapter:
            restore_navigation_adapter()
        logger.handlers, logger.propagate = previous_handlers, previous_propagate
        logger.setLevel(previous_level)
        sys.excepthook, threading.excepthook = old_sys_hook, old_thread_hook
