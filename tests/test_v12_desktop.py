"""Real Tk widgets, synthetic data; new shell coverage complements unchanged legacy tests."""

import pytest

from canvas_agent.config import load, save
from canvas_agent.desktop import NAV, Application
from canvas_agent.safe_tk import SafeTk
from canvas_agent.storage import Store


@pytest.fixture(scope="session")
def desktop_root():
    root = SafeTk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def desktop(tmp_path, desktop_root):
    root = desktop_root
    callback_errors = []
    root.report_callback_exception = lambda kind, error, trace: callback_errors.append((kind, str(error)))
    app = Application(root, tmp_path)
    yield app
    for timer in root.tk.call("after", "info"):
        root.after_cancel(timer)
    for child in root.winfo_children():
        child.destroy()
    assert not callback_errors


@pytest.mark.parametrize("theme", ["sage", "pink"])
@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("scaling", [1.33, 2.0, 2.66])
def test_five_pages_real_widgets_at_common_dpi(desktop, theme, language, scaling):
    app = desktop
    root = app.root
    root.tk.call("tk", "scaling", scaling)
    app.lang = language
    app.persist({"language": language, "theme": theme})
    app.build()
    root.geometry("1000x760")
    root.deiconify()
    for key, _, _ in NAV:
        app.navigate(key)
        root.update()
        assert len(app.nav_buttons) == 5
        assert app.nav_buttons[key].winfo_ismapped()
        assert app.scroll.canvas.winfo_width() > 380
        assert (
            app.progress.winfo_rootx() + app.progress.winfo_width() <= root.winfo_rootx() + root.winfo_width()
        )
        assert app.nav_buttons[key].winfo_reqwidth() <= app.nav_buttons[key].winfo_width()
    assert load(app.data_root / "config.json")["theme"] == theme
    assert load(app.data_root / "config.json")["language"] == language


def test_theme_and_language_survive_new_application(tmp_path, desktop_root):
    from canvas_agent.config import DEFAULTS

    save(tmp_path / "config.json", DEFAULTS | {"theme": "pink", "language": "zh"})
    import tkinter as tk

    root = tk.Toplevel(desktop_root)
    try:
        app = Application(root, tmp_path)
        assert app.config["theme"] == "pink" and app.lang == "zh"
        assert app.palette["bg"] == "#FFF1F5"
        assert app.nav_buttons["today"].cget("text") == "今日概览"
    finally:
        root.destroy()


def test_drawer_mark_restore_filters_and_canvas_label(desktop, task, now):
    from test_v12_tracking import seed

    app = desktop
    store = Store(app.data_root)
    seed(store, task, now)
    store.close()
    app.refresh()
    app.root.update()
    app.show_details(app.rows[0])
    assert app.drawer.winfo_exists()
    app.mark(app.rows[0], "completed", "other_submission", "synthetic")
    assert not app.visible_rows
    app.navigate("assignments")
    app.set_filter("completed")
    assert len(app.visible_rows) == 1
    assert app.visible_rows[0]["status"] == "Confirmed Not Submitted"
    assert "has not confirmed" in app.local_label(app.visible_rows[0])
    app.mark(app.visible_rows[0], "ignored")
    app.set_filter("ignored")
    assert len(app.visible_rows) == 1
    app.mark(app.visible_rows[0], "tracking")
    app.navigate("today")
    assert len(app.visible_rows) == 1
