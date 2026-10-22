"""QA-only correlated metadata. Never accept free-form messages, params, content or credentials."""

import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

FRONTEND_STAGES = frozenset(
    {
        "click_received",
        "frontend_guard_rejected",
        "state_modal_open",
        "action_started",
        "action_failed",
        "action_released",
        "frontend_rpc_prepare",
        "frontend_rpc_dispatch",
        "frontend_rpc_response",
        "frontend_rpc_rejected",
        "frontend_rpc_timeout",
        "frontend_rpc_settled",
        "refresh_started",
        "refresh_succeeded",
        "refresh_failed",
        "operation_cancelled",
    }
)
PYTHON_STAGES = frozenset(
    {
        "python_rpc_enter",
        "python_rpc_exit",
        "bridge_lock_acquired",
        "bridge_lock_released",
        "python_busy",
        "mutation_enter",
        "profile_lock_acquired",
        "sqlite_write_enter",
        "sqlite_commit",
        "sqlite_no_change",
        "sqlite_write_failed",
        "invalid_trace_context",
    }
)
OPERATIONS = frozenset(
    {
        "get_state",
        "set_tracking",
        "workspace",
        "sync",
        "confirmstate",
        "state_selection",
        "save_settings",
        "save_credential",
        "remove_credential",
        "verify_submission",
        "assignment_context",
        "test_pushplus",
        "test_identity",
        "open_official",
        "generate_prompt",
        "export_prompt",
        "review_files",
        "backup_data",
        "import_backup",
        "announcements",
        "announcement_summary",
        "test_ai",
        "weekly_preview",
        "runtime_status",
        "confirm_push_received",
        "copy_prompt",
        "emergency_prepare",
        "background_or_other_process",
        "database_transaction",
        "unknown",
        "other",
        "none",
    }
)
REASONS = frozenset(
    {
        "bridge_operation_in_progress",
        "profile_operation_in_progress",
        "database_locked",
        "outcome_pending",
        "outcome_pending_reload_to_verify",
        "expired_before_dispatch",
        "disabled",
        "frontend_busy",
        "window_closed",
        "invalid_trace_context",
        "transport_exception",
        "other",
    }
)
CODES = frozenset(
    {
        "busy",
        "qa_credentials_disabled",
        "credential_value_required",
        "credential_storage_failed",
        "ai_endpoint_mismatch",
        "request_timeout",
        "window_closed",
        "invalid_request",
        "operation_failed",
        "configuration_invalid",
        "stale_account",
        "sqlite_integrity",
        "sqlite_busy",
        "service_exception",
        "other",
    }
)


def request_id(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{32}", value) is not None


def safe_fields(fields):
    result = {}
    for key in ("busy", "closed", "disabled", "ok", "changed", "has_bridge"):
        if type(fields.get(key)) is bool:
            result[key] = fields[key]
    for key in ("owner_request_id", "queue_request_id"):
        if request_id(fields.get(key)):
            result[key] = fields[key]
    for key in ("operation", "owner", "blocking_operation", "queue_owner"):
        if type(fields.get(key)) is str:
            result[key] = fields[key] if fields[key] in OPERATIONS else "other"
    for key, allowed in (
        ("reason", REASONS),
        ("code", CODES),
        ("state", {"ignored", "completed", "tracking"}),
    ):
        if type(fields.get(key)) is str:
            result[key] = fields[key] if fields[key] in allowed else "other"
    return result


class OperationLog:
    def __init__(self, directory, run_id, enabled=False):
        self.directory, self.run_id, self.enabled = Path(directory), run_id, enabled
        self._lock, self._count = threading.Lock(), 0
        self.write_failed = False

    def record(self, stage, correlation, origin="python", **fields):
        allowed = FRONTEND_STAGES if origin == "frontend" else PYTHON_STAGES
        if not self.enabled or type(stage) is not str or stage not in allowed or not request_id(correlation):
            return False
        with self._lock:
            if self._count >= 6000:
                return False
            item = {
                "at": datetime.now(UTC).isoformat(),
                "run_id": self.run_id,
                "request_id": correlation,
                "origin": origin,
                "stage": stage,
                "sequence": self._count + 1,
                **safe_fields(fields),
            }
            try:
                with (self.directory / "operations.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(item) + "\n")
            except OSError:
                self.write_failed = True
                return False  # diagnostics failure must not change business/transaction outcomes
            self._count += 1
        return True

    def receive(self, packet):
        if (
            type(packet) is not dict
            or packet.get("channel") != "cda-operation-v1"
            or packet.get("run_id") != self.run_id
        ):
            return False
        return self.record(packet.get("stage"), packet.get("request_id"), "frontend", **safe_fields(packet))


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def build_identity(base, executable, frozen=False):
    base = Path(base)
    frontend = {
        name: sha(base / "frontend" / name)
        for name in ("index.html", "prototype.css", "app.css", "app.js", "startup.js")
    }
    result = {
        "version": "1.2.0",
        "process_id": os.getpid(),
        "operation_protocol": "cda-operation-v1",
        "frozen": bool(frozen),
        "frontend_sha256": frontend,
        "frontend_set_sha256": hashlib.sha256(json.dumps(frontend, sort_keys=True).encode()).hexdigest(),
    }
    if frozen:
        result["executable_sha256"] = sha(executable)
    return result
