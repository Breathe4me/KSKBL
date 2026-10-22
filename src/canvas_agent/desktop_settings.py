"""Settings and personal WeChat binding pages; no automatic external requests."""

import tkinter as tk
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import load
from .engine import run
from .gui import Application as AdvancedApplication
from .rules import local_time_label
from .security import ProcessLock
from .storage import Store
from .widgets import Flow, label


class SettingsPages:
    def render_wechat(self):
        self.heading(
            "A reminder in WeChat",
            "把提醒送到微信",
            "Use your own personal PushPlus account.",
            "使用你自己的 PushPlus 个人账号。",
        )
        label(
            self.body,
            self.tr(
                "Register with PushPlus, bind WeChat and complete identity verification as required. Free quotas and frequency limits apply; availability varies by account. Identity verification can incur a fee. Check the official portal for current terms.",
                "需注册 PushPlus、绑定微信，并按平台要求完成实名认证。免费额度及调用频率受限；实名认证可能收费，请以官方当前规则为准。",
            ),
        )
        self.push_token = tk.StringVar()
        self.push_entry = ttk.Entry(self.body, textvariable=self.push_token, show="•")
        self.push_entry.pack(fill="x", pady=8)
        row = Flow(self.body)
        row.pack(fill="x")
        self.button(
            row,
            "Show / hide",
            "显示／隐藏",
            lambda: self.push_entry.configure(show="" if self.push_entry.cget("show") else "•"),
        )
        self.button(row, "Save securely", "安全保存", self.bind_pushplus)
        self.button(row, "Unbind", "解绑", self.unbind_pushplus)
        row = Flow(self.body)
        row.pack(fill="x")
        self.button(row, "Check configuration", "检查配置", self.push_status)
        self.button(row, "Send test…", "发送测试…", self.test_pushplus)
        self.button(
            row, "Official portal ↗", "官方入口 ↗", lambda: webbrowser.open("https://www.pushplus.plus/")
        )
        try:
            configured = bool(self.secrets.get("pushplus"))
        except Exception:
            configured = False
        label(
            self.body,
            self.tr(
                "Windows-encrypted token saved" if configured else "No token saved",
                "已用 Windows 加密保存 Token" if configured else "尚未保存 Token",
            ),
        )
        label(
            self.body,
            self.tr(
                "A successful API request is accepted, not confirmed delivered. Timeouts remain uncertain and are not blindly retried. No 24/7 guarantee: your computer must be awake and signed in. Scheduled monitoring must be enabled in Advanced settings to continue after closing this window.",
                "接口成功仅代表已接受请求，不代表微信已送达。超时保留为未确认，不盲目重试。电脑须唤醒并登录；关闭窗口后的检查需在高级设置启用计划监控，本程序不提供全天在线保证。",
            ),
        )
        label(
            self.body,
            self.tr(
                "Normal/exam schedules and deadline windows: Advanced settings → Schedule / Reminders.",
                "正常周／考试周计划及截止窗口：高级设置 → 检查计划／提醒。",
            ),
        )
        for event in self.events[:12]:
            if event["code"].startswith(("notification_", "pushplus_")):
                label(
                    self.body,
                    f"{local_time_label(event['at'], self.config['timezone'])} · {event['code']} · {event['detail']}",
                )

    def bind_pushplus(self):
        value = self.push_token.get().strip()
        if not value:
            return
        try:
            with ProcessLock(self.data_root):
                self.secrets.set("pushplus", value)
            channels = sorted(set(self.config["channels"]) | {"pushplus"})
            self.persist({"channels": channels})
            self.push_token.set("")
            self.refresh()
        except Exception:
            messagebox.showerror(
                "PushPlus",
                self.tr(
                    "Windows credential protection failed; token was not stored as plaintext.",
                    "Windows 凭据保护失败；未降级为明文存储。",
                ),
            )

    def unbind_pushplus(self):
        with ProcessLock(self.data_root):
            self.secrets.set("pushplus", "")
        self.persist(
            {
                "channels": [c for c in self.config["channels"] if c != "pushplus"] or ["windows"],
                "weekly_channels": [c for c in self.config["weekly_channels"] if c != "pushplus"]
                or ["windows"],
            }
        )
        self.refresh()

    def push_status(self):
        self.status.set(
            self.tr(
                "Configured locally; account binding, quota and actual delivery require your test.",
                "本地配置可用；账号绑定、额度与实际送达需由你测试。",
            )
            if self.secrets.get("pushplus")
            else self.tr("Not configured", "尚未配置")
        )

    def test_pushplus(self):
        if messagebox.askyesno(
            "PushPlus",
            self.tr(
                "Send one test message to your personal PushPlus account?",
                "向你的个人 PushPlus 账号发送一条测试消息？",
            ),
        ):
            from secrets import token_hex

            from .notifications import Dispatcher, PushPlusChannel
            from .rules import Message

            def operation():
                with ProcessLock(self.data_root):
                    store = Store(self.data_root)
                    try:
                        dispatcher = Dispatcher(
                            store,
                            {"pushplus": PushPlusChannel(self.secrets.get("pushplus"))},
                            self.secrets.values(),
                            self.config["canvas_url"],
                        )
                        return dispatcher.send_result(
                            Message(
                                "test:" + token_hex(12), "Canvas Deadline Agent", "Test reminder / 测试提醒"
                            ),
                            ["pushplus"],
                            datetime.now(UTC),
                        )
                    finally:
                        store.close()

            self.work(
                operation,
                lambda r: self.status.set(
                    self.tr("Request result (delivery unconfirmed): ", "请求结果（送达未确认）：")
                    + r["status"]
                ),
            )

    def render_settings(self):
        self.heading("Make it yours", "按你的习惯设置")
        label(self.body, self.tr("Appearance", "外观"), "CardTitle.TLabel")
        row = Flow(self.body)
        row.pack(fill="x")
        self.button(row, "Warm Sage", "暖鼠尾草绿", lambda: self.set_theme("sage"))
        self.button(row, "Soft Pink", "柔粉色", lambda: self.set_theme("pink"))
        self.button(row, "中文 / English", "English / 中文", self.switch_language)
        label(
            self.body,
            self.tr(
                "Canvas Base URL (school instance, not an assignment page)",
                "Canvas Base URL（学校实例地址，不是作业页面）",
            ),
        )
        self.canvas_url = tk.StringVar(value=self.config["canvas_url"])
        ttk.Entry(self.body, textvariable=self.canvas_url).pack(fill="x", pady=6)
        label(
            self.body,
            self.tr(
                "Canvas Token · leave empty to keep the encrypted credential",
                "Canvas Token · 留空保留已加密凭据",
            ),
        )
        self.canvas_token = tk.StringVar()
        ttk.Entry(self.body, textvariable=self.canvas_token, show="•").pack(fill="x", pady=6)
        row = Flow(self.body)
        row.pack(fill="x")
        self.button(row, "Save Canvas", "保存 Canvas", self.save_canvas)
        self.button(row, "Verify identity", "验证账号", self.test_canvas)
        label(
            self.body,
            self.tr("Schedules, courses, AI and data maintenance", "计划、课程、AI 与数据维护"),
            "CardTitle.TLabel",
        )
        label(
            self.body,
            self.tr(
                "AI is optional and off by default. All core reminders work without an API key.",
                "AI 默认关闭且可选。核心提醒和作业管理无需 AI Key。",
            ),
        )
        ttk.Button(
            self.body, text=self.tr("Advanced settings…", "高级设置…"), command=self.open_advanced
        ).pack(anchor="w", pady=8)
        ttk.Button(
            self.body,
            text=self.tr("Import a v1.1 local backup…", "导入 v1.1 本地备份…"),
            command=self.import_legacy,
        ).pack(anchor="w", pady=8)
        label(
            self.body,
            self.tr(
                "Import is explicit. Credentials are excluded; monitoring stays off until reviewed.",
                "仅在你选择后导入。不导入凭据；复核前监控保持关闭。",
            ),
        )

    def save_canvas(self):
        from .config import https_url

        try:
            base = https_url(self.canvas_url.get())
            value = self.canvas_token.get().strip()
            changed = base != self.config["canvas_url"] or bool(value and value != self.secrets.get("canvas"))
            if value:
                with ProcessLock(self.data_root):
                    self.secrets.set("canvas", value)
            self.persist({"canvas_url": base})
            if changed:
                with ProcessLock(self.data_root):
                    store = Store(self.data_root)
                    try:
                        store.reset_account()  # local choices have a separate account namespace.
                    finally:
                        store.close()
            self.canvas_token.set("")
            self.status.set(self.tr("Saved. Verify identity, then sync.", "已保存。请验证账号，再同步。"))
            self.refresh()
        except Exception as error:
            self.status.set(self.tr("Save failed: ", "保存失败：") + type(error).__name__)

    def test_canvas(self):
        self.work(
            lambda: self.copilot.api().identity(),
            lambda _: self.status.set(self.tr("Canvas identity verified", "Canvas 账号验证成功")),
        )

    def sync(self):
        self.work(
            lambda: run(self.data_root),
            lambda r: self.status.set(self.tr("Sync: ", "同步结果：") + r["status"]),
        )

    def open_advanced(self):
        if self.advanced and self.advanced.winfo_exists():
            self.advanced.lift()
            return
        win = tk.Toplevel(self.root)
        self.advanced = win
        AdvancedApplication(win, self.data_root)

        def close():
            win.destroy()
            self.config = load(self.data_root / "config.json")
            self.lang = self.config["language"]
            self.build()

        win.protocol("WM_DELETE_WINDOW", close)

    def import_legacy(self):
        source = filedialog.askopenfilename(filetypes=[("Agent backup", "*.zip")])
        if not source:
            return
        if not messagebox.askyesno(
            self.tr("Import backup", "导入备份"),
            self.tr(
                "Back up current local state, then import the selected backup? Credentials are excluded; monitoring will be disabled.",
                "备份当前状态后导入所选备份？凭据不导入，监控将关闭。",
            ),
        ):
            return
        from .migration import import_backup

        self.work(lambda: import_backup(self.data_root, Path(source)), lambda _: self.reload())

    def reload(self):
        self.config = load(self.data_root / "config.json")
        self.lang = self.config["language"]
        self.build()
