"""Real Bridge/ProcessLock/SQLite writes and genuine thread/transaction contention."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from canvas_agent.storage import Store
from canvas_agent.web_bridge import Bridge
from canvas_agent.web_qa import prepare_qa_root


def fixture(root):
    prepare_qa_root(root)
    bridge = Bridge(root, qa=True)
    state = bridge.invoke("get_state", {})["data"]
    task = next(
        t
        for t in state["tasks"]
        if t["local"]["state"] == "tracking" and t["status"] == "Confirmed Not Submitted"
    )
    return bridge, {"key": task["key"], "account_scope": state["account_scope"]}, state


def persisted(root, params):
    store = Store(root)
    try:
        task = next(t for t in store.cached() if t["key"] == params["key"])
        row = store.db.execute(
            "SELECT state FROM local_tracking WHERE account=? AND task_key=?",
            (params["account_scope"], params["key"]),
        ).fetchone()
        history = store.db.execute(
            "SELECT COUNT(*) FROM local_tracking_history WHERE account=? AND task_key=?",
            (params["account_scope"], params["key"]),
        ).fetchone()[0]
        return {"local": row[0] if row else "tracking", "canvas": task["status"], "history": history}
    finally:
        store.close()


def test_real_mutations_persist_and_do_not_rewrite_canvas(tmp_path):
    bridge, params, original = fixture(tmp_path / "qa")
    for choice in ("ignored", "tracking", "completed"):
        result = bridge.invoke(
            "set_tracking", params | {"state": choice, "reason": "other", "note": "Synthetic note"}
        )
        assert result == {"ok": True, "data": {"saved": True, "changed": True, "state": choice}}
        actual = persisted(tmp_path / "qa", params)
        assert actual["local"] == choice and actual["canvas"] == "Confirmed Not Submitted"
        restarted = Bridge(tmp_path / "qa", qa=True).invoke("get_state", {})["data"]
        assert next(t for t in restarted["tasks"] if t["key"] == params["key"])["local"]["state"] == choice
        assert restarted["account_scope"] == original["account_scope"]
    other, _, _ = fixture(tmp_path / "other-qa")
    assert other.invoke("get_state", {})["data"]["tasks"][0]["local"]["state"] == "tracking"
    assert not bridge.invoke("set_tracking", params | {"account_scope": "other-account", "state": "ignored"})[
        "ok"
    ]


@pytest.mark.parametrize("held", ["sync", "workspace"])
def test_actual_inflight_conflict_is_classified_and_recovers(tmp_path, held):
    bridge, params, _ = fixture(tmp_path / "qa")
    entered, release = threading.Event(), threading.Event()
    original = getattr(bridge, "_" + held)

    def controlled(arguments):
        entered.set()
        assert release.wait(5)
        return original(arguments)

    setattr(bridge, "_" + held, controlled)
    arguments = {} if held == "sync" else params | {"operation": "revoke"}
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(bridge.invoke, held, arguments)
        assert entered.wait(5)
        try:
            result = bridge.invoke("set_tracking", params | {"state": "ignored"})
            assert result == {
                "ok": False,
                "error": "busy",
                "operation": "set_tracking",
                "reason": "bridge_operation_in_progress",
                "blocking_operation": held,
            }
            assert persisted(tmp_path / "qa", params)["local"] == "tracking"
        finally:
            release.set()
        assert future.result()["ok"]
    assert bridge.invoke("set_tracking", params | {"state": "ignored"})["ok"]


def test_repeated_and_parallel_clicks_write_one_history_entry(tmp_path):
    bridge, params, _ = fixture(tmp_path / "qa")
    before = persisted(tmp_path / "qa", params)["history"]
    with ThreadPoolExecutor(8) as executor:
        results = list(
            executor.map(lambda _: bridge.invoke("set_tracking", params | {"state": "ignored"}), range(24))
        )
    assert any(result["ok"] for result in results)
    for result in results:
        if not result["ok"]:
            assert result["error"] == "busy" and result["reason"] == "bridge_operation_in_progress"
            assert bridge.invoke("set_tracking", params | {"state": "ignored"})["ok"]
    assert bridge.invoke("set_tracking", params | {"state": "ignored"})["data"]["changed"] is False
    assert persisted(tmp_path / "qa", params)["history"] == before + 1


def test_real_sqlite_failure_rolls_back_and_releases_both_locks(tmp_path):
    bridge, params, _ = fixture(tmp_path / "qa")
    before = persisted(tmp_path / "qa", params)
    with sqlite3.connect(tmp_path / "qa/state.sqlite") as db:
        db.execute(
            "CREATE TRIGGER fail_local BEFORE INSERT ON local_tracking BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
    assert bridge.invoke("set_tracking", params | {"state": "ignored"}) == {
        "ok": False,
        "error": "operation_failed",
    }
    assert persisted(tmp_path / "qa", params) == before
    with sqlite3.connect(tmp_path / "qa/state.sqlite") as db:
        db.execute("DROP TRIGGER fail_local")
    with ThreadPoolExecutor(1) as executor:
        assert executor.submit(bridge.invoke, "set_tracking", params | {"state": "ignored"}).result()["ok"]


def test_other_process_profile_lock_is_not_removed_or_bypassed(tmp_path):
    from canvas_agent.security import ProcessLock

    bridge, params, _ = fixture(tmp_path / "qa")
    with ProcessLock(tmp_path / "qa"):
        result = bridge.invoke("set_tracking", params | {"state": "ignored"})
        assert result == {
            "ok": False,
            "error": "busy",
            "operation": "set_tracking",
            "reason": "profile_operation_in_progress",
            "blocking_operation": "background_or_other_process",
        }
    assert bridge.invoke("set_tracking", params | {"state": "ignored"})["ok"]


def test_real_database_lock_is_classified_without_exception_text(tmp_path, monkeypatch):
    bridge, params, _ = fixture(tmp_path / "qa")
    connection = sqlite3.connect(tmp_path / "qa/state.sqlite")
    connection.execute("BEGIN IMMEDIATE")
    original = sqlite3.connect
    monkeypatch.setattr(
        sqlite3, "connect", lambda *args, **kwargs: original(*args, **(kwargs | {"timeout": 0}))
    )
    try:
        result = bridge.invoke("set_tracking", params | {"state": "ignored"})
        assert result == {
            "ok": False,
            "error": "busy",
            "operation": "set_tracking",
            "reason": "database_locked",
            "blocking_operation": "database_transaction",
        }
    finally:
        connection.rollback()
        connection.close()
    assert bridge.invoke("set_tracking", params | {"state": "ignored"})["ok"]


def test_no_window_assignment_check_uses_real_writes(tmp_path):
    from canvas_agent.backend_check import check_assignments

    result = check_assignments(tmp_path / "new-synthetic")
    assert result["status"] == "passed" and result["gui_started"] is False
    assert [case["state"] for case in result["assignment_cases"]] == ["ignored", "tracking", "completed"]
    assert all(case["passed"] for case in result["assignment_cases"])


def test_assignment_check_refuses_to_mutate_existing_profile(tmp_path):
    from canvas_agent.backend_check import check_assignments

    root = tmp_path / "qa"
    bridge, _, _ = fixture(root)
    before = (root / "state.sqlite").read_bytes()
    assert check_assignments(root)["code"] == "fresh_synthetic_directory_required"
    assert (root / "state.sqlite").read_bytes() == before
    assert bridge.invoke("get_state", {})["ok"]
