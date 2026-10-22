"""Opt-in, redacted Python process-launch evidence; no command arguments are recorded."""

import json
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

EVENTS = {"subprocess.Popen", "os.system", "os.spawn", "os.posix_spawn", "os.exec"}


def record_event(destination, event, args):
    if event not in EVENTS:
        return
    image = "unavailable"
    if event == "subprocess.Popen" and args and args[0]:
        image = Path(str(args[0])).name
    value = {
        "at_utc": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "event": event,
        "image": image,
        "arguments_recorded": False,
        "stack": [
            {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
            for f in traceback.extract_stack(limit=16)[:-1]
        ],
    }
    try:
        with destination.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value) + "\n")
    except OSError:
        pass  # diagnostic I/O cannot break monitoring


def enable(root):
    destination = root / "process-launch-audit.jsonl"
    sys.addaudithook(lambda event, args: record_event(destination, event, args))
