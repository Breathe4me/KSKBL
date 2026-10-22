"""Credential-free startup state machine. No GUI imports or arbitrary exception messages."""

import hashlib
import html
import json
import logging
import re
import threading
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import ConfigurationError
from .operation_diagnostics import OperationLog

STAGES = frozenset(
    {
        "core_ready",
        "navigation_started",
        "navigation_completed",
        "dom_ready",
        "bridge_ready",
        "backend_state_ready",
        "ui_ready",
    }
)
FAILURES = frozenset(
    {
        "native_initialization_failed",
        "native_policy_failed",
        "navigation_failed",
        "navigation_blocked",
        "renderer_mismatch",
        "startup_timeout",
        "javascript_error",
        "resource_failed",
        "csp_violation",
        "backend_bootstrap_failed",
        "process_failed",
        "resource_integrity_failed",
        "runtime_missing",
        "python_exception",
    }
)


class StartupDiagnostics:
    def __init__(self, root, mode="application", operations_enabled=False):
        if mode not in ("application", "mapping_probe", "backend_check"):
            raise ValueError("invalid_diagnostic_mode")
        self.mode = mode
        self.run_id = uuid.uuid4().hex
        self.directory = Path(root).resolve() / "diagnostics" / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.operations = OperationLog(self.directory, self.run_id, operations_enabled)
        self._lock = threading.RLock()
        self.finished = threading.Event()
        self.flags = set()
        self.status = "starting"
        self.failure = None
        self.on_failure = None
        self.on_ready = None
        self.event("entry", version="1.2.0", severity="P0", issue="GUI Startup Failure")

    def event(self, event, **fields):
        # Callers supply only fixed codes, paths, counts, hashes, enum values, types and frame locations.
        with self._lock:
            item = {"at": datetime.now(UTC).isoformat(), "event": event, **fields}
            with (self.directory / "startup.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _snapshot(self):
        data = {
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "failure": self.failure,
            "stages": sorted(self.flags),
            "required": sorted(STAGES),
        }
        (self.directory / "startup-status.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    def signal(self, stage):
        if stage not in STAGES:
            raise ValueError("unsupported_startup_stage")
        callback = None
        with self._lock:
            self.flags.add(stage)
            self.event(stage)
            if self.status == "starting" and self.flags == STAGES:
                self.status = "ready"
                self.finished.set()
                self.event("startup_ready", evidence="native_events_and_real_page_handshake")
                callback = self.on_ready
            self._snapshot()
        if callback:
            callback()

    def fail(self, code):
        if code not in FAILURES:
            code = "python_exception"
        with self._lock:
            if self.status in ("failed", "closed"):
                return
            self.status, self.failure = "failed", code
            self.event("startup_failed", code=code, stages=sorted(self.flags))
            self._snapshot()
            self.finished.set()
        if self.on_failure:
            self.on_failure(code)

    def exception(self, where, error):
        if isinstance(error, ConfigurationError):
            self.event(
                "configuration_error",
                stage=where,
                code=error.code,
                reason=error.reason,
                fields=list(error.fields),
            )
        frames = [
            {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(getattr(error, "__traceback__", None))
        ]
        hresult = getattr(error, "HResult", None)
        self.event(
            "python_exception",
            where=where,
            exception_type=type(error).__name__,
            frames=frames,
            hresult=hresult if type(hresult) is int else None,
        )
        if any(frame["file"] in {"ssl.py", "transport.py"} for frame in frames):
            from .tls_diagnostics import exception_chain, snapshot

            try:
                self.event("tls_initialization_error", chain=exception_chain(error), environment=snapshot())
            except OSError:
                self.event("tls_diagnostic_resource_unreadable", exception_type=type(error).__name__)

    def receive(self, message):
        if (
            type(message) is not dict
            or message.get("run_id") != self.run_id
            or message.get("channel") != "cda-startup-v1"
        ):
            return False
        event = message.get("event")
        if type(event) is not str:
            return False
        if event in {"dom_ready", "bridge_ready", "ui_ready"}:
            self.signal(event)
        elif event in {"javascript_error", "resource_failed", "csp_violation", "backend_bootstrap_failed"}:
            # Never log error text, promise values, source URLs, DOM or provider contents.
            safe = {
                key: message[key]
                for key in ("line", "column")
                if type(message.get(key)) is int and 0 <= message[key] < 1000000
            }
            self.event("frontend_error", code=event, **safe)
            self.fail(event)
        else:
            return False
        return True

    def deadline(self, seconds=25):
        # A failure deadline only; success can only come from every real startup signal.
        if not self.finished.wait(seconds):
            self.fail("startup_timeout")

    def close(self):
        with self._lock:
            self.event("window_closed", startup_status=self.status)
            if self.status == "starting":
                self.status = "closed"
                self._snapshot()
            self.finished.set()


class SafeWebviewHandler(logging.Handler):
    def __init__(self, diagnostics):
        super().__init__()
        self.diagnostics = diagnostics

    def emit(self, record):
        self.diagnostics.event(
            "pywebview_log", level=record.levelname, module=record.module, line=record.lineno
        )
        if record.exc_info and isinstance(record.exc_info[1], BaseException):
            self.diagnostics.exception("pywebview_callback", record.exc_info[1])


def checked_resources(base, diagnostics=None):
    directory = Path(base) / "frontend"
    records = {}
    for name in ("index.html", "prototype.css", "app.css", "app.js", "startup.js"):
        path = directory / name
        data = path.read_bytes()
        if not data:
            raise ValueError("empty_frontend_resource")
        records[name] = {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest = Path(base) / "frontend-sha256.json"
    if manifest.is_file():
        pins = json.loads(manifest.read_text(encoding="utf-8"))
        if {name: item["sha256"] for name, item in records.items()} != pins:
            raise ValueError("frontend_resource_hash_mismatch")
    if diagnostics:
        (diagnostics.directory / "resources.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        diagnostics.event(
            "resources_verified", base=str(directory), manifest=manifest.is_file(), count=len(records)
        )
    return directory


def error_document(code, directory):
    safe = code if re.fullmatch(r"[a-z_]{1,80}", code) else "startup_failed"
    return (
        '<!doctype html><meta charset="utf-8"><title>P0 GUI Startup Failure</title>'
        '<body style="font:16px/1.7 Segoe UI,Microsoft YaHei UI,sans-serif;padding:40px;background:#fff7f4;color:#502d29">'
        "<h1>P0 · GUI Startup Failure</h1><p>界面初始化失败 / UI initialization failed.</p>"
        f"<p>Code: {safe}</p><p>诊断目录 / Diagnostics:</p><pre>{html.escape(str(directory))}</pre>"
        "<p>保留日志后关闭窗口；无需重装 Windows。请勿发送任何凭据。</p></body>"
    )
