"""Assignment cards, right-side detail drawer and local action presentation."""

import tkinter as tk
import webbrowser
from datetime import UTC, datetime
from tkinter import messagebox, ttk

from .models import Status, timestamp
from .rules import due_label
from .security import ProcessLock, safe_link
from .storage import Store
from .submission import verify
from .tracking import REASONS, Tracking
from .widgets import Card, Flow, ScrollPage, label


class TaskPages:
    def active(self, task):
        return task["local"]["state"] == "tracking" and task["status"] not in (
            Status.SUBMITTED,
            Status.GRADED,
        )

    def render_today(self):
        self.heading(
            "What matters today?",
            "今天先做什么？",
            "A little clarity for your next deadline.",
            "按自己的节奏，处理下一项截止。",
        )
        now = datetime.now(UTC)
        active = [t for t in self.rows if self.active(t)]
        urgent = [t for t in active if t["due"] and 0 <= (timestamp(t["due"]) - now).total_seconds() <= 3600]
        stats = ttk.Frame(self.body)
        stats.pack(fill="x", pady=(14, 20))
        for col, (en, zh, count) in enumerate(
            (
                ("To do", "待处理作业", len(active)),
                ("Urgent", "紧急截止", len(urgent)),
                ("Locally done", "本地已完成", sum(t["local"]["state"] == "completed" for t in self.rows)),
            )
        ):
            stats.columnconfigure(col, weight=1, uniform="stats")
            card = Card(stats, self.palette, padding=10)
            card.grid(row=0, column=col, sticky="nsew", padx=3)
            label(card.body, str(count), "Count.TLabel")
            label(card.body, self.tr(en, zh), "Card.TLabel")
        self.render_tasks(active)

    def render_assignments(self):
        self.heading(
            "All assignments",
            "所有作业",
            "Canvas status and your local choices stay separate.",
            "Canvas 原始状态与本地选择分别保留。",
        )
        filters = Flow(self.body)
        filters.pack(fill="x", pady=12)
        for key, en, zh in (
            ("tracking", "Tracking", "追踪中"),
            ("completed", "Locally done", "本地完成"),
            ("ignored", "Ignored", "已忽略"),
            ("all", "All", "全部"),
        ):
            self.button(filters, en, zh, lambda k=key: self.set_filter(k))
        rows = (
            self.rows
            if self.filter == "all"
            else [t for t in self.rows if t["local"]["state"] == self.filter]
        )
        self.render_tasks(rows)

    def set_filter(self, value):
        self.filter = value
        self.refresh()

    def render_tasks(self, rows):
        self.visible_rows = sorted(
            rows, key=lambda t: timestamp(t["due"]) or datetime.max.replace(tzinfo=UTC)
        )
        if not rows:
            label(
                self.body,
                self.tr(
                    "Nothing to show. Configure Canvas and sync, or change your filter.",
                    "暂无可展示任务。请配置 Canvas 并同步，或切换筛选。",
                ),
                "Muted.TLabel",
            )
        for task in self.visible_rows:
            card = Card(self.body, self.palette)
            card.pack(fill="x", pady=6)
            label(card.body, task["course"], "Card.TLabel")
            label(card.body, task["title"], "CardTitle.TLabel")
            due = due_label(type("Due", (), {"due": task["due"]})(), self.config["timezone"])
            remaining = ""
            if task["due"]:
                minutes = int((timestamp(task["due"]) - datetime.now(UTC)).total_seconds() / 60)
                remaining = self.tr(
                    f" · {minutes} min remaining" if minutes >= 0 else f" · {abs(minutes)} min overdue",
                    f" · 剩余 {minutes} 分钟" if minutes >= 0 else f" · 已逾期 {abs(minutes)} 分钟",
                )
                if 0 <= minutes <= 60 and self.active(task):
                    label(
                        card.body,
                        self.tr("● DUE SOON", "● 即将截止"),
                        "Card.TLabel",
                        foreground=self.palette["warning"],
                    )
            label(card.body, due + remaining, "Card.TLabel")
            label(
                card.body,
                "Canvas: " + self.canvas_label(task["status"]) + "\n" + self.local_label(task),
                "Card.TLabel",
            )
            actions = Flow(card.body, style="Card.TFrame")
            actions.pack(fill="x")
            self.button(actions, "Details →", "查看详情 →", lambda t=task: self.show_details(t))
            if task["local"]["state"] != "tracking":
                self.button(actions, "Restore tracking", "恢复追踪", lambda t=task: self.mark(t, "tracking"))

    def canvas_label(self, value):
        if self.lang != "zh":
            return str(value)
        return {
            Status.SUBMITTED: "已确认提交",
            Status.NOT_SUBMITTED: "确认未提交",
            Status.UNKNOWN: "无法确认",
            Status.PENDING: "处理中",
            Status.GRADED: "已评分／豁免",
        }.get(value, str(value))

    def local_label(self, task):
        state = task["local"]["state"]
        text = self.tr("Tracking", "正常追踪")
        if state == "completed":
            text = self.tr(
                "Locally completed; Canvas confirmation is independent", "本地已完成，Canvas 确认独立核对"
            )
            if task["status"] not in (Status.SUBMITTED, Status.GRADED):
                text = self.tr("Locally completed; Canvas has not confirmed", "本地已完成，Canvas 尚未确认")
        elif state == "ignored":
            text = self.tr("Ignored · reminders paused", "已忽略 · 提醒已停止")
        if task["local"]["content_changed"]:
            text += self.tr(" · Canvas content updated", " · Canvas 内容已更新")
        return text

    def show_details(self, task):
        self.selected_task = task
        for key, row in self.task_rows.items():
            if row["key"] == task["key"]:
                self.task_tree.selection_set(key)
        # Drawer replaces part of the list; narrow windows get a full-width detail page.
        if hasattr(self, "drawer") and self.drawer.winfo_exists():
            self.drawer.destroy()
        self.drawer = ttk.Frame(self.content, padding=18, style="Card.TFrame")
        if self.content.winfo_width() >= 800:
            self.drawer.place(relx=1, rely=0, anchor="ne", relwidth=0.53, relheight=1)
        else:
            self.drawer.place(x=0, y=0, relwidth=1, relheight=1)
        page = ScrollPage(self.drawer, self.palette["card"])
        page.pack(fill="both", expand=True)
        body = page.body
        label(body, task["title"], "CardTitle.TLabel")
        label(body, "Canvas: " + self.canvas_label(task["status"]) + "\n" + self.local_label(task))
        ttk.Button(body, text=self.tr("Close details", "关闭详情"), command=self.drawer.destroy).pack(anchor="w", pady=6)
        self.reason = tk.StringVar(value=task["local"]["reason"])
        self.note = tk.StringVar(value=task["local"]["note"])
        label(body, self.tr("Optional reason", "可选原因"))
        choices = [
            "—",
            self.tr("Submitted elsewhere", "已通过其他方式提交"),
            self.tr("Group submission", "小组成员统一提交"),
            self.tr("Optional task", "可选任务"),
            self.tr("Other", "其他"),
        ]
        reason_box = ttk.Combobox(body, state="readonly", values=choices)
        reason_box.current(REASONS.index(self.reason.get()))
        reason_box.pack(fill="x", pady=5)
        label(body, self.tr("Note (up to 500 characters)", "备注（最多 500 字）"))
        ttk.Entry(body, textvariable=self.note).pack(fill="x", pady=5)
        for state, en, zh in (
            ("completed", "Mark locally completed", "标记本地已完成"),
            ("ignored", "Ignore assignment", "忽略此作业"),
            ("tracking", "Restore normal tracking", "恢复正常追踪"),
        ):
            ttk.Button(
                body,
                text=self.tr(en, zh),
                command=lambda s=state: self.mark(task, s, REASONS[reason_box.current()], self.note.get()),
            ).pack(fill="x", pady=5)
        ttk.Button(
            body,
            text=self.tr("Verify Canvas status", "核对 Canvas 状态"),
            command=lambda: self.verify_task(task),
        ).pack(fill="x", pady=5)
        ttk.Button(
            body,
            text=self.tr("Requirements / Prompt / Review", "作业要求／Prompt／文件检查"),
            command=lambda: self.copilot.load_task(task),
        ).pack(fill="x", pady=5)
        ttk.Button(
            body,
            text=self.tr("Open official Canvas page", "打开官方 Canvas 页面"),
            command=lambda: self.open_canvas(task),
        ).pack(fill="x", pady=5)
        if task["local"]["state"] != "tracking":
            label(
                body,
                self.tr(
                    "Desktop, WeChat, overdue and Guardian reminders are stopped.",
                    "桌面、微信、逾期及紧急模式提醒均已停止。",
                ),
            )

    def mark(self, task, state, reason="", note=""):
        try:
            with ProcessLock(self.data_root):
                store = Store(self.data_root)
                try:
                    Tracking(store).set(task, state, reason, note)
                finally:
                    store.close()
            self.status.set(self.tr("Local choice saved", "本地选择已保存"))
            self.refresh()
        except (ValueError, RuntimeError) as error:
            messagebox.showerror(self.tr("Local tracking", "本地追踪"), str(error))

    def open_canvas(self, task):
        url = safe_link(task["url"], self.config["canvas_url"])
        if url:
            webbrowser.open(url)

    def verify_task(self, task):
        if ":assignment:" not in task["key"]:
            self.open_canvas(task)
            return

        def operation():
            with ProcessLock(self.data_root):
                store = Store(self.data_root)
                try:
                    return verify(self.copilot.api(), task["course_id"], task["key"].split(":")[-1], store)
                finally:
                    store.close()

        self.work(operation, lambda r: self.status.set(self.canvas_label(r["status"])))
