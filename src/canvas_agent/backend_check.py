"""Actual GUI backend bootstrap path, explicitly without a window, CLR or external services."""

import json
import sys
from pathlib import Path

from .startup_diagnostics import StartupDiagnostics
from .web_bridge import Bridge
from .web_qa import prepare_qa_root


def check_backend(root):
    root = Path(root)
    # This helper is QA-only. Its preparation/backup and Bridge._state are the GUI's own paths.
    try:
        prepare_qa_root(root)
    except Exception:
        return {
            "status": "failed",
            "code": "qa_preparation_failed",
            "stage": "qa_prepare",
            "gui_started": False,
        }
    diagnostics = StartupDiagnostics(root, mode="backend_check")
    bridge = Bridge(root, qa=True)
    bridge._diagnostics = diagnostics
    diagnostics.event("backend_check_started", frozen=bool(getattr(sys, "frozen", False)))
    result = bridge.invoke("get_state", {})
    forbidden = [
        name
        for name in ("webview.platforms.winforms", "webview.platforms.edgechromium")
        if name in sys.modules
    ]
    success = result.get("ok") is True and "backend_state_ready" in diagnostics.flags and not forbidden
    if success:
        state = result["data"]
        record = {
            "status": "passed",
            "code": "backend_initialized",
            "tasks": len(state["tasks"]),
            "credentials": state["credentials"],
            "qa": state["qa"],
        }
    else:
        record = {
            "status": "failed",
            "code": result.get("error", "unexpected_gui_import"),
            "reason": result.get("reason"),
            "fields": result.get("fields", []),
        }
    record.update(
        frozen=bool(getattr(sys, "frozen", False)),
        mode="backend_check",
        gui_started=False,
        ui_ready=False,
        stages=sorted(diagnostics.flags),
        diagnostics=str(diagnostics.directory),
        forbidden_gui_imports=forbidden,
    )
    diagnostics.event("backend_check_completed", status=record["status"])
    diagnostics.close()  # backend-only success must never mark native/DOM/UI stages complete
    (root / "backend-check-result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def check_assignments(root):
    """Destructive only to a NEW explicit synthetic fixture; never reuse an existing profile."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        return {"status": "failed", "code": "fresh_synthetic_directory_required", "gui_started": False}
    record = check_backend(root)
    if record["status"] != "passed":
        return record
    from .storage import Store

    cases = []
    bridge = Bridge(root, qa=True)
    state = bridge.invoke("get_state", {})["data"]
    task = state["tasks"][0]
    params = {"key": task["key"], "account_scope": state["account_scope"]}
    original_status = task["status"]
    try:
        for choice in ("ignored", "tracking", "completed"):
            result = bridge.invoke("set_tracking", params | {"state": choice})
            store = Store(root)
            try:
                actual = store.db.execute(
                    "SELECT state FROM local_tracking WHERE account=? AND task_key=?",
                    (params["account_scope"], params["key"]),
                ).fetchone()
                canvas = next(t for t in store.cached() if t["key"] == params["key"])["status"]
                history_before = len(store.db.execute("SELECT id FROM local_tracking_history").fetchall())
            finally:
                store.close()
            repeated = bridge.invoke("set_tracking", params | {"state": choice})
            restarted = Bridge(root, qa=True).invoke("get_state", {})
            restored = next(t for t in restarted["data"]["tasks"] if t["key"] == params["key"])
            store = Store(root)
            try:
                history_after = len(store.db.execute("SELECT id FROM local_tracking_history").fetchall())
            finally:
                store.close()
            passed = (
                result.get("ok") is True
                and result["data"].get("saved") is True
                and actual is not None
                and actual[0] == choice
                and canvas == original_status
                and restored["local"]["state"] == choice
                and restored["status"] == original_status
                and repeated.get("ok") is True
                and repeated["data"].get("changed") is False
                and history_before == history_after
            )
            cases.append(
                {
                    "state": choice,
                    "passed": passed,
                    "sqlite_verified": actual is not None and actual[0] == choice,
                    "restart_verified": restored["local"]["state"] == choice,
                    "canvas_unchanged": canvas == original_status,
                    "repeated_write_deduplicated": history_before == history_after,
                }
            )
        record.update(
            status="passed" if all(case["passed"] for case in cases) else "failed",
            code="assignment_mutations_checked",
            assignment_cases=cases,
        )
    except Exception as error:
        record.update(status="failed", code="assignment_check_failed", exception_type=type(error).__name__)
    finally:
        bridge._close()
    (root / "assignment-check-result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
