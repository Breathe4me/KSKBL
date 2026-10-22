"""Task Scheduler wakes a cheap local gate every minute; only configured slots sync."""

import hashlib
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from defusedxml.ElementTree import fromstring

from .models import timestamp
from .windows_native import WindowsAPIError, apartment, com_hresult


def active_times(config, day):
    in_range = bool(config["exam_start"] and config["exam_start"] <= day.isoformat() <= config["exam_end"])
    return config["exam_times"] if config["mode"] == "exam" or in_range else config["normal_times"]


def local_slot(day, hm, zone):
    naive = datetime.fromisoformat(f"{day.isoformat()}T{hm}:00")
    aware = naive.replace(tzinfo=zone, fold=0)
    # Spring gap -> move forward through the gap. Fall fold -> first occurrence only.
    return aware.astimezone(UTC)


def slots(config, now, days_back=2, days_forward=8):
    zone = ZoneInfo(config["timezone"])
    today = now.astimezone(zone).date()
    result = []
    for offset in range(-days_back, days_forward + 1):
        day = today + timedelta(days=offset)
        for hm in active_times(config, day):
            result.append((local_slot(day, hm, zone), "daily"))
        if config["weekly_enabled"] and day.weekday() == config["weekly_day"]:
            result.append((local_slot(day, config["weekly_time"], zone), "weekly"))
    return sorted(set(result))


def next_slot(config, now):
    return min((x[0] for x in slots(config, now) if x[0] > now), default=None)


def due_work(config, store, now):
    effective_from = timestamp(store.get("schedule_effective_from"))
    recent = [(t, k) for t, k in slots(config, now, days_back=8) if now - timedelta(hours=36) <= t <= now]
    # Weekly catchup spans the current week, but never replays older weeks.
    local = now.astimezone(ZoneInfo(config["timezone"]))
    week = f"{local.isocalendar().year}-W{local.isocalendar().week:02d}"
    weekly = config["weekly_enabled"] and any(
        k == "weekly"
        and t <= now
        and (not effective_from or t >= effective_from)
        and t.astimezone(ZoneInfo(config["timezone"])).isocalendar()[:2] == local.isocalendar()[:2]
        for t, k in slots(config, now, days_back=7)
    )
    weekly = weekly and store.get("weekly_done") != week
    last = timestamp(store.get("last_slot"))
    daily = max((t for t, k in recent if k == "daily" and (not last or t > last)), default=None)
    last_attempt = timestamp(store.get("last_attempt"))
    retry = store.get("needs_retry", False)
    interval = config.get("sync_interval_minutes", 0)
    periodic = interval > 0 and (not last_attempt or now - last_attempt >= timedelta(minutes=interval))
    if (daily or weekly or retry) and last_attempt and now - last_attempt < timedelta(minutes=15):
        return None
    if not daily and not weekly and not retry and not periodic:
        return None
    slot_id = (
        daily.isoformat()
        if daily
        else (
            f"interval:{int(now.timestamp()) // (interval * 60)}"
            if periodic
            else store.get("retry_slot") or f"weekly:{week}"
        )
    )
    return {"run_id": f"scheduled:{slot_id}", "slot": daily, "week": week if weekly else None}


def rebase_timezone(config, store, now):
    """Apply a timezone change to future slots without replaying earlier wall-clock slots."""
    latest = max((t for t, kind in slots(config, now) if kind == "daily" and t <= now), default=None)
    store.set("last_slot", latest.isoformat() if latest else None)
    store.set("schedule_effective_from", now.isoformat())
    store.set("needs_retry", False)
    store.set("retry_slot", None)


def task_name(root):
    # Own namespace + current user's data path. Never enumerate/delete unrelated tasks.
    digest = hashlib.sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()[:16]
    return f"CanvasDeadlineAgent-{digest}"


def action_command():
    if getattr(sys, "frozen", False):
        return sys.executable, "--scheduled"
    entry = Path(__file__).resolve().parents[2] / "scripts" / "entry.py"
    return sys.executable, subprocess.list2cmdline([str(entry), "--scheduled"])


def task_xml(root, user, executable=None, arguments=None):
    exe, args = action_command()
    exe, args = executable or exe, arguments if arguments is not None else args
    args += " " + subprocess.list2cmdline(["--data-dir", str(Path(root).resolve())])
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)

    def node(parent, tag, value=None, **attrs):
        el = ET.SubElement(parent, f"{{{ns}}}{tag}", attrs)
        if value is not None:
            el.text = str(value)
        return el

    task = ET.Element(f"{{{ns}}}Task", {"version": "1.2"})
    registration = node(task, "RegistrationInfo")
    node(registration, "Description", "Canvas Deadline Agent per-user monitoring; data in LOCALAPPDATA")
    triggers = node(task, "Triggers")
    time_trigger = node(triggers, "TimeTrigger")
    repeat = node(time_trigger, "Repetition")
    node(repeat, "Interval", "PT1M")
    node(repeat, "StopAtDurationEnd", "false")
    node(
        time_trigger,
        "StartBoundary",
        (datetime.now().replace(microsecond=0) + timedelta(minutes=1)).isoformat(),
    )
    node(time_trigger, "Enabled", "true")
    logon = node(triggers, "LogonTrigger")
    node(logon, "Enabled", "true")
    node(logon, "UserId", user)
    principals = node(task, "Principals")
    principal = node(principals, "Principal", id="User")
    node(principal, "UserId", user)
    node(principal, "LogonType", "InteractiveToken")
    node(principal, "RunLevel", "LeastPrivilege")
    settings = node(task, "Settings")
    node(
        settings, "MultipleInstancesPolicy", "Parallel"
    )  # ProcessLock coalesces core work; AI cannot block minute wakes.
    node(settings, "DisallowStartIfOnBatteries", "false")
    node(settings, "StopIfGoingOnBatteries", "false")
    node(settings, "StartWhenAvailable", "true")
    node(settings, "RunOnlyIfNetworkAvailable", "false")
    node(settings, "ExecutionTimeLimit", "PT30M")
    actions = node(task, "Actions", Context="User")
    action = node(actions, "Exec")
    node(action, "Command", exe)
    node(action, "Arguments", args)
    node(action, "WorkingDirectory", str(Path(exe).parent))
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


