"""Bounded packaged process observation. Logs only own process-tree metadata, never arguments."""

import ctypes
import hashlib
import json
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import UTC, datetime, timedelta
from pathlib import Path

from canvas_agent import schedule
from canvas_agent.config import DEFAULTS, save


class Entry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("pid", wintypes.DWORD),
        ("heap", ctypes.c_size_t),
        ("module", wintypes.DWORD),
        ("threads", wintypes.DWORD),
        ("parent", wintypes.DWORD),
        ("priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
        ("image", wintypes.WCHAR * 260),
    ]


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]


def is_our_exe(pid):
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        return bool(
            kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length))
            and Path(buffer.value) == exe
        )
    finally:
        kernel.CloseHandle(handle)


def snapshot():
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    rows = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            rows[entry.pid] = (entry.parent, entry.image)
            ok = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    return rows


exe, root = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
root.mkdir(parents=True, exist_ok=False)
gui, data = root / "gui", root / "scheduled"
gui.mkdir()
data.mkdir()
save(data / "config.json", DEFAULTS | {"monitoring": False})
report = {
    "started_utc": datetime.now(UTC).isoformat(),
    "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
    "sampling_ms": 20,
    "command_lines_collected": False,
    "process_events": [],
    "limitation": "20ms sampling can miss short-lived children. This is not Behavior Shield clearance.",
    "background_scope": "Real frozen gates with monitoring disabled; live account and provider calls not attempted.",
}
tracked, seen, stop = set(), set(snapshot()), threading.Event()


def monitor():
    while not stop.is_set():
        rows = snapshot()
        for pid, (parent, name) in rows.items():
            if pid not in seen and (
                parent in tracked or name.casefold() == exe.name.casefold() and is_our_exe(pid)
            ):
                tracked.add(pid)
                report["process_events"].append(
                    {
                        "at_utc": datetime.now(UTC).isoformat(),
                        "pid": pid,
                        "parent_pid": parent,
                        "image": name,
                        "parent_image": rows.get(parent, (0, "unavailable"))[1],
                    }
                )
        seen.update(rows)
        stop.wait(0.02)


worker = threading.Thread(target=monitor)
worker.start()


def launch(arguments):
    process = subprocess.Popen([str(exe), *arguments])  # noqa: S603 - explicit built artifact, fixed args
    tracked.add(process.pid)
    return process.wait(timeout=35)


try:
    report["gui_exit"] = launch(["--smoke-test", "--trace-native", "--data-dir", str(gui)])
    report["gui_smoke"] = json.loads((gui / "gui-smoke.json").read_text(encoding="utf-8"))
    if not report["gui_smoke"].get("save_all_button_visible"):
        raise RuntimeError("packaged_save_button_not_visible")
    report["notification_exit"] = launch(["--test-notification", "--trace-native", "--data-dir", str(gui)])
    report["notification"] = json.loads((gui / "notification-test.json").read_text(encoding="utf-8"))
    audit = gui / "process-launch-audit.jsonl"
    report["python_launch_calls"] = (
        [json.loads(line) for line in audit.read_text().splitlines()] if audit.exists() else []
    )
    schedule.action_command = lambda: (str(exe), "--scheduled")
    schedule.install_task(data)
    report["task_created"] = schedule.task_info(data)
    schedule.install_task(data)
    future = datetime.now(UTC) + timedelta(hours=3)
    schedule.install_deadline_task(data, [future.isoformat()])
    for suffix in ("", "-Deadlines"):
        with schedule.scheduler_connection() as connection:
            task = connection[1].GetTask(schedule.task_name(data) + suffix)
            task.Run(None)
            task = None
        time.sleep(5)
        with schedule.scheduler_connection() as connection:
            task = connection[1].GetTask(schedule.task_name(data) + suffix)
            report["background" + suffix] = {
                "last_result": int(task.LastTaskResult),
                "state": int(task.State),
            }
            task = None
finally:
    try:
        schedule.remove_all_tasks(data)
        report["daily_removed"] = not schedule.task_info(data)["exists"]
    finally:
        stop.set()
        worker.join()
        blocked = {"powershell.exe", "pwsh.exe", "cmd.exe", "schtasks.exe", "whoami.exe"}
        report["observed_command_children"] = [
            e for e in report["process_events"] if e["image"].casefold() in blocked
        ]
        report["completed_utc"] = datetime.now(UTC).isoformat()
        (root / "packaged-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
