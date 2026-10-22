"""Explicit fresh-directory production backend/DPAPI check; no renderer or user profile access."""

import hashlib
import json
import secrets
import sys
from pathlib import Path

from .config import DEFAULTS, save
from .release_info import version
from .security import Secrets
from .web_bridge import Bridge


def _native_dependency_check(require):
    # Explicit CLI diagnostics only. Exercise substituted ABI dependencies, never a window.
    import _lzma
    import ctypes
    import lzma

    import winrt._winrt

    require(bool(winrt._winrt.__file__))

    from ctypes import wintypes

    sample = b"CDA native dependency roundtrip\x00" * 100
    for format_ in (lzma.FORMAT_XZ, lzma.FORMAT_ALONE):
        require(lzma.decompress(lzma.compress(sample, format=format_)) == sample)
    require(str(Path(_lzma.__file__).resolve()).startswith(str(Path(sys._MEIPASS).resolve())))
    # Real ctypes/libffi closure invocation (not a mocked adapter).
    callback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int)(lambda value: value + 1)
    require(callback(41) == 42)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel.GetModuleHandleW.restype = wintypes.HMODULE
    kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetModuleFileNameW.restype = wintypes.DWORD
    native_paths = {}
    for name in ("libffi-8.dll", "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
        handle = kernel.GetModuleHandleW(name)
        require(bool(handle))
        buffer = ctypes.create_unicode_buffer(32768)
        require(bool(kernel.GetModuleFileNameW(handle, buffer, len(buffer))))
        path = Path(buffer.value).resolve()
        require(
            path.parent == Path(sys._MEIPASS).resolve()
            if name == "libffi-8.dll"
            else path.parent == Path(__import__("os").environ["WINDIR"]).resolve() / "System32"
        )
        native_paths[name] = str(path)
    return {
        "case": "actual_lzma_ctypes_callback_WinRT_external_CRT",
        "passed": True,
        "loaded_native_paths": native_paths,
    }


def check(root):
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise ValueError("Release selfcheck requires a new empty explicit directory")
    root.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "failed",
        "version": version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "production_default": True,
        "gui_started": False,
        "cases": [],
    }

    def require(condition):
        if not condition:
            raise RuntimeError("release_selfcheck_failed")

    def forbidden_client(*args, **kwargs):
        raise RuntimeError("external_client_forbidden_in_release_selfcheck")

    try:
        save(root / "config.json", DEFAULTS)
        bridge = Bridge(root, qa=False, api_factory=forbidden_client)
        state = bridge.invoke("get_state", {})
        require(state["ok"] and not state["data"]["qa"] and state["data"]["tasks"] == [])
        require(all(value == "missing" for value in state["data"]["credentials"].values()))
        require(not state["data"]["settings"]["monitoring"] and not state["data"]["settings"]["ai_enabled"])
        require(not (root / "QA_ONLY.json").exists())
        result["cases"].append(
            {"case": "production_empty_first_run_no_QA_seed_no_secrets_no_background_AI", "passed": True}
        )
        for kind in ("canvas", "pushplus", "ai"):
            for _ in range(2):
                value = secrets.token_urlsafe(
                    28
                )  # temporary random canary, not a packaged sample or real credential
                require(bridge.invoke("save_credential", {"kind": kind, "value": value})["ok"])
                restarted = Bridge(root, qa=False, api_factory=forbidden_client).invoke("get_state", {})
                require(restarted["ok"] and restarted["data"]["credentials"][kind] == "saved")
                require(Secrets(root).get(kind) == value and value not in json.dumps(restarted))
            require(bridge.invoke("remove_credential", {"kind": kind})["ok"] and not Secrets(root).get(kind))
            result["cases"].append({"case": kind + "_actual_DPAPI_replace_restart_delete", "passed": True})
        if getattr(sys, "frozen", False):
            # Explicit diagnostic: real ABI/CLR without a renderer, window or service calls.
            from clr_loader import get_netfx

            runtime = get_netfx()
            try:
                info = runtime.info()
                require(info.kind == ".NET Framework")
            finally:
                runtime.shutdown()
            result["cases"].append({"case": "actual_CFFI_ABI_NetFx_no_renderer", "passed": True})
            result["cases"].append(_native_dependency_check(require))
        result["status"] = "passed"
        probe = secrets.token_urlsafe(32)
        Secrets(root).set("canvas", probe)
        result["persistence_probe_sha256"] = hashlib.sha256(probe.encode()).hexdigest()
        (root / "RELEASE_SELFCHECK_ONLY.json").write_text(
            '{"schema":1,"mode":"isolated_release_selfcheck"}', encoding="utf-8"
        )
        result["forbidden_gui_imports"] = [
            name
            for name in ("webview.platforms.winforms", "webview.platforms.edgechromium")
            if name in sys.modules
        ]
        require(not result["forbidden_gui_imports"])
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__)
    (root / "release-check-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def readback(root):
    root = Path(root)
    marker = json.loads((root / "RELEASE_SELFCHECK_ONLY.json").read_text(encoding="utf-8"))
    if marker != {"schema": 1, "mode": "isolated_release_selfcheck"}:
        raise ValueError("Not a selfcheck directory")
    previous = json.loads((root / "release-check-result.json").read_text(encoding="utf-8"))
    value = Secrets(root).get("canvas")
    state = Bridge(root, qa=False).invoke("get_state", {})
    passed = (
        previous["status"] == "passed"
        and hashlib.sha256(value.encode()).hexdigest() == previous["persistence_probe_sha256"]
    )
    passed = passed and state["ok"] and not state["data"]["qa"] and not state["data"]["tasks"]
    result = {
        "status": "passed" if passed else "failed",
        "version": version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "gui_started": False,
        "DPAPI_cross_process_persistence": bool(passed),
        "SQLite_empty_after_restart": bool(passed),
    }
    (root / "release-restart-check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
