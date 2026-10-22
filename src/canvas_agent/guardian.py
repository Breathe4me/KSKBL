"""Independent deadline gates with live verification and durable per-deadline receipts."""

import hashlib
import json
from datetime import timedelta

from .models import timestamp
from .rules import Message, local_time_label
from .submission import EXCUSED, SUBMITTED, UNKNOWN, verify
from .tracking import Tracking


def tracked_tasks(store):
    """Shared by the scheduler and emergency UI: local exclusions apply before entry."""
    return [task for task in store.cached() if Tracking(store).active(task)]


def rebuild_plan(store, config, now):
    plan = []
    if config["guardian_enabled"] and config["monitoring"]:
        selected = config["course_ids"]
        for task in tracked_tasks(store):
            if selected is not None and task["course_id"] not in selected:
                continue
            if ":assignment:" not in task["key"] or task["status"] in (SUBMITTED, "Graded"):
                continue
            try:
                due = timestamp(task.get("due"))
            except (ValueError, TypeError):
                continue
            if not due or due < now - timedelta(days=config["overdue_days"]):
                continue
            stages = [(config["guardian_minutes"], "first"), (-1, "post_due")]
            if config.get("guardian_repeat_enabled", True):
                stages.append((config["guardian_repeat_minutes"], "repeat"))
            if config.get("guardian_24h_enabled", False) and config["guardian_minutes"] != 1440:
                stages.append((1440, "24h"))
            for minutes, stage in stages:
                at = due - timedelta(minutes=minutes)
                key = f"guardian:{task['key']}:{due.isoformat()}:{stage}"
                plan.append(
                    {
                        "key": key,
                        "task_key": task["key"],
                        "at": at.isoformat(),
                        "due": due.isoformat(),
                        "stage": stage,
                        "task": task,
                    }
                )
    plan.sort(key=lambda x: x["at"])
    store.set("guardian_plan", plan)
    return plan


def update_schedule(root, store, config, now, force=False):
    from .schedule import deadline_task_info, install_deadline_task, remove_deadline_task

    plan = rebuild_plan(store, config, now)
    # One-minute buckets coalesce nearby tasks; floor rounding may wake early, minute gate checks actual time.
    times = sorted(
        {
            timestamp(p["at"]).replace(second=0, microsecond=0).isoformat()
            for p in plan
            if timestamp(p["at"]) > now
        }
    )[:40]
    digest = hashlib.sha256(json.dumps(times).encode()).hexdigest()
    unchanged = store.get("guardian_schedule_digest") == digest
    verified = timestamp(store.get("guardian_schedule_verified"))
    if unchanged and not force and verified and timedelta(0) <= now - verified < timedelta(minutes=5):
        return plan
    try:
        if unchanged:
            actual = deadline_task_info(root)
            if (times and actual.get("exists") and actual.get("action_matches")) or (
                not times and not actual.get("exists")
            ):
                store.set("guardian_schedule_verified", now.isoformat())
                return plan
        if times:
            install_deadline_task(root, times)
        else:
            remove_deadline_task(root)
        store.set("guardian_schedule_digest", digest)
        store.set("guardian_schedule_verified", now.isoformat())
        store.set("guardian_schedule_status", "registered" if times else "no_future_deadlines")
    except Exception:
        store.set("guardian_schedule_status", "registration_failed_minute_gate_fallback")
        store.event("guardian_schedule_failed")
    return plan


def tick(store, config, api, dispatcher, now):
    """Runs before the daily gate. Called under the normal per-data-directory process lock."""
    if not config["monitoring"] or not config["guardian_enabled"]:
        return []
    plan = rebuild_plan(store, config, now)
    due_by_task = {}
    for item in plan:
        if timestamp(item["at"]) <= now:
            due_by_task[item["task_key"]] = item  # most urgent stage wins on resume
    results = []
    for item in due_by_task.values():
        if store.get(item["key"]):
            continue
        last = timestamp(store.get("attempt:" + item["key"]))
        if last and now - last < timedelta(minutes=5):
            continue
        store.set("attempt:" + item["key"], now.isoformat())
        task = item["task"]
        result = verify(api, task["course_id"], task["key"].split(":")[-1], store, now)
        results.append(result)
        if result["assignment_refreshed"]:
            store.update_task(
                task["key"],
                {"due": result["due"], "lock": result.get("lock"), "late_allowed": result["late_allowed"]},
            )
        if result["status"] in (SUBMITTED, EXCUSED):
            store.set(item["key"], "submitted")
            continue
        if result["assignment_refreshed"] and timestamp(result["due"]) != timestamp(item["due"]):
            # Replanned date can be sooner; evaluate the new window on the next minute wake.
            store.set(item["key"], "deadline_changed")
            continue
        remaining = int((timestamp(item["due"]) - now).total_seconds() / 60)
        body = (
            f"{task['course']} · {task['title']}\n"
            + f"{remaining} minutes remaining / 剩余分钟\n"
            + f"Due: {local_time_label(item['due'], config['timezone'])}\n"
            + f"Submission: {result['status']}\nLate submission allowed: {result['late_allowed']}\n"
            + (
                "Offline/unverified: check Canvas directly. / 未确认，请打开 Canvas 核对。\n"
                if result["status"] == UNKNOWN
                else ""
            )
            + "Open the app → Deadline Guardian for Prompt / Review / Verify.\n打开程序的紧急提醒面板可生成提示词、审阅文件与核对提交。"
        )
        message = Message(
            item["key"],
            "Deadline Guardian / 截止紧急提醒",
            body,
            task["url"],
            important=True,
            task_key=task["key"],
        )
        ok = dispatcher.send(message, config["channels"], now)
        if ok:
            store.set(item["key"], "sent")
        store.set(
            "guardian_last",
            {
                "key": task["key"],
                "status": result["status"],
                "remaining_minutes": remaining,
                "checked": now.isoformat(),
            },
        )
    rebuild_plan(store, config, now)
    return results
