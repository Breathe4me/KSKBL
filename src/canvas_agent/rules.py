"""Deterministic reminder and weekly-report rules; UTC arithmetic, local display."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Status, timestamp


@dataclass
class Message:
    key: str
    title: str
    body: str
    url: str = ""
    important: bool = False
    weekly: bool = False
    task_key: str = ""
    tracking_revision: int | None = None


def due_label(task, zone):
    due = timestamp(task.due)
    return due.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M %Z") if due else "No Due Date / 无截止日期"


def local_time_label(value, zone, seconds=False):
    if not value:
        return "—"
    try:
        instant = timestamp(value) if isinstance(value, str) else value
        if instant.tzinfo is None:
            return "—"
        return instant.astimezone(ZoneInfo(zone)).strftime(
            "%Y-%m-%d %H:%M:%S %Z" if seconds else "%Y-%m-%d %H:%M %Z"
        )
    except (ValueError, TypeError, AttributeError):
        return "—"


def failure_lines(failures, courses=()):
    course_codes = {c["id"]: c.get("course_code") or c.get("name", str(c["id"])) for c in courses}
    kinds = {
        "assignments": "Assignments / 作业",
        "quizzes": "Quizzes / 测验",
        "announcements": "Announcements / 公告",
    }
    reasons = {
        "unsupported_or_missing": "HTTP 404: endpoint unavailable; coverage unconfirmed / 接口不可用，覆盖范围待确认",
        "quiz_navigation_unavailable": "HTTP 404; quiz navigation unavailable / 测验入口未开放，覆盖范围待确认",
        "permission_denied": "HTTP 403: access denied / 无读取权限",
        "network_or_timeout": "Connection failed / 连接失败或超时",
        "tls_verification_failed": "TLS certificate verification failed / TLS 证书验证失败",
        "unverified_quiz_details": "Some quiz details could not be read / 部分测验详情未能读取",
    }
    lines = []
    for failure in failures:
        cid, kind, code = failure["course_id"], failure["kind"], failure["code"]
        lines.append(
            f"- {course_codes.get(cid, cid)} · {kinds.get(kind, kind)}: {reasons.get(code, code)} [{code}]"
        )
        recovery = failure.get("recovery")
        if recovery:
            lines.append(
                f"  Modules checked / 已补查模块: {recovery['modules']}; "
                f"additional quizzes / 补充测验: {recovery['recovered']}; "
                f"unverified details / 详情未确认: {recovery['unresolved']}"
            )
            if recovery["status"] != "ok":
                lines.append(f"  Supplement failed / 补查失败: {recovery['code']}")
    return lines


def capability_lines(capabilities, courses=()):
    course_codes = {c["id"]: c.get("course_code") or c.get("name", str(c["id"])) for c in courses}
    lines = []
    for item in capabilities:
        lines.append(
            f"- {course_codes.get(item['course_id'], item['course_id'])}: "
            "Standalone quiz list disabled by course / 课程未启用独立测验列表"
        )
        recovery = item.get("recovery", {})
        if recovery:
            lines.append(
                f"  Modules checked / 已补查模块: {recovery['modules']}; "
                f"additional quizzes / 补充测验: {recovery['recovered']}"
            )
    if capabilities:
        lines.append(
            "Assignment-linked quizzes are read through Assignments. Other standalone quizzes cannot be fully enumerated. / "
            "关联测验已通过作业接口读取；其他独立测验无法保证全量枚举。"
        )
    return lines


def reminder_messages(tasks, config, now, run_id):
    seen, messages = set(), []
    for task in tasks:
        if task.key in seen:
            continue
        seen.add(task.key)
        if task.completed or not task.due:
            continue
        delta = (timestamp(task.due) - now).total_seconds()
        kind = None
        if 0 <= delta <= config["strong_hours"] * 3600 and config["strong_enabled"]:
            kind = "Deadline soon / 即将截止"
        elif -config["overdue_days"] * 86400 <= delta < 0 and config["overdue_enabled"]:
            kind = "Overdue / 已逾期"
        if kind:
            body = f"{task.course} · {task.title}\nDue / 截止: {due_label(task, config['timezone'])}\n{task.status}"
            if task.status == "Unknown":
                body += "\nSubmission status unknown — verify in Canvas / 提交状态未知，请在 Canvas 核对"
            if task.late_allowed is not None:
                body += f"\nLate submission allowed: {task.late_allowed}"
            messages.append(Message(f"{run_id}:{task.key}", kind, body, task.url, True, task_key=task.key))
    return messages


def weekly_report(snap, config, now, week_key):
    local = now.astimezone(ZoneInfo(config["timezone"]))
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    upcoming, done, unfinished, unknown, pending, undated = [], [], [], [], [], []
    unique = {t.key: t for t in snap.tasks}
    for task in sorted(unique.values(), key=lambda t: timestamp(t.due) or datetime.max.replace(tzinfo=UTC)):
        if not task.due:
            undated.append(task)
            continue
        if not start <= timestamp(task.due) < end:
            continue
        upcoming.append(task)
        (
            done
            if task.completed
            else pending
            if task.status == Status.PENDING
            else unknown
            if task.status == Status.UNKNOWN
            else unfinished
        ).append(task)
    lines = [
        "Data incomplete / 数据不完整"
        if snap.failures
        else "Assignments and announcements synchronized / 作业与公告同步成功"
        if snap.capabilities
        else "Current synchronized data / 当前同步数据"
    ]
    if snap.failures:
        lines.extend(
            [
                "Available data is shown below; failed scopes may contain additional items. / 以下展示已读数据，失败范围可能仍有遗漏。",
                "Failed scopes / 失败数据范围:",
                *failure_lines(snap.failures, snap.courses),
            ]
        )
    if snap.capabilities:
        lines.extend(["Data source notes / 数据源说明:", *capability_lines(snap.capabilities, snap.courses)])
    for title, tasks in [
        ("This week / 本周", upcoming),
        ("Completed / 已完成", done),
        ("Not submitted / 未提交", unfinished),
        ("Unknown / 未知", unknown),
        ("Pending / Processing / 处理中", pending),
        ("No Due Date / 无截止日期", undated),
    ]:
        lines.append(f"\n{title}: {len(tasks)}")
        # The overview contains counts; list each task only in its status section.
        if tasks is not upcoming:
            lines.extend(
                f"{t.course} · {t.title}\n{due_label(t, config['timezone'])} | {t.status}\n{t.url}\n"
                for t in tasks
            )
    lines.append(f"\nAnnouncements / 公告: {len(snap.announcements)}")
    lines.extend(f"{a.course} · {a.title}\n{a.url}" for a in snap.announcements[-20:])
    return Message(f"weekly:{week_key}", "Canvas weekly report / 每周报告", "\n".join(lines), weekly=True)
