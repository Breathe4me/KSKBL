"""Real COM smoke, isolated synthetic data. Never changes protection or production tasks."""

import ctypes
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from canvas_agent.config import DEFAULTS, save
from canvas_agent.schedule import (
    install_deadline_task,
    install_task,
    remove_all_tasks,
    scheduler_connection,
    task_info,
    task_name,
)

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=False)
save(root / "config.json", DEFAULTS | {"monitoring": False})
result = {"administrator_token": bool(ctypes.windll.shell32.IsUserAnAdmin()), "status": "Pending"}
try:
    install_task(root)
    result["daily_task"] = task_info(root)
    future = datetime.now(UTC) + timedelta(hours=3)
    install_deadline_task(root, [future.isoformat(), (future + timedelta(minutes=45)).isoformat()])
    install_deadline_task(root, [(future + timedelta(minutes=5)).isoformat()])
    with scheduler_connection() as connection:
        task = connection[1].GetTask(task_name(root) + "-Deadlines")
        definition = task.Definition
        result["deadline_task"] = {
            "run_level": int(definition.Principal.RunLevel),
            "logon_type": int(definition.Principal.LogonType),
            "triggers_after_update": int(definition.Triggers.Count),
            "guardian_action": "--guardian" in definition.Actions.Item(1).Arguments,
        }
        definition = None
        task.Run(None)
        task = None
    time.sleep(5)
    with scheduler_connection() as connection:
        task = connection[1].GetTask(task_name(root) + "-Deadlines")
        result["deadline_execution"] = {"state": int(task.State), "last_result": int(task.LastTaskResult)}
        task = None
    result["status"] = "Tested" if result["deadline_execution"]["last_result"] == 0 else "Pending"
except Exception as error:
    result.update(status="Pending", code=getattr(error, "code", type(error).__name__))
finally:
    try:
        remove_all_tasks(root)
        result["daily_removed"] = not task_info(root)["exists"]
        with scheduler_connection() as connection:
            import pythoncom

            try:
                task = connection[1].GetTask(task_name(root) + "-Deadlines")
                result["deadline_removed"] = False
                task = None
            except pythoncom.com_error:
                result["deadline_removed"] = True
    except Exception as error:
        result["cleanup_code"] = getattr(error, "code", type(error).__name__)
    (root / "native-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
