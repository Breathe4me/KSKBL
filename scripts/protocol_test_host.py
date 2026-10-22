"""Test-only actual pywebview decoder + actual QA Bridge, no CLR, GUI or network."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_message_protocol import installed_decoder, message  # noqa: E402

from canvas_agent.config import DEFAULTS  # noqa: E402
from canvas_agent.startup_diagnostics import StartupDiagnostics  # noqa: E402
from canvas_agent.web_bridge import Bridge  # noqa: E402
from canvas_agent.web_qa import prepare_qa_root  # noqa: E402
from canvas_agent.web_shell import html_document  # noqa: E402
from canvas_agent.webview_native import ordered_initial_navigation  # noqa: E402

root = Path(sys.argv[1])
prepare_qa_root(root)
legacy = {
    key: value
    for key, value in DEFAULTS.items()
    if key not in ("sync_interval_minutes", "guardian_repeat_enabled", "guardian_24h_enabled")
}
if sys.argv[2] == "invalid":
    legacy["guardian_minutes"] = True
(root / "config.json").write_text(json.dumps(legacy), encoding="utf-8")
prepare_qa_root(root)  # exact GUI backup-before-validation helper
diag = StartupDiagnostics(root)
bridge = Bridge(root, qa=True)
bridge._diagnostics = diag
errors, business = [], []
base = installed_decoder(errors, business)


def invoke(window, name, params, uid):
    business.append({"name": name, "id": uid, "value": bridge.invoke(*params)})


base.on_script_notify.__globals__["js_bridge_call"] = invoke
backend = SimpleNamespace(EdgeChrome=base)
window = SimpleNamespace()
ordered_initial_navigation(window, diag, root, backend=backend)
decoder = backend.EdgeChrome()
decoder.pywebview_window = window
for line in sys.stdin:
    packet = json.loads(line)
    if packet == "setup":
        result = {"html": html_document(diag)}
    elif packet == "snapshot":
        result = {
            "stages": sorted(diag.flags),
            "status": diag.status,
            "errors": errors,
            "diagnostics": str(diag.directory),
        }
    else:
        before = len(business)
        decoder.on_script_notify(None, message(packet))
        result = business[-1] if len(business) > before else None
    print(json.dumps(result, ensure_ascii=False), flush=True)
