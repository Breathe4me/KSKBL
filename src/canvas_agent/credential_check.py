"""Actual production Bridge/DPAPI with fabricated keys in NEW directories only; no GUI/network."""

import json
import sys
from pathlib import Path

from .config import DEFAULTS, save
from .security import Secrets, ai_key
from .web_bridge import Bridge
from .web_qa import prepare_qa_root


def check(root):
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        return {"status": "failed", "code": "fresh_synthetic_directory_required", "gui_started": False}
    root.mkdir(parents=True, exist_ok=True)
    live = root / "synthetic-production-services"
    live.mkdir()
    save(live / "config.json", DEFAULTS)
    (live / "QA_ONLY.json").write_text(json.dumps({"mode": "synthetic_only", "schema": 1}), encoding="utf-8")
    calls, cases = [], []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Selfcheck must not create external clients")

    bridge = Bridge(live, qa=False, api_factory=forbidden)
    result = {
        "status": "failed",
        "frozen": bool(getattr(sys, "frozen", False)),
        "gui_started": False,
        "data_mode": "fresh_synthetic_selftest_only",
        "cases": cases,
    }
    try:
        for kind in ("canvas", "pushplus", "ai"):
            for suffix in ("A", "B"):
                key = "SYNTHETIC-SELFTEST-" + kind + suffix
                response = bridge.invoke("save_credential", {"kind": kind, "value": key})
                if not response["ok"] or Secrets(live).get(kind) != key:
                    raise RuntimeError("credential_write_check_failed")
                state = Bridge(live, qa=False).invoke("get_state", {})
                if (
                    not state["ok"]
                    or state["data"]["credentials"][kind] != "saved"
                    or key in json.dumps(state)
                ):
                    raise RuntimeError("credential_restart_or_redaction_failed")
                if any(key.encode() in file.read_bytes() for file in live.glob("*.dpapi")):
                    raise RuntimeError("credential_ciphertext_check_failed")
            if not bridge.invoke("remove_credential", {"kind": kind})["ok"] or Secrets(live).get(kind):
                raise RuntimeError("credential_delete_failed")
            cases.append({"case": kind + "_actual_DPAPI_add_update_restart_delete_redaction", "passed": True})
        vault = Secrets(live)
        vault.set("ai", "SYNTHETIC-DEEPSEEK-BOUND")
        updated = DEFAULTS | {"ai_provider": "OpenAI", "ai_url": "https://api.openai.com/v1"}
        save(live / "config.json", updated)
        if vault.get("ai"):
            raise RuntimeError("provider_key_leak")
        vault.set("ai", "SYNTHETIC-OPENAI-BOUND")
        if (
            ai_key(vault, DEFAULTS) != "SYNTHETIC-DEEPSEEK-BOUND"
            or ai_key(vault, updated) != "SYNTHETIC-OPENAI-BOUND"
        ):
            raise RuntimeError("snapshot_binding_failed")
        cases.append({"case": "provider_and_request_snapshot_isolation", "passed": True})
        qa = prepare_qa_root(root / "synthetic-qa-policy")
        denied = Bridge(qa, qa=True).invoke(
            "save_credential", {"kind": "canvas", "value": "SYNTHETIC-DENIED"}
        )
        if denied != {"ok": False, "error": "qa_credentials_disabled"} or list(qa.glob("*.dpapi")):
            raise RuntimeError("qa_policy_failed")
        cases.append({"case": "QA_explicit_denial_no_persistence", "passed": True})
        result.update(
            status="passed" if not calls else "failed",
            external_clients_created=len(calls),
            forbidden_gui_imports=[
                name
                for name in ("webview.platforms.winforms", "webview.platforms.edgechromium")
                if name in sys.modules
            ],
        )
        if result["forbidden_gui_imports"]:
            result["status"] = "failed"
    except Exception as error:
        result.update(status="failed", exception_type=type(error).__name__)
    (root / "credential-check-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
