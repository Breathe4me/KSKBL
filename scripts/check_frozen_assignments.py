"""Actual new QA EXE, explicit no-window mutation check in a fresh synthetic fixture."""

import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path

from check_frozen_backend import sha

from canvas_agent.storage import Store


def verify(candidate):
    candidate = Path(candidate).resolve()
    project = Path(__file__).resolve().parents[1]
    if not candidate.is_relative_to(project / "qa-export"):
        raise ValueError("Expected isolated QA candidate")
    proof_path = candidate / "FROZEN_ASSIGNMENT_CHECK.json"
    if proof_path.exists():
        raise FileExistsError("Refusing to replace existing proof")
    program = candidate / "portable/CanvasDeadlineAgent-UI-QA/CanvasDeadlineAgent-UI-QA.exe"
    run = candidate / "assignment-check-runs" / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    root = run / "synthetic-only"
    process = subprocess.run(  # noqa: S603 - exact QA executable, no-window diagnostic, new synthetic directory only
        [str(program), "--assignment-check", "--data-dir", str(root)],
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
    result_path = root / "assignment-check-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    passed = (
        process.returncode == 0
        and result.get("status") == "passed"
        and result.get("frozen") is True
        and result.get("gui_started") is False
        and result.get("ui_ready") is False
        and not result.get("forbidden_gui_imports")
        and len(result.get("assignment_cases", [])) == 3
        and all(case["passed"] for case in result["assignment_cases"])
    )
    restart = subprocess.run(  # noqa: S603 - same reviewed EXE; same isolated synthetic fixture; no GUI
        [str(program), "--backend-check", "--data-dir", str(root)],
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
    restarted_path = root / "backend-check-result.json"
    restarted = json.loads(restarted_path.read_text(encoding="utf-8")) if restarted_path.exists() else {}
    store = Store(root)
    try:
        row = store.db.execute("SELECT state FROM local_tracking WHERE task_key='1:assignment:1'").fetchone()
        persisted = row is not None and row[0] == "completed"
        canvas_unchanged = (
            next(t for t in store.cached() if t["key"] == "1:assignment:1")["status"]
            == "Confirmed Not Submitted"
        )
    finally:
        store.close()
    restart_passed = (
        restart.returncode == 0
        and restarted.get("status") == "passed"
        and restarted.get("frozen") is True
        and restarted.get("gui_started") is False
        and persisted
        and canvas_unchanged
    )
    passed = passed and restart_passed
    proof = {
        "status": "passed" if passed else "failed",
        "exe_sha256": sha(program),
        "exit_code": process.returncode,
        "create_no_window": True,
        "result": result,
        "stderr_empty": not process.stderr.strip(),
        "separate_process_restart": {
            "passed": restart_passed,
            "result": restarted,
            "sqlite_completed_after_restart": persisted,
            "canvas_unchanged": canvas_unchanged,
        },
    }
    proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    if not passed:
        raise ValueError("Frozen actual assignment mutation gate failed; do not create ISO")
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    proof = verify(parser.parse_args().candidate)
    print(json.dumps(proof, indent=2))