@contextmanager
def scheduler_connection():
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler required")
    import pythoncom
    from win32com.client.dynamic import Dispatch

    error = None
    with apartment():
        service = folder = None
        connection = []
        try:
            # Dynamic dispatch avoids makepy/gencache code generation and its disk writes.
            service = Dispatch("Schedule.Service")
            service.Connect()  # local host, current Windows user, no password/elevation
            folder = service.GetFolder("\\")
            connection = [service, folder]
            yield connection
        except pythoncom.com_error as e:
            error = WindowsAPIError("task_scheduler_failed", com_hresult(e))
        finally:
            connection.clear()
            folder = service = None  # release before CoUninitialize on this thread
    if error is not None:
        raise error from None


def current_user_sid():
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(sid)
    finally:
        token.Close()


def install_task(root):
    with scheduler_connection() as connection:
        user = current_user_sid()
        definition = connection[0].NewTask(0)
        definition.XmlText = task_xml(root, user).decode("utf-16")
        try:
            # TASK_CREATE_OR_UPDATE=6; TASK_LOGON_INTERACTIVE_TOKEN=3; no password.
            connection[1].RegisterTaskDefinition(task_name(root), definition, 6, user, None, 3)
        finally:
            definition = None


def _get_task(folder, root):
    import pythoncom

    try:
        return folder.GetTask(task_name(root))
    except pythoncom.com_error as e:
        if com_hresult(e) == 0x80070002:
            return None
        raise


def task_info(root):
    """Query only this app's task, without exporting user IDs, paths or arguments."""
    with scheduler_connection() as connection:
        task = _get_task(connection[1], root)
        if task is None:
            return {"exists": False}
        try:
            return {
                "exists": True,
                "state": int(task.State),
                "last_result": int(task.LastTaskResult),
                "run_level": int(task.Definition.Principal.RunLevel),
                "logon_type": int(task.Definition.Principal.LogonType),
            }
        finally:
            task = None


def remove_task(root):
    if os.name != "nt":
        return
    with scheduler_connection() as connection:
        task = _get_task(connection[1], root)
        if task is not None:
            task = None
            connection[1].DeleteTask(task_name(root), 0)


def remove_all_tasks(root):
    remove_task(root)
    remove_deadline_task(root)


def deadline_xml(root, user, times):
    """A separate per-user task, with coalesced UTC one-shot triggers and logon catch-up."""
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    xml = fromstring(task_xml(root, user))
    triggers = xml.find("t:Triggers", ns)
    for trigger in list(triggers):
        if trigger.tag.endswith("TimeTrigger"):
            triggers.remove(trigger)
    for value in sorted(set(times))[:40]:
        trigger = ET.SubElement(triggers, "{" + ns["t"] + "}TimeTrigger")
        ET.SubElement(trigger, "{" + ns["t"] + "}StartBoundary").text = timestamp(value).isoformat()
        ET.SubElement(trigger, "{" + ns["t"] + "}Enabled").text = "true"
    args = xml.find("t:Actions/t:Exec/t:Arguments", ns)
    args.text = args.text.replace("--scheduled", "--guardian", 1)
    return ET.tostring(xml, encoding="utf-16", xml_declaration=True)


def install_deadline_task(root, times):
    with scheduler_connection() as connection:
        user = current_user_sid()
        definition = connection[0].NewTask(0)
        try:
            definition.XmlText = deadline_xml(root, user, times).decode("utf-16")
            connection[1].RegisterTaskDefinition(task_name(root) + "-Deadlines", definition, 6, user, None, 3)
        finally:
            definition = None


def deadline_task_info(root):
    """Query only our own deadline action; never export its path or arguments."""
    import pythoncom

    with scheduler_connection() as connection:
        try:
            task = connection[1].GetTask(task_name(root) + "-Deadlines")
        except pythoncom.com_error as error:
            if com_hresult(error) == 0x80070002:
                return {"exists": False}
            raise
        try:
            action = task.Definition.Actions.Item(1)
            exe, arguments = action_command()
            expected = arguments.replace("--scheduled", "--guardian", 1)
            expected += " " + subprocess.list2cmdline(["--data-dir", str(Path(root).resolve())])
            return {
                "exists": True,
                "action_matches": (
                    os.path.normcase(action.Path) == os.path.normcase(exe)
                    and action.Arguments == expected
                    and os.path.normcase(action.WorkingDirectory) == os.path.normcase(str(Path(exe).parent))
                    and int(task.Definition.Actions.Count) == 1
                    and int(task.Definition.Principal.RunLevel) == 0
                    and int(task.Definition.Principal.LogonType) == 3
                ),
            }
        finally:
            action = task = None


def remove_deadline_task(root):
    if os.name != "nt":
        return
    import pythoncom

    with scheduler_connection() as connection:
        try:
            connection[1].DeleteTask(task_name(root) + "-Deadlines", 0)
        except pythoncom.com_error as error:
            if com_hresult(error) != 0x80070002:
                raise
