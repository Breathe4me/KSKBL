"""Concurrent test transport: real QA Bridge/services/SQLite; only scheduling barriers are controlled."""

import json
import sqlite3
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from canvas_agent.storage import Store
from canvas_agent.web_bridge import Bridge
from canvas_agent.web_qa import prepare_qa_root
from canvas_agent.web_shell import html_document

root = prepare_qa_root(Path(sys.argv[1]))
baseline = len(sys.argv) > 2 and sys.argv[2] == "baseline"
document = html_document()
if baseline:
    project = Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(project / "reports/p0-assignment-busy-20261022-01/SOURCE_BEFORE.zip") as archive:
        namespace = {"__name__": "canvas_agent.baseline_web_bridge", "__package__": "canvas_agent"}
        exec(  # noqa: S102 - reviewed immutable source baseline, only test transport
            compile(archive.read("src/canvas_agent/web_bridge.py"), "baseline/web_bridge.py", "exec"),
            namespace,
        )
        Bridge = namespace["Bridge"]
        document = document.replace(
            (project / "frontend/app.js").read_text(encoding="utf-8"),
            archive.read("frontend/app.js").decode("utf-8"),
        )
bridge = Bridge(root, qa=True)
mutex = threading.Lock()
calls = []
hold = {"method": None, "entered": threading.Event(), "release": threading.Event()}
original_workspace, original_sync = bridge._workspace, bridge._sync
original_tracking = bridge._tracking


def controlled(method, original, params):
    if hold["method"] == method:
        hold["entered"].set()
        if not hold["release"].wait(15):
            raise TimeoutError("test scheduling barrier deadline")
    return original(params)


bridge._workspace = lambda params: controlled("workspace", original_workspace, params)
bridge._sync = lambda params: controlled("sync", original_sync, params)
bridge._tracking = lambda params: controlled("set_tracking", original_tracking, params)


def process(packet):
    try:
        operation = packet.get("control")
        if operation == "setup":
            result = {"html": document}
        elif operation == "hold":
            hold["method"] = packet["method"]
            hold["entered"].clear()
            hold["release"].clear()
            result = {"configured": True}
        elif operation == "entered":
            result = {"entered": hold["entered"].is_set()}
        elif operation == "release":
            hold["method"] = None
            hold["release"].set()
            result = {"released": True}
        elif operation == "database":
            store = Store(root)
            try:
                result = {
                    "tasks": store.cached(),
                    "local": [dict(row) for row in store.db.execute("SELECT * FROM local_tracking")],
                    "history": [
                        dict(row) for row in store.db.execute("SELECT * FROM local_tracking_history")
                    ],
                    "calls": list(calls),
                }
            finally:
                store.close()
        elif operation in ("fail_writes", "allow_writes"):
            with sqlite3.connect(root / "state.sqlite") as db:
                db.execute(
                    "CREATE TRIGGER fail_local BEFORE INSERT ON local_tracking BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
                    if operation == "fail_writes"
                    else "DROP TRIGGER fail_local"
                )
            result = {"configured": True}
        elif operation == "restart":
            # No in-memory store/connection survives; child request workers always make their own Store.
            result = Bridge(root, qa=True).invoke("get_state", {})
        else:
            method, params = packet["method"], packet.get("params", {})
            with mutex:
                calls.append(method)
            result = bridge.invoke(method, params)
        response = {"id": packet["id"], "result": result}
    except Exception as error:
        response = {"id": packet["id"], "host_error": type(error).__name__}
    with mutex:
        print(json.dumps(response, ensure_ascii=False), flush=True)


with ThreadPoolExecutor(max_workers=12) as executor:
    for line in sys.stdin:
        executor.submit(process, json.loads(line))
hold["release"].set()
