"""Run ONLY the packaged --backend-check entry, in fresh isolated synthetic profiles, no GUI."""

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition):
    if not condition:
        raise ValueError("Frozen bootstrap preservation check failed")


def verify(candidate, legacy):
    project = Path(__file__).resolve().parents[1]
    candidate, legacy = Path(candidate).resolve(), Path(legacy).resolve()
    if not candidate.is_relative_to(project / "qa-export"):
        raise ValueError("Candidate must be an isolated qa-export directory")
    program = candidate / "portable/CanvasDeadlineAgent-UI-QA/CanvasDeadlineAgent-UI-QA.exe"
    if not program.is_file() or (candidate / "FROZEN_BACKEND_CHECK.json").exists():
        raise ValueError("Missing executable or an existing check must not be replaced")
    run = candidate / "backend-check-runs" / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    cwd = run / "unrelated-cwd"
    cwd.mkdir()
    appdata = run / "isolated-localappdata"
    appdata.mkdir()
    environment = dict(os.environ, LOCALAPPDATA=str(appdata))
    cases = []

    def execute(name, root, expected=0, reason=None, fields=None):
        process = subprocess.run(  # noqa: S603 - exact isolated QA EXE; explicit no-window diagnostic entry only
            [str(program), "--backend-check", "--data-dir", str(root)],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        result_path = root / "backend-check-result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        passed = (
            process.returncode == expected
            and result.get("frozen") is True
            and result.get("gui_started") is False
            and result.get("ui_ready") is False
            and not result.get("forbidden_gui_imports")
        )
        if expected == 0:
            passed = (
                passed
                and result.get("status") == "passed"
                and result.get("stages") == ["backend_state_ready"]
                and set(result.get("credentials", {}).values()) == {"missing"}
            )
        else:
            passed = (
                passed
                and result.get("status") == "failed"
                and result.get("code") == "configuration_invalid"
                and result.get("reason") == reason
                and result.get("fields") == fields
                and result.get("stages") == []
            )
        cases.append(
            {
                "case": name,
                "passed": bool(passed),
                "exit_code": process.returncode,
                "result": result,
                "stderr_empty": not process.stderr.strip(),
                "create_no_window": True,
                "data_directory": str(root),
            }
        )
        if not passed:
            raise AssertionError("Frozen backend case failed: " + name)
        return result

    proof = {
        "mode": "actual PyInstaller EXE backend; no GUI/CLR renderer; fresh synthetic profiles only",
        "exe": str(program),
        "exe_sha256": sha(program),
        "cases": cases,
        "status": "failed",
    }
    try:
        fresh = run / "first-launch"
        execute("first_launch_missing_directory", fresh)
        (fresh / "canvas.dpapi").write_bytes(b"SYNTHETIC-TRAP-NOT-A-REAL-CREDENTIAL")
        execute("restart_ignores_qa_dpapi", fresh)
        empty = run / "empty-directory"
        empty.mkdir()
        execute("first_launch_empty_directory", empty)
        old = run / "legacy-config"
        execute("legacy_fixture_initialization", old)
        original = legacy.read_bytes()
        (old / "config.json").write_bytes(original)
        execute("legacy_missing_three_fields", old)
        require((old / "config.json").read_bytes() == original)
        require(any(file.read_bytes() == original for file in (old / "config-backups").iterdir()))
        invalid = run / "invalid-recovery"
        execute("invalid_fixture_initialization", invalid)
        valid = (invalid / "config.json").read_bytes()
        data = json.loads(valid)
        data["guardian_minutes"] = True
        (invalid / "config.json").write_text(json.dumps(data), encoding="utf-8")
        malformed = (invalid / "config.json").read_bytes()
        database_before = sha(invalid / "state.sqlite")
        execute("invalid_type_rejected", invalid, 2, "integer_out_of_range", ["guardian_minutes"])
        require(
            (invalid / "config.json").read_bytes() == malformed
            and sha(invalid / "state.sqlite") == database_before
        )
        require(any(file.read_bytes() == malformed for file in (invalid / "config-backups").iterdir()))
        (invalid / "config.json").write_bytes(valid)  # explicit repair ONLY of this disposable test fixture
        execute("explicit_repair_preserves_database", invalid)
        (invalid / "config.json").write_bytes(b'{"schema_version":')
        execute("malformed_json_rejected", invalid, 2, "invalid_json", ["$document"])
        require((invalid / "config.json").read_bytes() == b'{"schema_version":')
        proof["status"] = "passed"
        proof["original_config_preserved"] = True
        proof["invalid_database_preserved"] = True
        proof["backend_only_no_ui_success_claim"] = True
    finally:
        (candidate / "FROZEN_BACKEND_CHECK.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--legacy-config", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.candidate, args.legacy_config)
    print(
        json.dumps(
            {"status": result["status"], "cases": len(result["cases"]), "exe_sha256": result["exe_sha256"]}
        )
    )
