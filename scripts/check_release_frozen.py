"""Execute only no-window production RC diagnostic/disabled CLI paths in new isolated directories."""

import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path

from build_manifest import file_hash


def verify(candidate=None):
    project = Path(__file__).resolve().parents[1]
    candidate = Path(candidate).resolve() if candidate else project / "release-prep/v1.2.0-beta.1"
    if not candidate.is_relative_to(project / "release-prep"):
        raise ValueError("Frozen verification must use an isolated release-prep directory")
    target = candidate / "evidence/FROZEN_RELEASE_CHECK.json"
    if target.exists():
        raise FileExistsError("Do not overwrite a frozen verification")
    exe = candidate / "payload/CanvasDeadlineAgent/CanvasDeadlineAgent.exe"
    work = candidate / "evidence/frozen-startup" / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=False)
    profile = work / "中文隔离数据"
    env = dict(os.environ, LOCALAPPDATA=str(work / "unused-real-profile"))
    rows = []

    def run(arguments, expected):
        process = subprocess.run(  # noqa: S603 - exact newly built RC, explicit no-window checked arguments
            [str(exe), *arguments],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=50,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        rows.append(
            {
                "arguments": arguments,
                "exit_code": process.returncode,
                "expected": expected,
                "passed": process.returncode == expected,
                "stdout_empty": not process.stdout,
                "stderr_empty": not process.stderr,
            }
        )
        if process.returncode != expected:
            raise ValueError("Frozen release diagnostic failed; do not archive/build installer")

    run(["--release-selfcheck", "startup", "--data-dir", str(profile)], 0)
    result = json.loads((profile / "release-check-result.json").read_text(encoding="utf-8"))
    if not (
        result["status"] == "passed"
        and result["frozen"]
        and result["production_default"]
        and result["version"] == "1.2.0-beta.1"
        and not result["gui_started"]
        and not result["forbidden_gui_imports"]
    ):
        raise ValueError("Release startup state invalid")
    run(["--release-selfcheck", "readback", "--data-dir", str(profile)], 0)
    restart = json.loads((profile / "release-restart-check.json").read_text(encoding="utf-8"))
    if (
        restart["status"] != "passed"
        or not restart["frozen"]
        or not restart["DPAPI_cross_process_persistence"]
    ):
        raise ValueError("Frozen cross-process persistence failed")
    run(["--mock"], 2)
    run(["--qa"], 2)
    run(["--scheduled", "--data-dir", str(profile)], 0)
    run(["--guardian", "--data-dir", str(profile)], 0)
    run(["--check", "--data-dir", str(profile)], 2)  # no Canvas URL; no real network request
    record = {
        "status": "passed",
        "exe_sha256": file_hash(exe),
        "create_no_window": True,
        "production_first_run": result,
        "second_frozen_process": restart,
        "commands": rows,
        "no_real_profile_access": True,
        "no_real_external_services_or_task_registration": True,
    }
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "commands": len(rows), "exe_sha256": record["exe_sha256"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path)
    verify(parser.parse_args().candidate)
