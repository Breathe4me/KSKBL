"""Single validated UI capability endpoint. No credential values are returned to JavaScript."""

import copy
import json
import re
import sqlite3
import threading
import uuid
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .api import CanvasAPI
from .assignment_context import fetch_context
from .config import DEFAULTS, ConfigurationError, load, save, validate
from .engine import run
from .notifications import Dispatcher, PushPlusChannel
from .operation_diagnostics import request_id as valid_request_id
from .release_info import version as release_version
from .rules import Message
from .security import CredentialError, ProcessLock, Secrets, ai_key, redact, safe_link
from .storage import Store
from .submission import verify
from .tracking import REASONS, STATES, Tracking


class NoCredentials:
    """Default QA transport never reads DPAPI, even from an accidentally populated QA folder."""

    def __init__(self, root):
        pass

    def get(self, kind):
        return ""

    def values(self):
        return ()

    def set(self, kind, value):
        raise ValueError("qa_credentials_disabled")


PUBLIC_SETTINGS = frozenset(DEFAULTS) - {"schema_version"}
TASK_FIELDS = ("key", "course_id", "course", "title", "kind", "due", "status", "points", "checked")


def arguments(value, required=(), optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError("invalid_arguments")


def text(value, limit=500):
    if type(value) is not str or len(value) > limit or "\x00" in value:
        raise ValueError("invalid_text")
    return value


class Bridge:
    """Only invoke is public; services, paths and native window are private bridge attributes."""

    def __init__(self, root, qa=False, secrets_factory=Secrets, api_factory=CanvasAPI):
        self._root, self._qa = Path(root), qa
        self._secrets_factory = NoCredentials if qa and secrets_factory is Secrets else secrets_factory
        self._api_factory = api_factory
        self._mutex = threading.Lock()
        self._active_operation = None
        self._trace_local = threading.local()
        self._native = None
        self._diagnostics = None
        self._closed = False

    def _close(self):
        self._closed = True
        session = getattr(self, "_workspace_session", None)
        if session:
            session["access"].revoke()

    def _trace(self, stage, **fields):
        diagnostics = self._diagnostics
        if diagnostics:
            diagnostics.operations.record(stage, getattr(self._trace_local, "request_id", None), **fields)

    def invoke(self, method, params, trace=None):
        previous = getattr(self._trace_local, "request_id", None)
        valid_trace = trace is None or (
            type(trace) is dict and set(trace) == {"request_id"} and valid_request_id(trace["request_id"])
        )
        self._trace_local.request_id = (
            trace["request_id"] if trace is not None and valid_trace else uuid.uuid4().hex
        )
        operation = method if type(method) is str else "other"
        self._trace("python_rpc_enter", operation=operation)
        result = {"ok": False, "error": "operation_failed"}
        try:
            if not valid_trace:
                self._trace("invalid_trace_context", operation=operation)
                result = {"ok": False, "error": "invalid_request"}
            else:
                result = self._invoke(method, params)
            return result
        finally:
            self._trace(
                "python_rpc_exit",
                operation=operation,
                ok=result.get("ok") is True,
                code=result.get("error", "other"),
                reason=result.get("reason", "other"),
            )
            self._trace_local.request_id = previous

    def _invoke(self, method, params):
        handlers = {
            "get_state": self._state,
            "set_tracking": self._tracking,
            "save_settings": self._settings,
            "save_credential": self._credential,
            "remove_credential": self._remove_credential,
            "sync": self._sync,
            "verify_submission": self._verify,
            "assignment_context": self._context,
            "test_pushplus": self._test_pushplus,
            "test_identity": self._test_identity,
            "open_official": self._open_official,
            "generate_prompt": self._prompt,
            "export_prompt": self._export_prompt,
            "review_files": self._review_files,
            "backup_data": self._backup,
            "import_backup": self._import_backup,
            "announcements": self._announcements,
            "announcement_summary": self._announcement_summary,
            "test_ai": self._test_ai,
            "weekly_preview": self._weekly_preview,
            "workspace": self._workspace,
            "runtime_status": self._runtime_status,
            "confirm_push_received": self._confirm_push_received,
            "copy_prompt": self._copy_prompt,
            "emergency_prepare": self._emergency_prepare,
        }
        try:
            if type(method) is not str or method not in handlers:
                raise ValueError("unknown_method")
            # Bound the entire request before touching any native or storage service.
            if len(json.dumps(params, ensure_ascii=False)) > 20000:
                raise ValueError("request_too_large")
            if self._closed:
                return {"ok": False, "error": "window_closed"}
            if not self._mutex.acquire(blocking=False):
                return self._busy(method, "bridge_operation_in_progress", self._active_operation or "unknown")
            self._active_operation = method
            self._trace("bridge_lock_acquired", operation=method)
            try:
                result = handlers[method](params)
            finally:
                self._active_operation = None
                self._mutex.release()
                self._trace("bridge_lock_released", operation=method)
            result = self._scrub(result)
            if method == "get_state" and self._diagnostics:
                self._diagnostics.signal("backend_state_ready")
            return {"ok": True, "data": result}
        except Exception as error:
            if self._diagnostics:
                self._diagnostics.exception("bridge_invoke", error)
            # Stable API codes only. Never stringify arbitrary exception text.
            code = getattr(error, "code", None)
            if type(error).__name__ == "AlreadyRunning":
                return self._busy(method, "profile_operation_in_progress", "background_or_other_process")
            elif isinstance(error, sqlite3.OperationalError) and getattr(
                error, "sqlite_errorcode", 0
            ) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return self._busy(method, "database_locked", "database_transaction")
            elif (
                type(error) is ValueError
                and error.args
                and error.args[0]
                in {
                    "canvas_configuration_required",
                    "stale_account",
                    "official_page_required",
                    "explicit_ai_confirmation_required",
                    "explicit_test_confirmation_required",
                    "explicit_native_action_unavailable",
                    "credential_entry_unavailable",
                }
            ):
                code = error.args[0]
            if not isinstance(code, str) or not re.fullmatch(r"[a-z_]{1,80}", code):
                code = (
                    "invalid_request"
                    if isinstance(error, (ValueError, TypeError, KeyError))
                    else "operation_failed"
                )
            response = {"ok": False, "error": code}
            if isinstance(error, ConfigurationError):
                response.update(reason=error.reason, fields=list(error.fields))
            return response

    def _busy(self, operation, reason, blocking_operation):
        self._trace("python_busy", operation=operation, reason=reason, blocking_operation=blocking_operation)
        result = {
            "ok": False,
            "error": "busy",
            "operation": operation,
            "reason": reason,
            "blocking_operation": blocking_operation,
        }
        if self._diagnostics:
            self._diagnostics.event(
                "operation_busy", operation=operation, reason=reason, blocking_operation=blocking_operation
            )
        return result

    def _secrets(self):
        return self._secrets_factory(self._root)

    def _scrub(self, result):
        known = []
        vault = self._secrets()
        reader = getattr(vault, "values", None)
        if reader:
            try:
                known.extend(value for value in reader() if value)
            except (OSError, UnicodeError):
                pass
        for kind in ("canvas", "pushplus", "ai"):
            try:
                value = self._secrets().get(kind)
            except Exception:
                # An unreadable credential has no plaintext available for exact matching.
                # Generic token/URL redaction below still applies to every response.
                value = None
            if value:
                known.append(value)

        def visit(value):
            if isinstance(value, str):
                return redact(value, known)
            if isinstance(value, list):
                return [visit(item) for item in value]
            if isinstance(value, dict):
                return {key: visit(item) for key, item in value.items()}
            return value

        return visit(result)

    def _client(self):
        config = load(self._root / "config.json")
        token = self._secrets().get("canvas")
        if not token or not config["canvas_url"]:
            raise ValueError("canvas_configuration_required")
        return self._api_factory(config["canvas_url"], token)

    def _state(self, params):
        arguments(params)
        if self._diagnostics:
            self._diagnostics.event("backend_initialization_stage", stage="config_load")
        config = load(self._root / "config.json")
        if self._diagnostics:
            self._diagnostics.event("backend_initialization_stage", stage="state_load")
        store = Store(self._root)
        try:
            tasks = []
            selected = config["course_ids"]
            for task in Tracking(store).rows():
                if selected is not None and task["course_id"] not in selected:
                    continue
                row = {key: task.get(key) for key in TASK_FIELDS}
                row["local"] = {
                    key: task["local"].get(key) for key in ("state", "reason", "note", "content_changed")
                }
                latest = store.get("verification:" + task["key"], {})
                row["verification"] = {
                    key: latest.get(key) for key in ("status", "checked", "attempt", "error", "error_code")
                }
                tasks.append(row)
            credentials = {}
            for key in ("canvas", "pushplus", "ai"):
                try:
                    vault = self._secrets()
                    value = ai_key(vault, config) if key == "ai" else vault.get(key)
                    credentials[key] = "saved" if value else "missing"
                except Exception:
                    credentials[key] = "unreadable"
            history = [
                {k: item.get(k) for k in ("key", "checked", "status", "attempt", "error")}
                for item in store.get("verification_history", [])[-100:]
            ]
            delivery = []
            for row in store.db.execute(
                "SELECT key,channel,status,updated FROM delivery ORDER BY updated DESC LIMIT 20"
            ):
                attempt = store.get("delivery_attempt:" + row["channel"] + ":" + row["key"], {})
                item = {key: row[key] for key in ("channel", "status", "updated")}
                item["attempts"] = attempt.get("count", 0)
                item["next_retry_after"] = (
                    (datetime.fromisoformat(attempt["at"]) + timedelta(minutes=15)).isoformat()
                    if row["status"] == "failed" and item["attempts"] < 3 and attempt.get("at")
                    else None
                )
                delivery.append(item)
            policy = {
                "mode": "synthetic_only" if self._qa else "live",
                "can_save": not self._qa,
                "ai_legacy_rebind_required": False,
            }
            if not self._qa:
                legacy = getattr(self._secrets(), "legacy_ai_requires_rebind", None)
                if legacy:
                    policy["ai_legacy_rebind_required"] = legacy(config)
            return {
                "settings": {key: copy.deepcopy(config[key]) for key in PUBLIC_SETTINGS},
                "credentials": credentials,
                "credential_policy": policy,
                "tasks": tasks,
                "history": history,
                "local_history": Tracking(store).history(),
                "account_scope": store.get("account"),
                "qa": self._qa,
                "courses": [
                    {k: c.get(k) for k in ("id", "name", "course_code")}
                    for c in store.get("course_catalog", store.get("courses", []))
                ],
                "sync": {
                    key: store.get(key)
                    for key in (
                        "last_attempt",
                        "last_success",
                        "last_full_success",
                        "last_status",
                        "last_check",
                        "last_complete",
                        "last_error",
                    )
                },
                "coverage": [
                    {k: c.get(k) for k in ("course_id", "kind", "code")}
                    for c in store.get("capabilities", [])
                ],
                "pushplus": {
                    "configured": credentials["pushplus"] == "saved",
                    "last_test": store.get("pushplus_last_test"),
                    "budget": {
                        key: store.get("pushplus_budget", {}).get(key) for key in ("day", "count", "blocked")
                    },
                },
                "delivery": delivery,
                "application": {
                    "version": release_version(),
                    "database": str((self._root / "state.sqlite").resolve()),
                    "logs": str((self._root / "diagnostics").resolve()),
                    "scheduler_verified": False,
                },
                "failures": [
                    {k: f.get(k) for k in ("course_id", "kind", "code")} for f in store.get("failures", [])
                ],
                "events": [{k: e[k] for k in ("at", "code", "detail")} for e in store.events()[:20]],
            }
        finally:
            store.close()

    def _task(self, store, params):
        key = text(params["key"], 120)
        if not re.fullmatch(r"\d+:(assignment|quiz):\d+", key):
            raise ValueError("invalid_task")
        if params["account_scope"] != store.get("account") or not store.get("account"):
            raise ValueError("stale_account")
        task = next((t for t in store.cached() if t["key"] == key), None)
        if not task:
            raise ValueError("unknown_task")
        return task

    def _tracking(self, params):
        self._trace("mutation_enter", operation="set_tracking")
        arguments(params, ("key", "account_scope", "state"), ("reason", "note"))
        if params["state"] not in STATES or params.get("reason", "") not in REASONS:
            raise ValueError("invalid_state")
        note = text(params.get("note", ""))
        with ProcessLock(self._root):
            self._trace("profile_lock_acquired", operation="set_tracking")
            store = Store(self._root)
            try:
                task = self._task(store, params)
                tracking = Tracking(store)
                previous = tracking.get(task)
                changed = previous["content_changed"] or any(
                    previous[key] != value
                    for key, value in (
                        ("state", params["state"]),
                        ("reason", params.get("reason", "")),
                        ("note", note),
                    )
                )
                if changed:
                    self._trace("sqlite_write_enter", operation="set_tracking", state=params["state"])
                    try:
                        tracking.set(task, params["state"], params.get("reason", ""), note)
                    except Exception:
                        self._trace("sqlite_write_failed", operation="set_tracking", state=params["state"])
                        raise
                    self._trace(
                        "sqlite_commit", operation="set_tracking", state=params["state"], changed=True
                    )
                else:
                    self._trace(
                        "sqlite_no_change", operation="set_tracking", state=params["state"], changed=False
                    )
                if self._diagnostics:
                    self._diagnostics.event(
                        "assignment_state_committed",
                        operation="set_tracking",
                        state=params["state"],
                        changed=changed,
                        mode="qa" if self._qa else "live",
                    )
            finally:
                store.close()
        return {"saved": True, "changed": changed, "state": params["state"]}

    def _settings(self, params):
        arguments(params, ("settings",))
        changes = params["settings"]
        if type(changes) is not dict or not set(changes) <= PUBLIC_SETTINGS:
            raise ValueError("unsupported_settings")
        with ProcessLock(self._root):
            old = load(self._root / "config.json")
            updated = validate(old | changes)
            if self._qa and updated["monitoring"]:
                raise ValueError("qa_native_operations_disabled")
            if updated["monitoring"] != old["monitoring"]:
                from .schedule import install_task, remove_all_tasks

                if updated["monitoring"]:
                    install_task(self._root)
                else:
                    remove_all_tasks(self._root)
            if old["canvas_url"] != updated["canvas_url"]:
                store = Store(self._root)
                try:
                    store.reset_account()
                finally:
                    store.close()
            if old["timezone"] != updated["timezone"]:
                from .schedule import rebase_timezone

                store = Store(self._root)
                try:
                    rebase_timezone(updated, store, datetime.now(UTC))
                finally:
                    store.close()
            save(self._root / "config.json", updated)
        return {"saved": True}

    def _credential(self, params):
        arguments(params, ("kind", "value"))
        if params["kind"] not in ("canvas", "pushplus", "ai"):
            raise ValueError("invalid_credential_kind")
        value = text(params["value"], 4096).strip()
        if self._qa:
            raise CredentialError("qa_credentials_disabled")
        if not value:
            raise CredentialError("credential_value_required")
        with ProcessLock(self._root):
            vault = self._secrets()
            previous = ""
            if params["kind"] == "canvas":
                try:
                    previous = vault.get("canvas")
                except (OSError, UnicodeError):
                    previous = None  # explicit replacement may repair an unreadable old blob
            changed = params["kind"] == "canvas" and previous != value
            if params["kind"] == "ai" and hasattr(vault, "set_ai"):
                vault.set_ai(load(self._root / "config.json"), value)
            else:
                vault.set(params["kind"], value)
            if params["kind"] == "pushplus":
                store = Store(self._root)
                try:
                    store.set("pushplus_last_test", None)
                finally:
                    store.close()
            if changed:
                store = Store(self._root)
                try:
                    store.reset_account()
                finally:
                    store.close()
        return {"saved": True}

    def _remove_credential(self, params):
        arguments(params, ("kind",))
        if params["kind"] not in ("canvas", "pushplus", "ai"):
            raise ValueError("invalid_credential_kind")
        if self._qa:
            raise CredentialError("qa_credentials_disabled")
        with ProcessLock(self._root):
            vault = self._secrets()
            if params["kind"] == "ai" and hasattr(vault, "set_ai"):
                vault.set_ai(load(self._root / "config.json"), "")
            else:
                vault.set(params["kind"], "")
            if params["kind"] in ("canvas", "pushplus"):
                store = Store(self._root)
                try:
                    if params["kind"] == "canvas":
                        store.reset_account()
                    else:
                        store.set("pushplus_last_test", None)
                finally:
                    store.close()
            if params["kind"] == "pushplus":
                config = load(self._root / "config.json")
                save(
                    self._root / "config.json",
                    config
                    | {
                        "channels": [c for c in config["channels"] if c != "pushplus"] or ["windows"],
                        "weekly_channels": [c for c in config["weekly_channels"] if c != "pushplus"]
                        or ["windows"],
                    },
                )
        return {"removed": True}

    def _sync(self, params):
        arguments(params)
        if self._qa:
            return {"status": "qa_offline", "live_request": False}
        return run(
            self._root, api_factory=self._api_factory, secrets_factory=self._secrets_factory, sync_only=True
        )

    def _test_identity(self, params):
        arguments(params)
        if self._qa:
            return {"status": "qa_offline", "live_request": False}
        identity = self._client().identity()
        import hashlib

        config = load(self._root / "config.json")
        scope = hashlib.sha256(f"{config['canvas_url']}:{identity}".encode()).hexdigest()
        return {"status": "identity_verified", "account_scope": scope}

    def _verify(self, params):
        arguments(params, ("key", "account_scope"))
        with ProcessLock(self._root):
            store = Store(self._root)
            try:
                task = self._task(store, params)
                if self._qa:
                    return {"status": task["status"], "checked": datetime.now(UTC).isoformat(), "qa": True}
                if ":assignment:" not in task["key"]:
                    raise ValueError("official_page_required")
                result = verify(self._client(), task["course_id"], task["key"].split(":")[-1], store)
                return {
                    k: result.get(k)
                    for k in ("status", "checked", "attempt", "error", "error_code", "submitted_at")
                }
            finally:
                store.close()

    def _context(self, params):
        arguments(params, ("key", "account_scope"))
        store = Store(self._root)
        try:
            task = self._task(store, params)
            context = self._assignment(task)
            return {
                key: context.get(key)
                for key in (
                    "requirements",
                    "rubric",
                    "files",
                    "submission_types",
                    "allowed_extensions",
                    "missing",
                    "policy_status",
                    "rubric_status",
                )
            } | {
                "files": [
                    {k: item.get(k) for k in ("file_id", "name", "bytes", "status")}
                    for item in context.get("files", [])
                ]
            }
        finally:
            store.close()

    def _assignment(self, task):
        if self._qa:
            return {
                "course_id": task["course_id"],
                "assignment_id": int(task["key"].split(":")[-1]),
                "course": task["course"],
                "title": task["title"],
                "due": task["due"],
                "unlock": None,
                "lock": None,
                "points": task.get("points"),
                "requirements": "合成测试内容 / Synthetic requirements only.\n报告 PDF · 查看 Rubric · 检查提交确认。",
                "teacher_instructions": "Synthetic only",
                "rubric": [],
                "rubric_status": "Not provided",
                "files": [],
                "links": [],
                "ai_restrictions": [],
                "missing": ["Synthetic rubric unavailable"],
                "policy_status": "Unknown; check course AI policy",
                "url": "",
                "submission_types": ["online_upload"],
                "allowed_extensions": ["pdf"],
                "qa": True,
            }
        if ":assignment:" not in task["key"]:
            raise ValueError("official_page_required")
        return fetch_context(self._client(), task["course_id"], task["key"].split(":")[-1], task["course"])

    def _prompt(self, params):
        arguments(params, ("key", "account_scope"))
        from .prompt_builder import build_prompt

        with ProcessLock(self._root):
            store = Store(self._root)
            try:
                return {
                    "text": build_prompt(self._assignment(self._task(store, params))),
                    "generated_locally": True,
                }
            finally:
                store.close()

    def _require_dialogs(self, params):
        if params.get("confirmed") is not True or self._qa or self._native is None or self._closed:
            raise ValueError("explicit_native_action_unavailable")

    def _export_prompt(self, params):
        arguments(params, ("key", "account_scope", "confirmed"))
        self._require_dialogs(params)
        prompt = self._prompt({k: params[k] for k in ("key", "account_scope")})["text"]
        chosen = self._native.save_file("assignment-prompt.md", ("Markdown (*.md)",))
        if chosen is None:
            return {"status": "cancelled"}
        from .config import atomic_write

        atomic_write(chosen, self._scrub(prompt).encode("utf-8"))
        return {"status": "exported", "name": chosen.name}

    def _review_files(self, params):
        arguments(params, ("key", "account_scope", "confirmed"))
        self._require_dialogs(params)
        from .material_files import LocalAccess
        from .reviewer import review

        chosen = self._native.open_files(("Reviewable files (*.pdf;*.docx;*.md;*.txt;*.py;*.zip)",))
        if not chosen:
            return {"status": "cancelled"}
        access = LocalAccess()
        store = Store(self._root)
        try:
            access.grant(chosen)
            result = review(self._assignment(self._task(store, params)), access)
            # File content and full paths remain in Python; return observations only.
            return {
                "status": "reviewed",
                "files": [
                    {"name": item["name"], "status": item["status"], "bytes": item["bytes"]}
                    for item in result["files"]
                ],
                **{
                    k: result[k]
                    for k in (
                        "satisfied",
                        "possibly_unsatisfied",
                        "missing_files",
                        "issues",
                        "suggestions",
                        "unverified",
                        "label",
                    )
                },
            }
        finally:
            access.revoke()
            store.close()

    def _backup(self, params):
        arguments(params, ("confirmed",))
        self._require_dialogs(params)
        from .maintenance import backup

        chosen = self._native.save_file("canvas-agent-backup.zip", ("Agent backup (*.zip)",))
        if chosen is None:
            return {"status": "cancelled"}
        backup(self._root, chosen)
        return {"status": "backed_up", "name": chosen.name, "credentials_included": False}

    def _import_backup(self, params):
        arguments(params, ("confirmed",))
        self._require_dialogs(params)
        from .migration import import_backup

        chosen = self._native.open_backup()
        if chosen is None:
            return {"status": "cancelled"}
        result = import_backup(self._root, chosen)
        return {"status": result["status"], "monitoring": False, "credentials_imported": False}

    def _test_pushplus(self, params):
        arguments(params, ("confirmed",))
        if params["confirmed"] is not True or self._qa:
            raise ValueError("explicit_test_confirmation_required")
        from secrets import token_hex

        with ProcessLock(self._root):
            store = Store(self._root)
            try:
                secrets = self._secrets()
                dispatcher = Dispatcher(
                    store,
                    {"pushplus": PushPlusChannel(secrets.get("pushplus"))},
                    secrets.values(),
                    load(self._root / "config.json")["canvas_url"],
                )
                receipt_id = token_hex(12)
                result = dispatcher.send_result(
                    Message("test:" + receipt_id, "Canvas Deadline Agent", "Test reminder / 测试提醒"),
                    ["pushplus"],
                    datetime.now(UTC),
                )
                record = result | {
                    "receipt_id": receipt_id,
                    "at": datetime.now(UTC).isoformat(),
                    "delivery_confirmed": False,
                }
                store.set("pushplus_last_test", record)
                return record
            finally:
                store.close()

    def _announcements(self, params):
        arguments(params)
        config = load(self._root / "config.json")
        store = Store(self._root)
        try:
            selected = config["course_ids"]
            return {
                "account_scope": store.get("account"),
                "items": [
                    {key: item.get(key) for key in ("key", "course", "title", "posted", "body")}
                    for item in store.cached("announcements")
                    if selected is None or item["course_id"] in selected
                ],
            }
        finally:
            store.close()

    def _announcement_summary(self, params):
        arguments(params, ("key", "account_scope", "generate", "force", "confirmed"))
        for key in ("generate", "force", "confirmed"):
            if type(params[key]) is not bool:
                raise ValueError("invalid_summary_flags")
        if params["force"] and not params["generate"]:
            raise ValueError("force_requires_generation")
        if params["generate"] and (not params["confirmed"] or self._qa):
            raise ValueError("explicit_ai_confirmation_required")
        key = text(params["key"], 120)
        if not re.fullmatch(r"\d+:announcement:\d+", key):
            raise ValueError("invalid_announcement")
        from .ai import AIClient
        from .ai_presentation import format_result
        from .announcement_intelligence import summarize_one

        config = load(self._root / "config.json")
        store = Store(self._root)
        try:
            if not store.get("account") or params["account_scope"] != store.get("account"):
                raise ValueError("stale_account")
            item = next((item for item in store.cached("announcements") if item["key"] == key), None)
            if item is None or (
                config["course_ids"] is not None and item["course_id"] not in config["course_ids"]
            ):
                raise ValueError("unknown_announcement")
            secrets = self._secrets()
            client = AIClient(config, ai_key(secrets, config), secrets=secrets.values())
            # summarize_one uses the separate AI reservation lock, never the core monitor lock.
            result = summarize_one(
                item, client, store, config["language"], params["force"], params["generate"]
            )
            return {"text": format_result(result, config["language"]), "status": result["status"]}
        finally:
            store.close()

    def _test_ai(self, params):
        arguments(params, ("confirmed",))
        if params["confirmed"] is not True or self._qa:
            raise ValueError("explicit_ai_confirmation_required")
        from .ai import AIClient
        from .ai_presentation import format_result

        config = load(self._root / "config.json")
        secrets = self._secrets()
        result = AIClient(config, ai_key(secrets, config), secrets=secrets.values()).test()
        return {"text": format_result(result, config["language"]), "status": result["status"]}

    def _weekly_preview(self, params):
        arguments(params)
        from .models import Announcement, Snapshot, Task
        from .rules import weekly_report

        config = load(self._root / "config.json")
        store = Store(self._root)
        try:
            selected = config["course_ids"]

            def include(item):
                return selected is None or item["course_id"] in selected

            tasks = [
                Task(**{k: v for k, v in item.items() if k != "checked"})
                for item in store.cached()
                if include(item) and Tracking(store).active(item)
            ]
            announcements = [
                Announcement(**{k: v for k, v in item.items() if k != "checked"})
                for item in store.cached("announcements")
                if include(item)
            ]
            failures = [f for f in store.get("failures", []) if f["course_id"] == "all" or include(f)]
            capabilities = [c for c in store.get("capabilities", []) if include(c)]
            if not store.get("last_check"):
                failures = [{"course_id": "all", "kind": "not_checked", "code": "no_current_data"}]
            report = weekly_report(
                Snapshot(store.get("courses", []), tasks, announcements, [], failures, capabilities),
                config,
                datetime.now(UTC),
                "preview",
            )
            return {
                "title": report.title,
                "text": report.body,
                "cached_preview": True,
                "last_check": store.get("last_check"),
            }
        finally:
            store.close()

    def _workspace(self, params):
        from .web_copilot import operate

        return operate(self, params)

    def _open_official(self, params):
        arguments(params, ("destination",), ("key", "account_scope", "file_id"))
        if self._qa:
            return {"opened": False, "qa": True}
        if params["destination"] == "pushplus":
            url = "https://www.pushplus.plus/"
        elif params["destination"] in ("canvas", "attachment"):
            store = Store(self._root)
            try:
                task = self._task(store, params)
                url = safe_link(task["url"], load(self._root / "config.json")["canvas_url"])
                if params["destination"] == "attachment":
                    fid = params.get("file_id")
                    if type(fid) is not int or fid not in {
                        f["file_id"] for f in self._assignment(task)["files"]
                    }:
                        raise ValueError("attachment_not_in_assignment")
                    url = load(self._root / "config.json")["canvas_url"] + f"/files/{fid}"
            finally:
                store.close()
        else:
            raise ValueError("unsupported_destination")
        if not url:
            raise ValueError("official_link_unavailable")
        if self._closed:
            return {"opened": False, "status": "window_closed"}
        opened = bool(webbrowser.open(url))
        return {"opened": opened, "status": "opened" if opened else "browser_unavailable"}

    def _confirm_push_received(self, params):
        arguments(params, ("receipt_id", "confirmed"))
        if params["confirmed"] is not True or self._qa:
            raise ValueError("explicit_test_confirmation_required")
        with ProcessLock(self._root):
            store = Store(self._root)
            try:
                record = store.get("pushplus_last_test")
                if (
                    not record
                    or record["receipt_id"] != params["receipt_id"]
                    or record["status"] != "accepted"
                ):
                    raise ValueError("invalid_receipt")
                record.update(delivery_confirmed=True, confirmed_at=datetime.now(UTC).isoformat())
                store.set("pushplus_last_test", record)
                return {"status": "user_confirmed_received"}
            finally:
                store.close()

    def _runtime_status(self, params):
        arguments(params)
        from .schedule import deadline_task_info, next_slot, task_info, task_name

        config = load(self._root / "config.json")
        following = next_slot(config, datetime.now(UTC))
        result = {
            "monitoring": config["monitoring"],
            "task_name": task_name(self._root),
            "next_slot": following.isoformat() if following else None,
            "verified": False,
        }
        if self._qa:
            return result | {"status": "qa_native_not_queried"}
        try:
            return result | {
                "verified": True,
                "status": "queried",
                "task": task_info(self._root),
                "guardian": deadline_task_info(self._root),
            }
        except Exception as error:
            code = getattr(error, "code", "scheduler_query_failed")
            return result | {
                "status": code
                if type(code) is str and re.fullmatch(r"[a-z_]{1,80}", code)
                else "scheduler_query_failed"
            }

    def _copy_prompt(self, params):
        arguments(params, ("key", "account_scope", "mode", "confirmed"))
        self._require_dialogs(params)
        task_params = {key: params[key] for key in ("key", "account_scope")}
        if params["mode"] == "standard":
            value = self._prompt(task_params)["text"]
        elif params["mode"] == "workspace":
            value = self._workspace(task_params | {"operation": "workspace_prompt"})["text"]
        else:
            raise ValueError("invalid_prompt_mode")
        self._native.copy_text(self._scrub(value))
        return {"status": "copied"}

    def _emergency_prepare(self, params):
        arguments(params, ("key", "account_scope"))
        from .models import timestamp

        store = Store(self._root)
        try:
            task = self._task(store, params)
            due = timestamp(task.get("due"))
            eligible = (
                Tracking(store).active(task)
                and task["status"] not in ("Confirmed Submitted", "Graded")
                and due
                and 0 <= (due - datetime.now(UTC)).total_seconds() <= 3600
            )
            return {
                "eligible": bool(eligible),
                "status": "ready" if eligible else "outside_active_window",
                "steps": [
                    "Read official requirements and rubric",
                    "Review explicitly selected files",
                    "Generate a local prompt if permitted",
                    "Submit only on Canvas, then verify the latest status",
                ]
                if eligible
                else [],
                "paid_request": False,
                "automatic_submission": False,
            }
        finally:
            store.close()
