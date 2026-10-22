"""Explicit isolated, offline GUI smoke. Never reads an existing user profile."""

from datetime import UTC, datetime, timedelta

from . import __version__
from .desktop import NAV
from .models import Snapshot, Status, Task
from .storage import Store


def run_gui_smoke(app):
    root, data = app.root, app.data_root
    now = datetime.now(UTC)
    tasks = [
        Task(
            f"1:assignment:{i}",
            1,
            "MOCK1001",
            title,
            "assignments",
            (now + timedelta(minutes=minutes)).isoformat(),
            Status.NOT_SUBMITTED,
            "",
        )
        for i, title, minutes in (
            (1, "Synthetic urgent assignment / 合成紧急作业", 40),
            (2, "Synthetic group project / 合成小组任务", 1440),
        )
    ]
    store = Store(data)
    try:
        store.set("account", "synthetic-smoke-account")
        store.snapshot(Snapshot([{"id": 1, "name": "MOCK1001"}], tasks, [], [(1, "assignments")], []), now)
    finally:
        store.close()
    failures = []
    root.report_callback_exception = lambda kind, error, trace: failures.append(kind.__name__)
    checks = []
    for scale in (1.33, 2.0, 2.66):
        root.tk.eval("tk scaling " + str(scale))
        root.geometry("1000x760")
        for language in ("en", "zh"):
            app.lang = language
            for theme in ("sage", "pink"):
                app.config = app.config | {"theme": theme, "language": language}
                app.build()
                for key, _, _ in NAV:
                    app.navigate(key)
                    root.update()
                    visible = all(
                        b.winfo_ismapped() and b.winfo_reqwidth() <= b.winfo_width()
                        for b in app.nav_buttons.values()
                    )
                    checks.append(
                        {
                            "scale": scale,
                            "language": language,
                            "theme": theme,
                            "page": key,
                            "navigation_visible": bool(visible),
                        }
                    )
    app.persist({"theme": "pink", "language": "zh"})
    app.navigate("assignments")
    app.mark(app.rows[0], "ignored")
    app.set_filter("ignored")
    ignored = len(app.visible_rows) == 1
    app.mark(app.visible_rows[0], "tracking")
    app.navigate("today")
    restored = len(app.visible_rows) == 2
    app.show_details(app.rows[0])
    root.update()
    drawer = bool(app.drawer.winfo_ismapped())
    return {
        "version": __version__,
        "status": "passed"
        if ignored and restored and drawer and not failures and all(c["navigation_visible"] for c in checks)
        else "failed",
        "pages": 5,
        "layouts": checks,
        "ignored_filter": ignored,
        "restore": restored,
        "drawer": drawer,
        "callback_errors": failures,
        "network": "not_used",
        "account": "synthetic_only",
    }
