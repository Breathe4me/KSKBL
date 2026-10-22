"""Execute only the new candidate's no-window DPAPI selfcheck in a fresh Unicode synthetic path."""

import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path

from check_frozen_backend import sha

from canvas_agent.config import DEFAULTS
from canvas_agent.security import Secrets, ai_key


def verify(candidate):
    candidate = Path(candidate).resolve()
    if not candidate.is_relative_to(Path(__file__).resolve().parents[1] / "qa-export"):
        raise ValueError("Expected isolated QA candidate")
    target = candidate / "FROZEN_CREDENTIAL_CHECK.json"
    if target.exists():
        raise FileExistsError("Never replace an existing check")
    exe = candidate / "portable/CanvasDeadlineAgent-UI-QA/CanvasDeadlineAgent-UI-QA.exe"
    run = candidate / "credential-check-runs" / ("凭据合成-" + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    data = run / "独立数据"
    process = subprocess.run(  # noqa: S603 - exact candidate; explicit no-window synthetic-only selfcheck
        [str(exe), "--credential-check", "--data-dir", str(data)],
        cwd=run,
        env=dict(os.environ, LOCALAPPDATA=str(run / "unused-localappdata")),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    path = data / "credential-check-result.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    # The frozen process has exited. This separate Python process decrypts only its fabricated keys.
    vault = Secrets(data / "synthetic-production-services")
    readback = (
        (
            ai_key(vault, DEFAULTS) == "SYNTHETIC-DEEPSEEK-BOUND"
            and vault.get("ai") == "SYNTHETIC-OPENAI-BOUND"
        )
        if result.get("status") == "passed"
        else False
    )
    passed = (
        process.returncode == 0
        and result.get("status") == "passed"
        and result.get("frozen") is True
        and result.get("gui_started") is False
        and result.get("external_clients_created") == 0
        and not result.get("forbidden_gui_imports")
        and len(result.get("cases", [])) == 5
        and all(case["passed"] for case in result["cases"])
        and readback
    )
    record = {
        "status": "passed" if passed else "failed",
        "exe_sha256": sha(exe),
        "result": result,
        "create_no_window": True,
        "exit_code": process.returncode,
        "unicode_path": True,
        "DPAPI_readback_after_frozen_process_exit": readback,
    }
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
    if not passed:
        raise ValueError("Frozen credential check failed; do not generate ISO")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    print(json.dumps(verify(parser.parse_args().candidate), indent=2))
