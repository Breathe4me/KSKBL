"""Real installed pywebview decoder AND js_bridge_call worker; no CLR/native windows."""

import json
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_message_protocol import installed_decoder, message  # noqa: E402
from webview.util import js_bridge_call  # noqa: E402

from canvas_agent.config import DEFAULTS, save  # noqa: E402
from canvas_agent.startup_diagnostics import StartupDiagnostics  # noqa: E402
from canvas_agent.storage import Store  # noqa: E402
from canvas_agent.web_bridge import Bridge  # noqa: E402
from canvas_agent.web_qa import prepare_qa_root  # noqa: E402
from canvas_agent.web_shell import html_document  # noqa: E402
from canvas_agent.webview_native import ordered_initial_navigation  # noqa: E402

live_test = len(sys.argv) > 2 and sys.argv[2] == "synthetic-live"
root = Path(sys.argv[1])
if live_test:
    root.mkdir(parents=True, exist_ok=False)
    save(root / "config.json", DEFAULTS)
    (root / "QA_ONLY.json").write_text(json.dumps({"mode": "synthetic_only", "schema": 1}), encoding="utf-8")
else:
    root = prepare_qa_root(root)
diag = StartupDiagnostics(root, operations_enabled=True)


def forbidden_client(*args, **kwargs):
    raise AssertionError("External clients forbidden in frontend audit tests")


bridge = Bridge(root, qa=not live_test, api_factory=forbidden_client)
bridge._diagnostics = diag
output_lock = threading.Lock()
release, entered = threading.Event(), threading.Event()
sync = bridge._sync


def controlled_sync(params):
    entered.set()
    if not release.wait(20):
        raise TimeoutError("test barrier deadline")
    return sync(params)


bridge._sync = controlled_sync


def emit(packet):
    with output_lock:
        print(json.dumps(packet, ensure_ascii=False), flush=True)


errors = []
base = installed_decoder(errors, [])
base.on_script_notify.__globals__["js_bridge_call"] = js_bridge_call
window = SimpleNamespace(
    _js_api=bridge, _functions={}, evaluate_js=lambda script: emit({"evaluate_js": script})
)
backend = SimpleNamespace(EdgeChrome=base)
ordered_initial_navigation(window, diag, root, backend=backend)
decoder = backend.EdgeChrome()
decoder.pywebview_window = window
document = html_document(diag)
for line in sys.stdin:
    request = json.loads(line)
    control = request.get("control")
    if control == "setup":
        result = {"html": document, "run_id": diag.run_id}
    elif control == "hold_sync":
        release.clear()
        entered.clear()
        worker = threading.Thread(target=lambda: bridge.invoke("sync", {}))
        worker.start()
        result = {"entered": entered.wait(5)}
    elif control == "release":
        release.set()
        if "worker" in globals():
            worker.join(5)
        result = {"released": True}
    elif control in ("fail_sql", "allow_sql"):
        with sqlite3.connect(root / "state.sqlite") as db:
            db.execute(
                "CREATE TRIGGER fail_local BEFORE INSERT ON local_tracking BEGIN SELECT RAISE(ABORT,'fixture'); END"
                if control == "fail_sql"
                else "DROP TRIGGER fail_local"
            )
        result = {"configured": True}
    elif control == "snapshot":
        file = diag.directory / "operations.jsonl"
        store = Store(root)
        try:
            result = {
                "records": [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
                if file.exists()
                else [],
                "local": [dict(row) for row in store.db.execute("SELECT task_key,state FROM local_tracking")],
                "errors": errors,
                "identity": json.loads((diag.directory / "build-identity.json").read_text(encoding="utf-8")),
                "credential_files": [path.name for path in root.glob("*.dpapi")],
            }
        finally:
            store.close()
    else:
        decoder.on_script_notify(None, message(request["packet"]))
        result = None
    emit({"id": request["id"], "result": result})
release.set()
