"""Install/reinstall/uninstall the dedicated QA build, never the v1.0 application."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from canvas_agent import schedule
from canvas_agent.config import DEFAULTS, save
from canvas_agent.security import Secrets
from canvas_agent.storage import Store

qa = Path(sys.argv[1]).resolve()
setup = qa / "CanvasDeadlineAgent-v1.1-QA-Setup.exe"
suffix = sys.argv[3] if len(sys.argv) > 3 else ""
program, data = qa / ("installed-v11" + suffix), qa / ("installer-data" + suffix)
if program.exists() or data.exists():
    raise SystemExit("Refusing existing QA directories")
data.mkdir()
save(data / "config.json", DEFAULTS | {"canvas_url": "https://canvas.example", "language": "zh"})
Secrets(data).set("canvas", "synthetic-install-only-credential")
state = Store(data)
state.set("qa_retention_marker", "synthetic")
state.claim("synthetic_reminder", "windows", datetime.now(UTC))
state.receipt("synthetic_reminder", "windows", True, datetime.now(UTC))
state.close()


def hashes():
    return {
        name: hashlib.sha256((data / name).read_bytes()).hexdigest()
        for name in ("config.json", "canvas.dpapi", "state.sqlite")
    }


result = {
    "status": "Pending",
    "scope": "Same frozen payload; QA AppId and explicit QA uninstall data directory.",
}
before = hashes()


def execute(arguments):
    return subprocess.run(arguments, timeout=120, check=False).returncode  # noqa: S603 - fixed local QA artifacts


try:
    result["install_exit"] = execute(
        [
            str(setup),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            "/DIR=" + str(program),
            "/LOG=" + str(qa / "install.log"),
        ]
    )
    exe = program / "CanvasDeadlineAgent.exe"
    source_exe = Path(sys.argv[2]).resolve()
    result["installed_exe_matches_final"] = exe.read_bytes() == source_exe.read_bytes()
    result["upgrade_exit"] = execute(
        [
            str(setup),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            "/DIR=" + str(program),
            "/LOG=" + str(qa / "upgrade.log"),
        ]
    )
    result["data_retained_after_upgrade"] = before == hashes()
    result["installed_gui_exit"] = execute(
        [str(exe), "--smoke-test", "--trace-native", "--data-dir", str(data)]
    )
    result["installed_gui"] = json.loads((data / "gui-smoke.json").read_text(encoding="utf-8"))
    result["installed_save_button_visible"] = result["installed_gui"].get("save_all_button_visible", False)
    schedule.action_command = lambda: (str(exe), "--scheduled")
    schedule.install_task(data)
    schedule.install_deadline_task(data, [(datetime.now(UTC) + timedelta(hours=3)).isoformat()])
    result["task_created_before_uninstall"] = schedule.task_info(data)["exists"]
    result["uninstall_exit"] = execute(
        [
            str(program / "unins000.exe"),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/LOG=" + str(qa / "uninstall.log"),
        ]
    )
    result["program_removed"] = not exe.exists()
    result["daily_task_removed"] = not schedule.task_info(data)["exists"]
    with schedule.scheduler_connection() as connection:
        import pythoncom

        from canvas_agent.windows_native import com_hresult

        try:
            task = connection[1].GetTask(schedule.task_name(data) + "-Deadlines")
            task = None
            result["deadline_task_removed"] = False
        except pythoncom.com_error as error:
            result["deadline_task_removed"] = com_hresult(error) == 0x80070002
    result["config_and_credential_retained_after_uninstall"] = all(
        before[name] == hashes()[name] for name in ("config.json", "canvas.dpapi")
    )
    state = Store(data)
    result["database_and_history_retained"] = (
        state.get("qa_retention_marker") == "synthetic"
        and state.db.execute("SELECT status FROM delivery WHERE key='synthetic_reminder'").fetchone()[0]
        == "sent"
    )
    state.close()
    result["status"] = (
        "Tested"
        if (
            all(
                result[k]
                for k in (
                    "installed_exe_matches_final",
                    "data_retained_after_upgrade",
                    "program_removed",
                    "daily_task_removed",
                    "deadline_task_removed",
                    "config_and_credential_retained_after_uninstall",
                    "database_and_history_retained",
                    "installed_save_button_visible",
                )
            )
            and all(
                result[k] == 0
                for k in ("install_exit", "upgrade_exit", "installed_gui_exit", "uninstall_exit")
            )
        )
        else "Pending"
    )
finally:
    schedule.remove_all_tasks(data)
    (qa / "install-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
