"""One locked unit of work, durable snapshots, schedule coalescing and delivery receipts."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from secrets import token_hex

from .api import APIError, CanvasAPI
from .config import load
from .models import Status
from .notifications import Dispatcher, PushPlusChannel, WindowsChannel
from .rules import Message, reminder_messages, weekly_report
from .schedule import due_work
from .security import ProcessLock, Secrets
from .storage import Store
from .tracking import Tracking


def run(
    root,
    scheduled=False,
    now=None,
    api_factory=CanvasAPI,
    channel_factory=None,
    guardian_only=False,
    sync_only=False,
    secrets_factory=None,
):
    result = _run_monitor(
        root, scheduled, now, api_factory, channel_factory, guardian_only, sync_only, secrets_factory
    )
    if not guardian_only and not sync_only and result["status"] in ("ok", "limited", "partial", "not_due"):
        from .ai_jobs import start_worker

        try:
            start_worker(root)  # returns immediately; never joins under the GUI busy flag
        except Exception:
            # Core work is already committed; optional worker startup cannot undo it.
            result["ai_status"] = "worker_unavailable"
    return result


def _run_monitor(
    root, scheduled, now, api_factory, channel_factory, guardian_only, sync_only=False, secrets_factory=None
):
    now = now or datetime.now(UTC)
    with ProcessLock(root):
        config = load(root / "config.json")
        if (scheduled or guardian_only) and not config["monitoring"]:
            return {"status": "disabled"}
        store = Store(root)
        try:
            store.ensure_submission_rules()
            secrets = (secrets_factory or Secrets)(root)
            token = secrets.get("canvas")
            channels = (
                channel_factory(secrets)
                if channel_factory
                else {}
                if sync_only
                else {"windows": WindowsChannel(), "pushplus": PushPlusChannel(secrets.get("pushplus"))}
            )
            dispatcher = Dispatcher(store, channels, secrets.values(), config["canvas_url"])
            guardian_alerted = set()
            if (
                not sync_only
                and config["guardian_enabled"]
                and config["monitoring"]
                and token
                and config["canvas_url"]
            ):
                from .guardian import tick, update_schedule

                guardian_api = api_factory(config["canvas_url"], token)
                scope = hashlib.sha256((config["canvas_url"] + ":" + token).encode()).hexdigest()
                if store.get("credential_scope") != scope:
                    try:
                        identity = guardian_api.identity()
                    except APIError as error:
                        store.event("guardian_identity_unavailable", error.code)
                        return {"status": error.code, "complete": False}
                    account = hashlib.sha256(f"{config['canvas_url']}:{identity}".encode()).hexdigest()
                    if store.get("account") not in (None, account):
                        store.reset_account()
                    store.set("account", account)
                    store.set("credential_scope", scope)
                guardian_alerted.update(r["key"] for r in tick(store, config, guardian_api, dispatcher, now))
                update_schedule(root, store, config, now)
            if guardian_only:
                return {"status": "ok"}
            work = (
                due_work(config, store, now)
                if scheduled
                else {"run_id": f"manual:{token_hex(16)}", "slot": None, "week": None}
            )
            if not work:
                return {"status": "not_due"}
            if not token or not config["canvas_url"]:
                return {"status": "configuration_required"}
            store.set("last_attempt", now.isoformat())
            client = api_factory(config["canvas_url"], token)
            try:
                identity = client.identity()
                account = hashlib.sha256(f"{config['canvas_url']}:{identity}".encode()).hexdigest()
                if store.get("account") not in (None, account):
                    store.reset_account()
                store.set("account", account)
                store.set(
                    "credential_scope",
                    hashlib.sha256((config["canvas_url"] + ":" + token).encode()).hexdigest(),
                )
                courses = client.courses(config["include_ended"])
                store.set("course_catalog", courses)
                if config["course_ids"] is not None:
                    courses = [c for c in courses if c["id"] in config["course_ids"]]
                snap = client.sync(courses)
            except APIError as e:
                store.set("last_complete", False)
                store.set("last_status", "failed")
                store.set("last_error", e.code)
                store.set("failures", [{"course_id": "all", "kind": "connection", "code": e.code}])
                store.set("needs_retry", scheduled)
                store.set("retry_slot", work["run_id"].removeprefix("scheduled:"))
                store.event("sync_failed", e.code)
                return {"status": e.code, "complete": False}
            # Submission verification is independent of the Guardian feature switch.
            from .submission import EXCUSED, NOT_SUBMITTED, PENDING, SUBMITTED, verify

            for task in snap.tasks:
                baseline = store.get("submission_baseline:" + task.key)
                if ":assignment:" in task.key and baseline is not None and baseline != task.status:
                    verification = verify(client, task.course_id, task.key.split(":")[-1], store, now)
                    task.status = {
                        SUBMITTED: Status.SUBMITTED,
                        EXCUSED: Status.GRADED,
                        NOT_SUBMITTED: Status.NOT_SUBMITTED,
                        PENDING: Status.PENDING,
                    }.get(verification["status"], Status.UNKNOWN)
                store.set("submission_baseline:" + task.key, task.status)
            store.snapshot(snap, now)
            if sync_only:
                store.event("sync_only_complete", snap.status)
                return {
                    "status": "ok" if snap.complete else snap.status,
                    "complete": snap.complete,
                    "tasks": len(snap.tasks),
                    "failures": snap.failures,
                    "capabilities": snap.capabilities,
                    "sync_ok": not snap.failures,
                    "notifications_sent": False,
                }
            if config["guardian_enabled"] and config["monitoring"]:
                from .guardian import update_schedule

                update_schedule(root, store, config, now)
                guardian_alerted.update(r["key"] for r in tick(store, config, client, dispatcher, now))
            failed_assignments = {f["course_id"] for f in snap.failures if f["kind"] == "assignments"}
            reliable_tasks = [
                t
                for t in snap.tasks
                if not (t.kind == "quizzes" and ":assignment:" in t.key and t.course_id in failed_assignments)
            ]
            reliable_tasks = [t for t in reliable_tasks if Tracking(store).active(t.to_dict())]
            messages = reminder_messages(
                [t for t in reliable_tasks if t.key not in guardian_alerted], config, now, work["run_id"]
            )
            reminded = guardian_alerted | {
                t.key for t in reliable_tasks if any(m.key.endswith(":" + t.key) for m in messages)
            }
            for cid, kind in snap.successful:
                if kind not in ("assignments", "quizzes"):
                    continue
                key = f"task_baseline:{cid}:{kind}"
                old = store.get(key)
                scoped = [t for t in reliable_tasks if t.course_id == cid and t.kind == kind]
                current = {t.key: t.due for t in scoped}
                if old is not None:
                    for t in scoped:
                        if (
                            not t.completed
                            and t.key not in reminded
                            and (t.key not in old or old[t.key] != t.due)
                        ):
                            from .rules import due_label

                            messages.append(
                                Message(
                                    f"task_change:{t.key}:{t.due}",
                                    "New/changed task / 新增或修改任务",
                                    f"{t.course} · {t.title}\n{due_label(t, config['timezone'])}\n{t.status}",
                                    t.url,
                                    task_key=t.key,
                                )
                            )
                store.set(key, current)
            for cid, kind in snap.successful:
                if kind != "announcements":
                    continue
                key = f"announcement_baseline:{cid}"
                old = store.get(key)
                anns = [a for a in snap.announcements if a.course_id == cid]
                current = {
                    a.key: hashlib.sha256(f"{a.updated}:{a.title}:{a.body}".encode()).hexdigest()
                    for a in anns
                }
                if old is not None:
                    for a in anns:
                        if old.get(a.key) != current[a.key]:
                            messages.append(
                                Message(
                                    f"announcement:{a.key}:{current[a.key]}",
                                    "New/updated announcement / 新增或更新公告",
                                    f"{a.course} · {a.title}\n{a.body}",
                                    a.url,
                                )
                            )
                store.set(key, current)
            delivery_ok = True
            for message in messages:
                delivery_ok = dispatcher.send(message, config["channels"], now) and delivery_ok
            # Core reports never wait for a model. AI supplements have separate opt-in and jobs.
            from .ai_jobs import queue_job

            if work["week"]:
                report = weekly_report(
                    replace(snap, tasks=[t for t in snap.tasks if Tracking(store).active(t.to_dict())]),
                    config,
                    now,
                    work["week"],
                )
                report = replace(report, tracking_revision=store.get("tracking_revision", 0))
                if dispatcher.send(report, config["weekly_channels"], now):
                    store.set("weekly_done", work["week"])
                queue_job(store, config, "weekly", {"week": work["week"], "body": report.body})
            for announcement in snap.announcements:
                queue_job(store, config, "announcement", announcement.key)
            if work["slot"]:
                store.set("last_slot", work["slot"].isoformat())
            store.set("needs_retry", scheduled and snap.status == "partial")
            store.set("retry_slot", work["run_id"].removeprefix("scheduled:"))
            store.event(
                "sync_complete" if snap.complete else "sync_limited" if not snap.failures else "sync_partial",
                f"courses={len(courses)} tasks={len(snap.tasks)} failures={len(snap.failures)} capabilities={len(snap.capabilities)}",
            )
            return {
                "status": "ok" if snap.complete else snap.status,
                "complete": snap.complete,
                "tasks": len(snap.tasks),
                "notifications_ok": delivery_ok,
                "failures": snap.failures,
                "capabilities": snap.capabilities,
                "sync_ok": not snap.failures,
            }
        finally:
            store.close()
