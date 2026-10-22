"""Tk/ttk desktop UI. Network work runs on a worker; Tk is used only on the main thread."""

import copy
import json
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from zoneinfo import ZoneInfo

from . import __version__, maintenance
from .ai import AIClient
from .api import CanvasAPI
from .config import DEFAULTS, load, save, validate
from .courses import academic_courses, selected_courses
from .engine import run
from .models import Announcement, Task
from .notifications import Dispatcher, PushPlusChannel, WindowsChannel
from .rules import (
    Message,
    capability_lines,
    due_label,
    failure_lines,
    local_time_label,
    reminder_messages,
    weekly_report,
)
from .schedule import install_task, next_slot, rebase_timezone
from .schedule import remove_all_tasks as remove_task
from .security import ProcessLock, Secrets, ai_key, safe_link
from .storage import Store

SAVED_SECRET_MASK = "••••••••"  # noqa: S105 - fixed UI placeholder, never a credential


class Application:
    def __init__(self, root, data_root):
        self.root, self.data_root = root, Path(data_root)
        self.config = load(self.data_root / "config.json")
        self.secrets = Secrets(self.data_root)
        self.lang = self.config["language"]
        self.results = queue.Queue()
        self.busy = False
        self.ai_busy = False
        self.vars, self.secret_vars, self.time_lists = {}, {}, {}
        self.course_rows, self.task_rows, self.announcement_rows = {}, {}, {}
        root.title(f"Canvas Deadline Agent {__version__}")
        root.geometry("1120x800")
        root.minsize(900, 700)
        root.configure(bg="#eef2f6")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f6")
        style.configure("TLabel", background="#eef2f6", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("Header.TLabel", font=("Segoe UI", 21, "bold"), foreground="#183a52")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        self.build()
        self.refresh()
        root.after(100, self.poll)
        if not self.config["canvas_url"]:
            root.after(200, self.wizard)

    def tr(self, english, chinese):
        return chinese if self.lang == "zh" else english

    def button(self, parent, en, zh, command, **kwargs):
        b = ttk.Button(parent, text=self.tr(en, zh), command=command)
        b.pack(side=kwargs.pop("side", "left"), padx=4, pady=6, **kwargs)
        return b

    def text_window(self, title, value):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("850x600")
        text = tk.Text(win, wrap="word", font=("Segoe UI", 11), padx=20, pady=20)
        text.pack(fill="both", expand=True)
        text.insert("1.0", value)
        text.configure(state="disabled")

    def build(self):
        self.credential_status = {}
        self.secret_placeholders = set()
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        self.outer = outer
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Canvas Deadline Agent", style="Header.TLabel").pack(side="left")
        self.button(header, "中文 / English", "English / 中文", self.switch_language, side="right")
        ttk.Label(
            outer, text=self.tr("Your courses. Your schedule. Your data.", "你的课程、你的计划、你的数据。")
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))
        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.tabs = {}
        for key, en, zh in [
            ("dashboard", "Dashboard", "概览"),
            ("courses", "Courses & Tasks", "课程与任务"),
            ("schedule", "Schedule", "检查计划"),
            ("reminders", "Reminders", "提醒"),
            ("notifications", "Notifications", "通知"),
            ("ai", "AI Settings", "AI 设置"),
            ("settings", "Settings / Logs", "设置与日志"),
        ]:
            tab = ttk.Frame(self.notebook, padding=16)
            self.notebook.add(tab, text=self.tr(en, zh))
            self.tabs[key] = tab
        self.dashboard()
        self.courses_tab()
        self.schedule_tab()
        self.reminders_tab()
        self.notifications_tab()
        self.ai_tab()
        self.settings_tab()
        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value=self.tr("Ready", "就绪"))
        ttk.Label(footer, textvariable=self.status, wraplength=400, justify="left").grid(
            row=0, column=0, sticky="w"
        )
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.save_all_button = ttk.Button(
            footer, text=self.tr("Save all settings", "保存全部设置"), command=self.save_settings
        )
        self.save_all_button.grid(row=0, column=2, sticky="e", padx=(8, 0), pady=6)
        from .copilot_gui import CopilotPanel

        if hasattr(self, "copilot"):
            self.copilot.access.revoke()
        self.copilot = CopilotPanel(self)

    def field(self, parent, key, en, zh, options=None, secret=False):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=self.tr(en, zh), width=32).pack(side="left")
        value = "" if secret else self.config[key]
        variable = tk.StringVar(value=str(value))
        if secret:
            self.secret_vars[key] = variable
        else:
            self.vars[key] = variable
        control = (
            ttk.Combobox(row, textvariable=variable, values=options, state="readonly")
            if options
            else ttk.Entry(row, textvariable=variable, show="•" if secret else "")
        )
        control.pack(side="left", fill="x", expand=True)
        if secret:
            state = tk.StringVar()
            self.credential_status[key] = state
            ttk.Label(parent, textvariable=state, wraplength=850).pack(anchor="w", pady=(0, 8))
            variable.trace_add("write", lambda *_args, name=key: self.refresh_credential_status(name))
            self.bind_secret_entry(control, key)
            self.restore_secret_placeholder(key)
        return variable

    def secret_input(self, name):
        value = self.secret_vars[name].get().strip()
        return "" if value == SAVED_SECRET_MASK else value

    def bind_secret_entry(self, entry, name):
        def edit(_event):
            if name in self.secret_placeholders:
                self.secret_placeholders.discard(name)
                self.secret_vars[name].set("")

        entry.bind("<FocusIn>", edit)
        entry.bind("<FocusOut>", lambda _event: self.restore_secret_placeholder(name))

    def restore_secret_placeholder(self, name):
        if not self.secret_input(name):
            try:
                saved = bool(self.secrets.get(name))
            except Exception:
                saved = False
            if saved:
                self.secret_placeholders.add(name)
                self.secret_vars[name].set(SAVED_SECRET_MASK)
            else:
                self.secret_placeholders.discard(name)
                self.secret_vars[name].set("")
        self.refresh_credential_status(name)

    def refresh_credential_status(self, name=None):
        for key in [name] if name else self.credential_status:
            if self.secret_vars[key].get() != SAVED_SECRET_MASK:
                self.secret_placeholders.discard(key)
            try:
                saved = bool(self.secrets.get(key))
                text = (
                    self.tr(
                        "Saved (Windows encrypted). Mask represents the saved credential; click to replace.",
                        "已保存（Windows 加密）。掩码代表已保存凭据；点击输入框可替换。",
                    )
                    if saved
                    else self.tr("Not saved", "尚未保存")
                )
            except Exception:
                text = self.tr(
                    "Stored credential cannot be read; enter it again and save.",
                    "已存凭据无法读取，请重新输入并保存。",
                )
            if self.secret_input(key):
                text = (
                    self.tr("New value entered; save settings to apply. ", "已输入新值，保存设置后生效。")
                    + text
                )
            self.credential_status[key].set(text)

    def check(self, parent, key, en, zh):
        variable = tk.BooleanVar(value=self.config[key])
        self.vars[key] = variable
        ttk.Checkbutton(parent, text=self.tr(en, zh), variable=variable).pack(anchor="w", pady=6)

    def dashboard(self):
        tab = self.tabs["dashboard"]
        self.local_clock = tk.StringVar()
        ttk.Label(tab, textvariable=self.local_clock, font=("Segoe UI", 12)).pack(anchor="w", pady=(5, 0))
        self.refresh_clock()
        self.summary = tk.StringVar()
        ttk.Label(
            tab, textvariable=self.summary, font=("Segoe UI", 12), justify="left", wraplength=1000
        ).pack(anchor="w", pady=18)
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        self.button(buttons, "Check Now", "立即检查", self.check_now)
        self.button(buttons, "View weekly report", "查看本周报告", self.view_weekly)
        self.button(buttons, "View AI summary", "查看 AI 摘要", self.view_ai)
        self.button(buttons, "Data sources…", "数据源说明…", self.view_sources)
        self.check(
            tab,
            "monitoring",
            "Enable automatic monitoring (Task Scheduler)",
            "开启自动监控（Windows 任务计划）",
        )
        ttk.Label(
            tab,
            text=self.tr(
                "Save settings to apply monitoring. Checks continue after this window closes.\n"
                "The computer must be running and you must be signed in. Missed checks are combined on return.\n"
                "Cached tasks show their last check time; incomplete sync is always flagged.",
                "保存设置后生效。关闭窗口后，任务计划仍会检查。\n电脑须运行且用户已登录；恢复后合并补查。\n缓存任务显示上次检查时间；同步不完整时始终提示。",
            ),
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=25)

    def tree(self, parent, columns, height=7):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=6)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height)
        for key, en, zh, width in columns:
            tree.heading(key, text=self.tr(en, zh))
            tree.column(key, width=width, minwidth=50)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return tree

    def courses_tab(self):
        tab = self.tabs["courses"]
        ttk.Label(
            tab,
            text=self.tr(
                "Only courses with academic codes are shown. Double-click to toggle monitoring, then save.",
                "仅显示带课程代码的正式课程，排除培训模块。双击课程切换监控，然后保存。",
            ),
        ).pack(anchor="w")
        self.course_tree = self.tree(
            tab,
            [
                ("selected", "Monitor", "监控", 70),
                ("code", "Course code", "课程代码", 180),
                ("name", "Course", "课程", 500),
            ],
            4,
        )
        self.course_tree.bind("<Double-1>", self.toggle_course)
        self.task_tree = self.tree(
            tab,
            [
                ("course", "Course", "课程", 140),
                ("title", "Task", "任务", 220),
                ("due", "Due", "截止时间", 170),
                ("status", "Status", "状态", 170),
                ("checked", "Last checked (local)", "检查时间（本地）", 185),
            ],
            6,
        )
        self.task_tree.bind("<Double-1>", lambda _: self.open_selected(self.task_tree, self.task_rows))
        self.button(
            tab,
            "Open selected task in Canvas",
            "在 Canvas 打开所选任务",
            lambda: self.open_selected(self.task_tree, self.task_rows),
        )
        self.announcement_tree = self.tree(
            tab,
            [
                ("course", "Course", "课程", 160),
                ("title", "Announcement", "公告", 400),
                ("posted", "Posted / updated", "发布／更新", 200),
            ],
            3,
        )
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        self.button(buttons, "Read announcement", "阅读公告", self.read_announcement)
        self.button(
            buttons,
            "Open announcement",
            "打开公告链接",
            lambda: self.open_selected(self.announcement_tree, self.announcement_rows),
        )

    def time_editor(self, tab, key, en, zh):
        box = ttk.LabelFrame(tab, text=self.tr(en, zh), padding=10)
        box.pack(fill="x", pady=10)
        values = tk.Listbox(box, height=4, exportselection=False, font=("Segoe UI", 11))
        for t in self.config[key]:
            values.insert("end", t)
        self.time_lists[key] = values
        values.pack(side="left", fill="x", expand=True)
        edit = ttk.Frame(box)
        edit.pack(side="left", padx=12)
        entry = ttk.Entry(edit, width=12)
        entry.insert(0, "10:00")
        entry.pack()

        def update(replace=False):
            from .config import times

            try:
                time_value = times([entry.get().strip()])[0]
                if replace and values.curselection():
                    values.delete(values.curselection()[0])
                existing = set(values.get(0, "end")) | {time_value}
                values.delete(0, "end")
                for t in sorted(existing):
                    values.insert("end", t)
            except ValueError as e:
                messagebox.showerror(self.tr("Invalid time", "时间无效"), str(e))

        self.button(edit, "Add", "添加", update)
        self.button(edit, "Replace", "修改", lambda: update(True))
        self.button(
            edit,
            "Delete",
            "删除",
            lambda: values.delete(values.curselection()[0]) if values.curselection() else None,
        )

    def schedule_tab(self):
        tab = self.tabs["schedule"]
        self.field(tab, "mode", "Mode: normal / exam", "模式：normal 普通 / exam 考试周", ["normal", "exam"])
        self.time_editor(tab, "normal_times", "Normal schedule (24-hour)", "普通计划（24 小时制）")
        self.time_editor(tab, "exam_times", "Exam schedule (24-hour)", "考试周计划（24 小时制）")
        self.field(tab, "exam_start", "Exam start (YYYY-MM-DD)", "考试周开始（YYYY-MM-DD）")
        self.field(tab, "exam_end", "Exam end (YYYY-MM-DD)", "考试周结束（YYYY-MM-DD）")
        ttk.Label(
            tab,
            text=self.tr(
                "An exam date range automatically overrides normal mode. Leave both dates blank to disable.\n"
                "A local gate wakes every minute; network checks only run at your selected times.",
                "考试日期范围内自动使用考试周计划；两个日期均留空则禁用范围。\n本地程序每分钟检查计划，仅到设定时间才请求网络。",
            ),
            wraplength=850,
        ).pack(anchor="w", pady=12)
        self.button(tab, "Restore schedule defaults", "恢复计划默认值", self.reset_schedule)

    def reminders_tab(self):
        tab = self.tabs["reminders"]
        self.check(tab, "strong_enabled", "Enable strong reminders", "开启强提醒")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text=self.tr("Reminder window", "强提醒提前量"), width=32).pack(side="left")
        hours = self.config["strong_hours"]
        self.window_choice = tk.StringVar(value=f"{hours} Hours" if hours in (24, 48) else "Custom")
        ttk.Combobox(
            row, state="readonly", textvariable=self.window_choice, values=["24 Hours", "48 Hours", "Custom"]
        ).pack(side="left")
        self.field(tab, "strong_hours", "Custom hours (1–8760)", "自定义小时数（1–8760）")
        self.check(tab, "overdue_enabled", "Enable overdue tracking", "开启逾期追踪")
        self.field(tab, "overdue_days", "Overdue tracking days (1–365)", "逾期追踪天数（1–365）")
        self.check(tab, "weekly_enabled", "Enable weekly report", "开启每周报告")
        self.field(
            tab,
            "weekly_day",
            "Weekly day (0=Mon … 6=Sun)",
            "周报星期（0=周一…6=周日）",
            [str(x) for x in range(7)],
        )
        self.field(tab, "weekly_time", "Weekly time (HH:MM)", "周报时间（HH:MM）")
        self.weekly_channel = tk.StringVar(value=self.channel_label(self.config["weekly_channels"]))
        ttk.Label(tab, text=self.tr("Weekly notification channel", "周报通知渠道")).pack(
            anchor="w", pady=(10, 0)
        )
        ttk.Combobox(
            tab,
            state="readonly",
            textvariable=self.weekly_channel,
            values=["Windows Only", "PushPlus Only", "Windows + PushPlus"],
        ).pack(anchor="w")
        ttk.Label(
            tab,
            text=self.tr(
                "Every scheduled check inside the window repeats the reminder.\n"
                "Submitted/graded tasks stop. Unknown stays unknown.",
                "进入窗口后，每次计划检查均可再次提醒。\n已提交或评分后停止提醒；未知状态始终标记为未知。",
            ),
        ).pack(anchor="w", pady=20)

    @staticmethod
    def channel_label(channels):
        return (
            "Windows + PushPlus"
            if len(channels) == 2
            else "PushPlus Only"
            if channels == ["pushplus"]
            else "Windows Only"
        )

    @staticmethod
    def parse_channel(label):
        return (
            ["windows", "pushplus"]
            if label == "Windows + PushPlus"
            else ["pushplus"]
            if label == "PushPlus Only"
            else ["windows"]
        )

    def notifications_tab(self):
        tab = self.tabs["notifications"]
        self.channel = tk.StringVar(value=self.channel_label(self.config["channels"]))
        ttk.Label(tab, text=self.tr("Notification channels", "通知渠道")).pack(anchor="w")
        ttk.Combobox(
            tab,
            state="readonly",
            textvariable=self.channel,
            values=["Windows Only", "PushPlus Only", "Windows + PushPlus"],
        ).pack(anchor="w", pady=12)
        self.field(tab, "pushplus", "PushPlus Token", "PushPlus Token", secret=True)
        ttk.Label(
            tab,
            text=self.tr(
                "PushPlus sends selected course text to pushplus.plus. Save settings before testing.\n"
                "Windows notifications must be enabled in Windows Settings. Delivery errors appear in Logs.",
                "PushPlus 会将所选课程文本发送至 pushplus.plus；请保存后测试。\nWindows 通知须在系统设置中启用；发送错误显示在日志中。",
            ),
            wraplength=850,
        ).pack(anchor="w", pady=14)
        self.button(tab, "Test notification", "测试通知", self.test_notification)

    def scroll_content(self, parent):
        canvas = tk.Canvas(parent, highlightthickness=0, background="#eef2f6")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(canvas)
        item = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        return content

    def ai_tab(self):
        tab = self.scroll_content(self.tabs["ai"])
        self.check(tab, "ai_enabled", "Enable AI (off by default)", "开启 AI（默认关闭）")
        self.check(
            tab,
            "ai_consent",
            "I agree to the enabled AI purposes and explicitly confirmed requests below",
            "我同意下方单独启用的 AI 用途与手动确认的请求",
        )
        self.check(
            tab,
            "ai_announcements_enabled",
            "Automatic announcement summaries (sends full announcement text; off by default)",
            "自动公告摘要（发送完整公告文本；默认关闭）",
        )
        self.check(
            tab,
            "ai_weekly_enabled",
            "AI weekly supplement (sends course/task/status/date/link data; off by default)",
            "AI 周报补充（发送课程、作业、状态、日期及链接；默认关闭）",
        )
        provider = self.field(tab, "ai_provider", "Provider", "供应商", ["DeepSeek", "OpenAI", "Custom"])
        self.field(tab, "ai_url", "Base URL (include /v1 if needed)", "Base URL（需要时包含 /v1）")
        self.field(tab, "ai_model", "Model name", "模型名称")
        self.field(tab, "ai", "API Key", "API Key", secret=True)
        self.field(tab, "ai_temperature", "Temperature (advanced, 0–2)", "Temperature（高级，0–2）")
        self.field(tab, "ai_max_tokens", "Max tokens (100–4096)", "最大输出 Token（100–4096）")
        self.field(
            tab, "ai_announcement_limit", "Auto summaries per check (1–10)", "每次自动摘要上限（1–10）"
        )

        self.field(tab, "ai_daily_budget", "Summary requests per day (1–100)", "摘要每日请求预算（1–100）")

        def provider_change(*_):
            if provider.get() == "DeepSeek":
                self.vars["ai_url"].set("https://api.deepseek.com")
                self.vars["ai_model"].set("deepseek-chat")
            elif provider.get() == "OpenAI":
                self.vars["ai_url"].set("https://api.openai.com/v1")
                self.vars["ai_model"].set("gpt-4.1-mini")

        provider.trace_add("write", provider_change)
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        self.button(buttons, "Test AI connection…", "测试 AI 连接…", self.test_ai)
        self.button(buttons, "Generate daily summary…", "生成每日摘要…", self.summarize)
        ttk.Label(
            tab,
            text=self.tr(
                "Each enabled purpose and manual action may incur charges. Save first.\n"
                "Weekly AI is a separate supplement; the regular report never waits for AI.\n"
                "The summary budget excludes explicit connection tests and previewed cloud reviews.\n"
                "AI dates/tasks require verification; official Canvas data is never changed.",
                "各项用途及手动操作均可能计费；请先保存。\n"
                "AI 周报作为独立补充发送，常规周报不等待 AI。\n"
                "摘要预算不含手动连接测试及全文预览后发送的云审阅。\n"
                "AI 日期与待办需核对，不会修改 Canvas 官方数据。",
            ),
            wraplength=850,
        ).pack(anchor="w", pady=14)

    def settings_tab(self):
        tab = self.tabs["settings"]
        self.field(tab, "canvas_url", "Canvas Base URL", "Canvas 地址")
        self.field(tab, "canvas", "Canvas Token", "Canvas Token", secret=True)
        self.field(tab, "timezone", "Display and schedule timezone (IANA)", "显示与调度时区（IANA）")
        self.check(tab, "include_ended", "Include ended courses", "包含已结束课程")
        self.button(tab, "Test Canvas connection", "测试 Canvas 连接", self.test_connection)
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        self.button(buttons, "View logs", "查看日志", self.view_logs)
        self.button(buttons, "Export diagnostics", "导出脱敏诊断", self.export_diagnostics)
        self.button(buttons, "Backup data…", "备份数据…", self.backup)
        self.button(buttons, "Restore backup…", "恢复备份…", self.restore)
        buttons2 = ttk.Frame(tab)
        buttons2.pack(fill="x")
        self.button(buttons2, "Restore default settings…", "恢复默认配置…", self.reset_settings)
        self.button(buttons2, "Remove stored credentials…", "删除已保存凭据…", self.remove_credentials)
        self.button(buttons2, "Clear local data…", "清除本地数据…", self.clear_data)
        ttk.Label(
            tab,
            text=f"Version {__version__}\n"
            + self.tr(
                "Independent open-source candidate. Not affiliated with Instructure, Canvas LMS or any university.\n"
                "Credentials: current-user Windows DPAPI. Local data: ",
                "独立开源候选版本；与 Instructure、Canvas LMS 或任何大学无隶属关系。\n"
                "凭据：当前 Windows 用户 DPAPI。数据位置：",
            )
            + str(self.data_root),
            wraplength=850,
        ).pack(anchor="w", pady=20)

    def collect(self):
        c = copy.deepcopy(self.config)
        for key, var in self.vars.items():
            c[key] = var.get()
        for key in (
            "overdue_days",
            "weekly_day",
            "ai_max_tokens",
            "guardian_minutes",
            "guardian_repeat_minutes",
            "ai_announcement_limit",
            "ai_daily_budget",
        ):
            c[key] = int(c[key])
        c["strong_hours"] = (
            int(c["strong_hours"])
            if self.window_choice.get() == "Custom"
            else int(self.window_choice.get().split()[0])
        )
        c["ai_temperature"] = float(c["ai_temperature"])
        for key, widget in self.time_lists.items():
            c[key] = list(widget.get(0, "end"))
        c["channels"], c["weekly_channels"] = (
            self.parse_channel(self.channel.get()),
            self.parse_channel(self.weekly_channel.get()),
        )
        c["language"] = self.lang
        return validate(c)

    def work_ai(self, function, callback=None):
        self.work(function, callback, independent=True)

    def work(self, function, callback=None, independent=False):
        if self.ai_busy if independent else self.busy:
            self.status.set(self.tr("An operation is still running", "操作仍在进行中"))
            return
        if independent:
            self.ai_busy = True
        else:
            self.busy = True
            self.status.set(self.tr("Working…", "处理中…"))
            self.progress.start()

        def worker():
            try:
                self.results.put((True, function(), callback, independent))
            except Exception as e:
                # Display a stable type/code only; HTTP/credential exceptions may contain secrets.
                self.results.put((False, getattr(e, "code", type(e).__name__), None, independent))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            self.refresh_clock()
            try:
                ok, result, callback, *flags = self.results.get_nowait()
            except queue.Empty:
                return
            independent = bool(flags and flags[0])
            if independent:
                self.ai_busy = False
            else:
                self.busy = False
                self.progress.stop()
            if not self.busy:
                self.status.set(
                    self.tr("Completed", "已完成")
                    if ok
                    else self.tr("Operation failed: ", "操作失败：") + str(result)
                )
            if ok and callback:
                callback(result)
            if self.root.winfo_exists():
                self.refresh_credential_status()
                if ok:
                    self.refresh()
                else:
                    messagebox.showerror(self.tr("Operation failed", "操作失败"), str(result))
        except tk.TclError:
            # A closed child window must not stop all future queued results.
            pass
        except Exception as error:
            self.status.set(self.tr("Display failed: ", "显示失败：") + type(error).__name__)
        finally:
            try:
                if self.root.winfo_exists():
                    self.root.after(100, self.poll)
            except tk.TclError:
                pass

    def save_settings(self, callback=None):
        try:
            c = self.collect()
            credentials = {k: self.secret_input(k) for k in self.secret_vars}
        except (ValueError, KeyError) as e:
            messagebox.showerror(self.tr("Invalid settings", "配置无效"), str(e))
            return

        def operation():
            with ProcessLock(self.data_root):
                changed_account = c["canvas_url"] != self.config["canvas_url"] or bool(
                    credentials.get("canvas") and credentials["canvas"] != self.secrets.get("canvas")
                )
                for name, value in credentials.items():
                    if value:
                        self.secrets.set(name, value)
                if changed_account:
                    store = Store(self.data_root)
                    try:
                        store.reset_account()
                    finally:
                        store.close()
                save(self.data_root / "config.json", c)
                if c["timezone"] != self.config["timezone"]:
                    store = Store(self.data_root)
                    try:
                        rebase_timezone(c, store, datetime.now(UTC))
                    finally:
                        store.close()
                try:
                    if c["monitoring"]:
                        install_task(self.data_root)
                        from .guardian import update_schedule

                        state = Store(self.data_root)
                        try:
                            update_schedule(self.data_root, state, c, datetime.now(UTC), force=True)
                        finally:
                            state.close()
                    else:
                        remove_task(self.data_root)
                except Exception:
                    save(self.data_root / "config.json", c | {"monitoring": False})
                    raise
            return c

        def saved(result):
            self.config = result
            for key, variable in self.secret_vars.items():
                variable.set("")
                self.restore_secret_placeholder(key)
            if callback:
                callback()

        self.work(operation, saved)

    def check_now(self):
        def finished(value):
            if value["status"] in ("ok", "limited"):
                count, notes = value.get("tasks", 0), len(value.get("capabilities", []))
                text = self.tr(
                    f"Synchronized {count} tasks; {notes} data source notes.",
                    f"已同步 {count} 条任务；{notes} 项数据源说明。",
                )
                if not value.get("notifications_ok", True):
                    text += self.tr(
                        " Notification delivery uncertain; see logs.", " 通知送达未确认，请查看日志。"
                    )
            else:
                text = self.tr("Sync did not finish successfully: ", "同步未能全部完成：") + value["status"]
            self.status.set(text)

        self.work(lambda: run(self.data_root), finished)

    def test_connection(self):
        try:
            c = self.collect()
            token = self.secret_input("canvas") or self.secrets.get("canvas")
            if not c["canvas_url"] or not token:
                raise ValueError(self.tr("Canvas URL and Token required", "需要 Canvas 地址和 Token"))
        except ValueError as e:
            messagebox.showerror("Canvas", str(e))
            return

        def operation():
            api = CanvasAPI(c["canvas_url"], token)
            api.identity()
            courses = api.courses(c["include_ended"])
            snap = api.sync(courses)
            return courses, snap

        def finished(result):
            courses, snap = result
            self.fill_courses(courses)
            self.text_window(
                self.tr("Connection test", "连接测试"),
                self.tr("User profile: OK\nCourses: ", "用户信息：成功\n课程数：")
                + str(len(courses))
                + "\n"
                + (
                    "\n".join(failure_lines(snap.failures, courses))
                    if snap.failures
                    else self.tr(
                        "Assignments and announcements synchronized",
                        "作业与公告同步成功",
                    )
                )
                + (
                    "\n\n" + "\n".join(capability_lines(snap.capabilities, courses))
                    if snap.capabilities
                    else ""
                ),
            )

        self.work(operation, finished)

    def fill_courses(self, courses):
        self.course_tree.delete(*self.course_tree.get_children())
        self.course_rows = {}
        for c in academic_courses(courses):
            selected = self.config["course_ids"] is None or c["id"] in self.config["course_ids"]
            iid = self.course_tree.insert(
                "", "end", values=("✓" if selected else "", c.get("course_code", ""), c["name"])
            )
            self.course_rows[iid] = c

    def toggle_course(self, _):
        selected = self.course_tree.selection()
        if not selected:
            return
        cid = self.course_rows[selected[0]]["id"]
        current = set(
            self.config["course_ids"]
            if self.config["course_ids"] is not None
            else [c["id"] for c in self.course_rows.values()]
        )
        current.symmetric_difference_update({cid})
        self.config["course_ids"] = sorted(current)
        self.fill_courses(list(self.course_rows.values()))

    def refresh_clock(self):
        text = self.tr("Current time: ", "当前时间：") + local_time_label(
            datetime.now(UTC), self.config["timezone"], True
        )
        text += f"  ({self.config['timezone']})"
        if self.local_clock.get() != text:
            self.local_clock.set(text)

    def refresh(self):
        self.refresh_clock()
        store = Store(self.data_root)
        try:
            tasks, announcements = store.cached(), store.cached("announcements")
            last, complete = store.get("last_check", "—"), store.get("last_complete")
            failures = store.get("failures", [])
            capabilities = store.get("capabilities", [])
            courses = academic_courses(store.get("course_catalog", store.get("courses", [])))
            last_synced_ids = {c["id"] for c in store.get("courses", [])}
        finally:
            store.close()
        monitored = {c["id"] for c in selected_courses(courses, self.config["course_ids"])}
        tasks = [t for t in tasks if t["course_id"] in monitored]
        announcements = [a for a in announcements if a["course_id"] in monitored]
        failures = [f for f in failures if f["course_id"] == "all" or f["course_id"] in monitored]
        capabilities = [c for c in capabilities if c["course_id"] in monitored]
        failures.extend(
            {"course_id": cid, "kind": "not_checked", "code": "course_selection_changed"}
            for cid in sorted(monitored - last_synced_ids)
            if complete is not None
        )
        now = datetime.now(UTC)
        next_check = next_slot(self.config, now)
        next_text = (
            next_check.astimezone(ZoneInfo(self.config["timezone"])).strftime("%Y-%m-%d %H:%M %Z")
            if next_check
            else "—"
        )
        objects = [Task(**{k: v for k, v in t.items() if k != "checked"}) for t in tasks]
        strong = len(reminder_messages(objects, self.config, now, "preview"))
        upcoming = sum(
            bool(t.due and datetime.fromisoformat(t.due.replace("Z", "+00:00")) >= now and not t.completed)
            for t in objects
        )
        health = (
            self.tr("No check yet", "尚未检查")
            if complete is None
            else self.tr("Assignments and announcements synchronized", "作业与公告同步成功")
            if not failures and capabilities
            else self.tr("Complete", "完整")
            if not failures
            else self.tr("INCOMPLETE — some scopes could not be refreshed", "同步不完整；部分范围未能更新")
        )
        self.summary.set(
            self.tr("Connection / sync: ", "连接／同步：")
            + health
            + self.tr("\nMonitored courses: ", "\n监控课程：")
            + str(len(monitored))
            + self.tr("\nUpcoming tasks: ", "\n待截止任务：")
            + str(upcoming)
            + self.tr("\nReminder candidates (strong + overdue): ", "\n提醒任务（强提醒与逾期）：")
            + str(strong)
            + self.tr("\nLast check (local): ", "\n最近检查（本地）：")
            + local_time_label(last, self.config["timezone"], True)
            + self.tr("\nNext configured slot: ", "\n下一设定时间：")
            + next_text
            + self.tr("\nMonitoring: ", "\n自动监控：")
            + str(self.config["monitoring"])
            + ("\n" + "\n".join(failure_lines(failures, courses)) if failures else "")
            + (
                self.tr(
                    f"\nData source notes: {len(capabilities)} courses have no standalone quiz list; see Data sources.",
                    f"\n数据源说明：{len(capabilities)} 门课程未启用独立测验列表，详见“数据源说明”。",
                )
                if capabilities
                else ""
            )
        )
        self.fill_courses(courses)
        self.task_tree.delete(*self.task_tree.get_children())
        self.task_rows = {}
        for raw, t in sorted(zip(tasks, objects, strict=True), key=lambda pair: pair[1].due or "9999"):
            state = t.status
            if self.lang == "zh":
                state = {
                    "Confirmed Submitted": "确认已提交",
                    "Confirmed Not Submitted": "确认未提交",
                    "Pending / Processing": "处理中／待确认",
                    "Unknown": "未知",
                    "Graded": "已评分",
                }[state]
            if t.excused:
                state += self.tr(" (Excused)", "（已豁免）")
            if t.due and not t.completed and datetime.fromisoformat(t.due.replace("Z", "+00:00")) < now:
                state += self.tr(" · Overdue", " · 已逾期")
            iid = self.task_tree.insert(
                "",
                "end",
                values=(
                    t.course,
                    t.title,
                    due_label(t, self.config["timezone"]),
                    state,
                    local_time_label(raw["checked"], self.config["timezone"]),
                ),
            )
            self.task_rows[iid] = raw
        self.announcement_tree.delete(*self.announcement_tree.get_children())
        self.announcement_rows = {}
        for a in announcements:
            iid = self.announcement_tree.insert(
                "",
                "end",
                values=(
                    a["course"],
                    a["title"],
                    local_time_label(a["updated"] or a["posted"], self.config["timezone"]),
                ),
            )
            self.announcement_rows[iid] = a

    def open_selected(self, tree, rows):
        selected = tree.selection()
        if selected:
            url = safe_link(rows[selected[0]]["url"], self.config["canvas_url"])
            if url:
                webbrowser.open(url)

    def read_announcement(self):
        selection = self.announcement_tree.selection()
        if selection:
            a = self.announcement_rows[selection[0]]
            self.text_window(
                a["title"],
                f"{a['course']}\n{local_time_label(a['posted'], self.config['timezone'])} / {local_time_label(a['updated'], self.config['timezone'])}\n\n{a['body']}\n\n{a['url']}",
            )

    def reset_schedule(self):
        for key, widget in self.time_lists.items():
            widget.delete(0, "end")
            for value in DEFAULTS[key]:
                widget.insert("end", value)
        for key in ("mode", "exam_start", "exam_end"):
            self.vars[key].set(DEFAULTS[key])

    def view_logs(self):
        store = Store(self.data_root)
        try:
            self.text_window(
                self.tr("Logs", "日志"),
                json.dumps(
                    [
                        event | {"at": local_time_label(event["at"], self.config["timezone"], True)}
                        for event in store.events()
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        finally:
            store.close()

    def view_sources(self):
        store = Store(self.data_root)
        try:
            courses = selected_courses(
                store.get("course_catalog", store.get("courses", [])), self.config["course_ids"]
            )
            ids = {c["id"] for c in courses}
            capabilities = [c for c in store.get("capabilities", []) if c["course_id"] in ids]
            failures = [
                f for f in store.get("failures", []) if f["course_id"] == "all" or f["course_id"] in ids
            ]
            text = self.tr(
                "Course data sources are checked again on every sync.",
                "每次同步都会重新检测课程数据源，开放后自动恢复读取。",
            )
            text += "\n\n" + "\n".join(capability_lines(capabilities, courses))
            if failures:
                text += "\n\n" + "\n".join(failure_lines(failures, courses))
            if not capabilities and not failures:
                text += self.tr("\nNo recorded data source restrictions.", "\n未记录数据源限制。")
            self.text_window(self.tr("Data sources", "数据源说明"), text)
        finally:
            store.close()

    def view_weekly(self):
        from .models import Snapshot

        store = Store(self.data_root)
        try:
            tasks = [Task(**{k: v for k, v in t.items() if k != "checked"}) for t in store.cached()]
            anns = [
                Announcement(**{k: v for k, v in a.items() if k != "checked"})
                for a in store.cached("announcements")
            ]
            failures = store.get("failures", [])
            capabilities = store.get("capabilities", [])
            monitored = {
                c["id"] for c in selected_courses(store.get("courses", []), self.config["course_ids"])
            }
            tasks = [t for t in tasks if t.course_id in monitored]
            anns = [a for a in anns if a.course_id in monitored]
            failures = [f for f in failures if f["course_id"] == "all" or f["course_id"] in monitored]
            capabilities = [c for c in capabilities if c["course_id"] in monitored]
            if not store.get("last_check"):
                failures = [{"course_id": "all", "kind": "not_checked", "code": "no_current_data"}]
            report = weekly_report(
                Snapshot(store.get("courses", []), tasks, anns, [], failures, capabilities),
                self.config,
                datetime.now(UTC),
                "preview",
            )
            self.text_window(
                report.title,
                self.tr("Cached preview. Last check: ", "缓存预览。最近检查：")
                + local_time_label(store.get("last_check"), self.config["timezone"], True)
                + "\n\n"
                + report.body,
            )
        finally:
            store.close()

    def view_ai(self):
        from .ai_presentation import format_result

        store = Store(self.data_root)
        try:
            text = format_result(store.get("ai_result", {"status": "not_generated"}), self.lang)
            weekly = store.get("ai_weekly_result")
            if weekly:
                text += "\n\nAI weekly supplement / AI 周报补充\n\n" + format_result(weekly, self.lang)
            self.text_window(
                "AI",
                text,
            )
        finally:
            store.close()

    def test_notification(self):
        c = copy.deepcopy(self.config)

        def operation():
            store = Store(self.data_root)
            try:
                import uuid

                d = Dispatcher(
                    store,
                    {"windows": WindowsChannel(), "pushplus": PushPlusChannel(self.secrets.get("pushplus"))},
                    self.secrets.values(),
                    c["canvas_url"],
                )
                return d.send(
                    Message(
                        f"test:{uuid.uuid4().hex}", "Canvas Deadline Agent", "Test notification / 测试通知"
                    ),
                    c["channels"],
                    datetime.now(UTC),
                )
            finally:
                store.close()

        self.work(
            operation,
            lambda ok: messagebox.showinfo(
                "Notifications",
                self.tr(
                    "Accepted by channel" if ok else "Failed or uncertain; see logs",
                    "渠道已接收" if ok else "失败或状态不明，请查看日志",
                ),
            ),
        )

    def ai_action(self, test=False):
        c = copy.deepcopy(self.config)
        if not c["ai_enabled"] or not c["ai_consent"]:
            messagebox.showinfo(
                "AI", self.tr("Enable AI, consent and save first", "请先开启 AI、同意数据传输并保存")
            )
            return
        if not messagebox.askyesno(
            "AI",
            self.tr("Call your AI provider now? This may incur charges.", "现在调用 AI 服务？可能产生费用。"),
        ):
            return

        def operation():
            ai = AIClient(c, ai_key(self.secrets, c), secrets=self.secrets.values())
            if test:
                return ai.test()
            store = Store(self.data_root)
            try:
                monitored = {
                    course["id"] for course in selected_courses(store.get("courses", []), c["course_ids"])
                }
                anns = [
                    Announcement(**{k: v for k, v in a.items() if k != "checked"})
                    for a in store.cached("announcements")
                    if a["course_id"] in monitored
                ]
                result = ai.summarize(anns, c["language"])
                store.set("ai_result", result)
                return result
            finally:
                store.close()

        from .ai_presentation import format_result

        self.work_ai(operation, lambda result: self.text_window("AI", format_result(result, self.lang)))

    def test_ai(self):
        self.ai_action(True)

    def summarize(self):
        self.ai_action(False)

    def export_diagnostics(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="canvas-diagnostics.json")
        if path:
            self.work(lambda: maintenance.diagnostics(self.data_root, Path(path)))

    def backup(self):
        if not messagebox.askyesno(
            self.tr("Backup", "备份"),
            self.tr(
                "Backup contains unencrypted private course text, but no credentials. It is not redacted diagnostics. Store it securely.",
                "备份含未加密的私人课程文本，不含凭据；它不是脱敏诊断，请妥善保存。",
            ),
        ):
            return
        path = filedialog.asksaveasfilename(defaultextension=".zip", initialfile="canvas-backup.zip")
        if path:
            self.work(lambda: maintenance.backup(self.data_root, path))

    def restore(self):
        path = filedialog.askopenfilename(filetypes=[("Backup", "*.zip")])
        if path and messagebox.askyesno(
            self.tr("Restore", "恢复"),
            self.tr(
                "Replace local data with this backup? Monitoring will be disabled. Restart afterward.",
                "用备份替换本地数据？自动监控将关闭，完成后请重启。",
            ),
        ):
            self.work(lambda: maintenance.restore(self.data_root, path), lambda _: self.root.destroy())

    def reset_settings(self):
        if messagebox.askyesno(
            self.tr("Reset", "重置"),
            self.tr(
                "Restore settings and disable monitoring? Credentials and cache are retained. Restart afterward.",
                "恢复默认配置并关闭监控？保留凭据和缓存，完成后请重启。",
            ),
        ):

            def operation():
                with ProcessLock(self.data_root):
                    remove_task(self.data_root)
                    save(self.data_root / "config.json", copy.deepcopy(DEFAULTS))

            self.work(operation, lambda _: self.root.destroy())

    def remove_credentials(self):
        if messagebox.askyesno(
            self.tr("Credentials", "凭据"),
            self.tr(
                "Remove all stored credentials and disable monitoring?", "删除所有已保存凭据并关闭监控？"
            ),
        ):

            def operation():
                with ProcessLock(self.data_root):
                    remove_task(self.data_root)
                    save(
                        self.data_root / "config.json",
                        self.config | {"monitoring": False, "ai_enabled": False},
                    )
                    for name in Secrets.names:
                        self.secrets.set(name, "")

            self.work(operation, lambda _: self.root.destroy())

    def clear_data(self):
        if messagebox.askyesno(
            self.tr("Clear local data", "清除本地数据"),
            self.tr(
                "Delete credentials, settings and course cache, and remove this app's scheduled task?",
                "删除凭据、配置与课程缓存，并移除本软件的计划任务？",
            ),
        ):
            self.work(lambda: maintenance.clear(self.data_root), lambda _: self.root.destroy())

    def switch_language(self):
        if self.busy:
            return
        self.lang = "zh" if self.lang == "en" else "en"
        # Keep current edits while rebuilding translated controls.
        try:
            self.config = self.collect()
        except ValueError:
            self.config["language"] = self.lang
        pending_secrets = {key: self.secret_input(key) for key in self.secret_vars}
        self.outer.destroy()
        self.vars, self.secret_vars, self.time_lists = {}, {}, {}
        self.build()
        for key, value in pending_secrets.items():
            if value:
                self.secret_vars[key].set(value)
        self.refresh()

    def wizard(self):
        win = tk.Toplevel(self.root)
        win.title(self.tr("Welcome — initial setup", "欢迎 — 首次配置"))
        win.geometry("700x340")
        frame = ttk.Frame(win, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text=self.tr("Connect your Canvas account", "连接你的 Canvas 账户"), style="Header.TLabel"
        ).pack(anchor="w", pady=10)
        ttk.Label(
            frame,
            text=self.tr(
                "1. Enter your school's HTTPS Canvas URL.\n2. Create a personal token in Canvas → Account → Settings.\n3. Choose an IANA timezone, test, then save. Enable monitoring on Dashboard.",
                "1. 填写学校 Canvas 的 HTTPS 地址。\n2. 在 Canvas → 账户 → 设置创建个人 Token。\n3. 选择 IANA 时区、测试并保存；在概览开启自动监控。",
            ),
            wraplength=620,
        ).pack(anchor="w")
        for key, label in [
            ("canvas_url", "Canvas URL"),
            ("canvas", "API Token"),
            ("timezone", self.tr("Timezone", "时区")),
        ]:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=6)
            ttk.Label(row, text=label, width=16).pack(side="left")
            entry = ttk.Entry(
                row,
                textvariable=self.secret_vars[key] if key == "canvas" else self.vars[key],
                show="•" if key == "canvas" else "",
            )
            entry.pack(side="left", fill="x", expand=True)
            if key == "canvas":
                self.bind_secret_entry(entry, "canvas")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.button(buttons, "Test connection", "测试连接", self.test_connection)
        self.button(buttons, "Save & finish", "保存并完成", lambda: self.save_settings(win.destroy))
        self.button(buttons, "Set up later", "稍后设置", win.destroy)
