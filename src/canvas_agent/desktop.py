"""v1.2 presentation shell. Existing advanced controllers remain independently tested."""

import queue
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import __version__
from .config import load, save
from .copilot_gui import CopilotPanel
from .desktop_settings import SettingsPages
from .desktop_tasks import TaskPages
from .gui import Application as AdvancedApplication
from .rules import local_time_label
from .security import ProcessLock, Secrets
from .storage import Store
from .themes import apply
from .tracking import Tracking
from .widgets import Card, Flow, ScrollPage, label

NAV = (
    ("today", "Today", "今日概览"),
    ("assignments", "All assignments", "所有作业"),
    ("history", "Submission history", "提交记录"),
    ("wechat", "WeChat reminders", "微信提醒"),
    ("settings", "Settings", "设置"),
)


class Application(SettingsPages, TaskPages):
    # Worker/credential code is shared with the maintained advanced settings controller.
    work = AdvancedApplication.work
    work_ai = AdvancedApplication.work_ai
    poll = AdvancedApplication.poll
    tree = AdvancedApplication.tree
    text_window = AdvancedApplication.text_window

    def __init__(self, root, data_root):
        self.root, self.data_root = root, Path(data_root)
        self.config = load(self.data_root / "config.json")
        self.lang = self.config["language"]
        self.secrets = Secrets(self.data_root)
        self.results, self.busy, self.ai_busy = queue.Queue(), False, False
        self.page, self.filter = "today", "tracking"
        self.status = tk.StringVar(value=self.tr("Ready", "就绪"))
        self.selected_task, self.advanced = None, None
        self.copilot = CopilotPanel(self, attach=False)
        root.title(f"Canvas Deadline Agent {__version__}")
        root.geometry("1180x820")
        root.minsize(900, 680)
        self.build()
        self.poll_id = root.after(100, self.poll)

    def tr(self, english, chinese):
        return chinese if self.lang == "zh" else english

    def button(self, parent, en, zh, command, **kwargs):
        if not isinstance(parent, Flow):
            return AdvancedApplication.button(self, parent, en, zh, command, **kwargs)
        button = ttk.Button(parent, text=self.tr(en, zh), command=command)
        parent.add(button)
        return button

    def refresh_clock(self):
        pass  # The header displays the last successful synchronization, not a ticking dashboard.

    def refresh_credential_status(self):
        pass  # Credential fields are rebuilt from DPAPI only on navigation.

    def build(self):
        if hasattr(self, "shell"):
            self.shell.destroy()
        self.palette = apply(self.root, self.config["theme"])
        self.shell = ttk.Frame(self.root)
        self.shell.pack(fill="both", expand=True)
        self.shell.columnconfigure(1, weight=1)
        self.shell.rowconfigure(0, weight=1)
        side = ttk.Frame(self.shell, style="Side.TFrame", padding=(12, 26), width=218)
        side.grid(row=0, column=0, sticky="ns")
        label(side, "Canvas\nDeadline Agent", "Side.TLabel", font=("Segoe UI", 16, "bold"))
        label(side, "v1.2 · PERSONAL", "Side.TLabel")
        self.nav_buttons = {}
        for key, en, zh in NAV:
            button = ttk.Button(
                side, text=self.tr(en, zh), style="Nav.TButton", command=lambda k=key: self.navigate(k)
            )
            button.pack(fill="x", pady=4)
            self.nav_buttons[key] = button
        ttk.Frame(side, style="Side.TFrame").pack(fill="both", expand=True)
        self.button(side, "中文 / EN", "EN / 中文", self.switch_language)
        main = ttk.Frame(self.shell, padding=(24, 20, 16, 10))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.sync_label = label(header, "", "Muted.TLabel")
        actions = Flow(header)
        actions.pack(anchor="e")
        self.button(actions, "Sync now", "立即同步", self.sync)
        self.button(actions, "Settings", "设置", lambda: self.navigate("settings"))
        self.content = ttk.Frame(main)
        self.content.grid(row=1, column=0, sticky="nsew")
        footer = ttk.Frame(main)
        footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(footer, textvariable=self.status, wraplength=550)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=90)
        self.progress.grid(row=0, column=1, padx=8)
        self.task_tree = ttk.Treeview(self.content)  # Selection model shared with the Copilot controller.
        self.refresh()

    def persist(self, changes):
        with ProcessLock(self.data_root):
            updated = load(self.data_root / "config.json") | changes
            save(self.data_root / "config.json", updated)
        self.config = updated

    def switch_language(self):
        self.lang = "zh" if self.lang == "en" else "en"
        self.persist({"language": self.lang})
        self.build()

    def set_theme(self, value):
        self.persist({"theme": value})
        self.build()

    def navigate(self, page):
        self.page = page
        self.selected_task = None
        self.refresh()

    def refresh(self):
        for child in self.content.winfo_children():
            if child != self.task_tree:
                child.destroy()
        with_store = Store(self.data_root)
        try:
            self.rows = Tracking(with_store).rows()
            self.account = with_store.get("account")
            self.history = with_store.get("verification_history", [])
            self.events = with_store.events()
            last = local_time_label(with_store.get("last_success"), self.config["timezone"])
            status = with_store.get("last_status", "not_checked")
            failures = with_store.get("failures", [])
            if failures:
                status = ", ".join(sorted({str(f["code"]) for f in failures}))
            self.sync_label.configure(
                text=self.tr("Last successful sync: ", "最近成功同步：") + last + "  ·  " + status
            )
        finally:
            with_store.close()
        self.task_rows = {str(i): t for i, t in enumerate(self.rows)}
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        for key in self.task_rows:
            self.task_tree.insert("", "end", iid=key)
        for key, button in self.nav_buttons.items():
            button.configure(style="Selected.Nav.TButton" if key == self.page else "Nav.TButton")
        self.scroll = ScrollPage(self.content, self.palette["bg"])
        self.scroll.pack(fill="both", expand=True)
        self.body = self.scroll.body
        getattr(self, "render_" + self.page)()

    def heading(self, en, zh, sub_en="", sub_zh=""):
        label(self.body, self.tr(en, zh), "Title.TLabel")
        if sub_en:
            label(self.body, self.tr(sub_en, sub_zh), "Muted.TLabel")

    def render_history(self):
        self.heading(
            "Submission history",
            "提交记录",
            "Read-only verification. An unavailable result is not a failed submission.",
            "只读核验。无法确认并不等于提交失败；请先重新查询。",
        )
        if not self.history:
            label(
                self.body,
                self.tr(
                    "No verification records yet. Verify from assignment details.",
                    "暂无核验记录。可从作业详情核对提交。",
                ),
            )
        for item in reversed(self.history[-100:]):
            card = Card(self.body, self.palette)
            card.pack(fill="x", pady=5)
            label(card.body, self.canvas_label(item["status"]), "CardTitle.TLabel")
            label(
                card.body,
                f"{item['key']} · {local_time_label(item['checked'], self.config['timezone'])}",
                "Card.TLabel",
            )
            label(
                card.body, self.tr("Attempt: ", "尝试编号：") + str(item.get("attempt") or "—"), "Card.TLabel"
            )
