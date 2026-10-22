"""Independent channels, bounded safe messages, durable per-channel receipts."""

import html
import os
from xml.sax.saxutils import escape

from .pushplus import PushPlusChannel, PushPlusError
from .security import plain, plain_lines, redact, safe_link
from .windows_native import WindowsAPIError, apartment


class WindowsChannel:
    def send(self, title, body, url, important=False):
        if os.name != "nt":
            raise RuntimeError("Windows notifications unavailable")
        try:
            with apartment():
                from winrt.windows.data.xml.dom import XmlDocument
                from winrt.windows.ui.notifications import (
                    NotificationSetting,
                    ToastNotification,
                    ToastNotificationManager,
                    ToastNotificationPriority,
                )

                notifier = xml = toast = None
                try:
                    notifier = ToastNotificationManager.create_toast_notifier_with_id("CanvasDeadlineAgent")
                    if notifier.setting != NotificationSetting.ENABLED:
                        raise WindowsAPIError("windows_notifications_disabled")
                    xml = XmlDocument()
                    xml.load_xml(toast_xml(title, body, url, important))
                    toast = ToastNotification(xml)
                    if important:
                        toast.priority = ToastNotificationPriority.HIGH
                    notifier.show(toast)
                finally:
                    toast = xml = notifier = None
        except WindowsAPIError:
            raise
        except (OSError, ImportError, TypeError, RuntimeError) as e:
            raise WindowsAPIError("windows_notification_failed", getattr(e, "winerror", None)) from None


def toast_xml(title, body, url, important=False):
    """Only data is embedded in XML. No script, encoded command or child process."""
    duration = "long" if important else "short"
    launch = f' launch="{escape(url, {chr(34): "&quot;"})}" activationType="protocol"' if url else ""
    return (
        f'<toast duration="{duration}"{launch}><visual><binding template="ToastGeneric">'
        f"<text>{escape(title[:100])}</text><text>{escape(body[:4000])}</text>"
        "</binding></visual></toast>"
    )


class Dispatcher:
    def __init__(self, store, channels, secrets, base):
        self.store, self.channels, self.secrets, self.base = store, channels, secrets, base

    def send(self, message, selected, now):
        return self.send_result(message, selected, now)["status"] == "accepted"

    def send_result(self, message, selected, now):
        if message.task_key:
            from .tracking import Tracking

            if not Tracking(self.store).active({"key": message.task_key}):
                return {"status": "suppressed", "channels": {name: "suppressed" for name in selected}}
            current = next((t for t in self.store.cached() if t["key"] == message.task_key), None)
            if current and current["status"] in ("Confirmed Submitted", "Graded"):
                return {"status": "suppressed", "channels": {name: "suppressed" for name in selected}}
        outcomes = {}
        title = redact(plain(message.title, 200), self.secrets)
        full = redact(plain_lines(message.body, 12000), self.secrets)
        body = full[:11500] + (
            "\n[Truncated; see application / 内容截断，请查看应用]" if len(full) > 11500 else ""
        )
        url = safe_link(message.url, self.base)
        expected_account = self.store.get("account")
        for name in selected:
            if (
                message.weekly
                and message.tracking_revision is not None
                and (
                    self.store.get("account") != expected_account
                    or self.store.get("tracking_revision", 0) != message.tracking_revision
                )
            ):
                outcomes[name] = "suppressed"
                continue
            # A queued second channel must see choices made while the first channel was sending.
            if message.task_key:
                from .tracking import Tracking

                current = next((t for t in self.store.cached() if t["key"] == message.task_key), None)
                if (
                    self.store.get("account") != expected_account
                    or not Tracking(self.store).active({"key": message.task_key})
                    or (current and current["status"] in ("Confirmed Submitted", "Graded"))
                ):
                    outcomes[name] = "suppressed"
                    continue
            task_receipt = "task_delivery:" + name + ":" + message.task_key
            previous = self.store.get(task_receipt) if message.task_key else None
            if (
                previous
                and not message.key.startswith(("guardian:", "task_change:"))
                and 0 <= now.timestamp() - previous < 900
            ):
                outcomes[name] = "already_accepted"
                continue
            channel = self.channels.get(name)
            if isinstance(channel, PushPlusChannel):
                import hashlib

                scope = hashlib.sha256((channel.token or "").encode()).hexdigest()
                budget = self.store.get("pushplus_budget", {})
                if budget.get("scope") != scope or budget.get("day") != now.date().isoformat():
                    budget = {
                        "scope": scope,
                        "day": now.date().isoformat(),
                        "count": 0,
                        "recent": [],
                        "blocked": False,
                    }
                recent = [at for at in budget["recent"] if 0 <= now.timestamp() - at < 60]
                if budget["blocked"] or budget["count"] >= 200 or len(recent) >= 5:
                    outcomes[name] = "rate_limited_or_restricted"
                    self.store.event("pushplus_deferred", "local_rate_or_account_gate")
                    continue
            if not self.store.claim(message.key, name, now):
                outcomes[name] = (
                    "already_accepted"
                    if self.store.delivery_status(message.key, name) == "sent"
                    else "uncertain"
                )
                continue
            try:
                if not channel:
                    raise RuntimeError("Channel unavailable")
                if isinstance(channel, PushPlusChannel):
                    budget["recent"], budget["count"] = recent + [now.timestamp()], budget["count"] + 1
                    self.store.set("pushplus_budget", budget)
                channel.send(html.unescape(title), html.unescape(body), url, message.important)
            except PushPlusError as error:
                self.store.receipt(message.key, name, False, now)
                if not error.retryable:
                    with self.store.db:
                        self.store.db.execute(
                            "UPDATE delivery SET status='rejected' WHERE key=? AND channel=?",
                            (message.key, name),
                        )
                    if isinstance(channel, PushPlusChannel):
                        budget["blocked"] = True
                        self.store.set("pushplus_budget", budget)
                self.store.event("pushplus_rejected", error.code)
                outcomes[name] = error.code
            except Exception as error:
                # Network ambiguity remains uncertain to prevent accidental duplicate delivery.
                detail = name
                if isinstance(error, WindowsAPIError):
                    detail += ":" + error.code
                    if error.hresult is not None:
                        detail += f":0x{error.hresult:08X}"
                self.store.event("notification_failed_or_uncertain", detail)
                outcomes[name] = "uncertain"
            else:
                self.store.receipt(message.key, name, True, now)
                self.store.event("notification_accepted", name)
                if message.task_key:
                    self.store.set(task_receipt, now.timestamp())
                outcomes[name] = "accepted"
        accepted = bool(outcomes) and all(
            result in ("accepted", "already_accepted") for result in outcomes.values()
        )
        return {"status": "accepted" if accepted else "uncertain", "channels": outcomes}
