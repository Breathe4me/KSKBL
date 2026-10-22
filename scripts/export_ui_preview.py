"""Export the current production frontend with an explicitly labeled browser mock transport."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from canvas_agent.storage import Store
from canvas_agent.web_bridge import Bridge
from canvas_agent.web_qa import seed
from canvas_agent.web_shell import html_document

PROJECT = Path(__file__).resolve().parents[1]


class NoCredentials:
    def __init__(self, root):
        pass

    def get(self, kind):
        return ""


def export(output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Refusing to replace an existing UI preview")
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = output.parent / "synthetic-source-profile"
    seed(profile)  # fresh, separate synthetic data only; never reads a real profile
    store = Store(profile)
    try:
        tasks = store.cached()
        store.set(
            "verification_history",
            [
                {
                    "key": tasks[2]["key"],
                    "checked": tasks[2]["checked"],
                    "status": tasks[2]["status"],
                    "attempt": 1,
                    "error": "Synthetic fixture only",
                },
            ],
        )
    finally:
        store.close()
    bridge = Bridge(profile, qa=True, secrets_factory=NoCredentials)
    state = bridge.invoke("get_state", {})["data"]
    fixture = {
        "state": state,
        "contexts": {},
        "prompts": {},
        "announcements": bridge.invoke("announcements", {})["data"],
    }
    for task in state["tasks"]:
        args = {"key": task["key"], "account_scope": state["account_scope"]}
        fixture["contexts"][task["key"]] = bridge.invoke("assignment_context", args)["data"]
        fixture["prompts"][task["key"]] = bridge.invoke("generate_prompt", args)["data"]["text"]
    document = html_document()
    nonce = re.search(r'<script nonce="([^"]+)"', document).group(1)
    adapter = (PROJECT / "scripts/qa_mock_adapter.js").read_text(encoding="utf-8")
    encoded = json.dumps(fixture, ensure_ascii=False).replace("<", "\\u003c")
    adapter = adapter.replace("__QA_FIXTURE__", encoded)
    if "</script" in adapter.lower():
        raise ValueError("Invalid mock adapter embedding")
    document = document.replace(
        f'<script nonce="{nonce}">', f'<script nonce="{nonce}">{adapter}</script><script nonce="{nonce}">', 1
    )
    output.write_text(document, encoding="utf-8")
    sources = {}
    for relative in (
        "frontend/index.html",
        "frontend/prototype.css",
        "frontend/app.css",
        "frontend/app.js",
        "frontend/startup.js",
        "scripts/qa_mock_adapter.js",
        "src/canvas_agent/web_shell.py",
        "src/canvas_agent/web_qa.py",
    ):
        sources[relative] = hashlib.sha256((PROJECT / relative).read_bytes()).hexdigest()
    record = {
        "preview": str(output.resolve()),
        "mode": "browser_mock_adapter",
        "real_frontend_sources": sources,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "credentials": "none",
        "external_calls": "disabled",
        "persistence": "memory_only",
    }
    (output.parent / "UI_PREVIEW_PROVENANCE.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (output.parent / "BOOTSTRAP_STATE.json").write_text(json.dumps(state), encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(export(parser.parse_args().output), indent=2))
