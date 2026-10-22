"""Construct real widgets without a real account, external request, or scheduled task."""

import tkinter as tk

import pytest

from canvas_agent.gui import SAVED_SECRET_MASK, Application
from canvas_agent.safe_tk import SafeTk


@pytest.fixture(scope="session")
def tk_root():
    root = SafeTk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def ui(tmp_path, tk_root):
    root = tk_root
    app = Application(root, tmp_path)
    yield app
    for timer in root.tk.call("after", "info"):
        root.after_cancel(timer)
    for child in root.winfo_children():
        child.destroy()


def test_real_gui_defaults_and_collect(ui):
    assert len(ui.notebook.tabs()) == 7
    assert ui.window_choice.get() == "48 Hours"
    c = ui.collect()
    assert c["strong_hours"] == 48 and c["ai_enabled"] is False
    assert c["normal_times"] == ["10:00", "18:00"]
    assert c["overdue_days"] == 7


@pytest.mark.parametrize("scaling", [1.33, 2.0, 2.66])
@pytest.mark.parametrize("language", ["en", "zh"])
def test_save_all_stays_visible_on_all_tabs_in_small_scaled_window(ui, scaling, language, monkeypatch):
    root = ui.root
    original_scaling = float(root.tk.call("tk", "scaling"))
    saves = []
    monkeypatch.setattr(ui, "save_settings", lambda: saves.append(ui.collect()))
    try:
        root.tk.call("tk", "scaling", scaling)
        if ui.lang != language:
            ui.switch_language()
        else:
            ui.outer.destroy()
            ui.vars, ui.secret_vars, ui.time_lists = {}, {}, {}
            ui.build()
        root.geometry("900x700")
        root.deiconify()
        root.update()
        ui.status.set("Settings status / 设置状态 " * 10)
        for tab in ui.notebook.tabs():
            ui.notebook.select(tab)
            root.update()
            button = ui.save_all_button
            assert button.winfo_ismapped()
            left = button.winfo_rootx() - root.winfo_rootx()
            top = button.winfo_rooty() - root.winfo_rooty()
            assert 0 <= left and left + button.winfo_width() <= root.winfo_width()
            assert 0 <= top and top + button.winfo_height() <= root.winfo_height()
        ui.save_all_button.invoke()
        assert len(saves) == 1 and saves[0]["language"] == language
    finally:
        root.withdraw()
        root.tk.call("tk", "scaling", original_scaling)


def test_preset_ignores_invalid_custom_box(ui):
    ui.window_choice.set("24 Hours")
    ui.vars["strong_hours"].set("")
    assert ui.collect()["strong_hours"] == 24
    ui.window_choice.set("Custom")
    with pytest.raises(ValueError):
        ui.collect()


def test_language_switch_and_course_selection(ui):
    ui.switch_language()
    assert ui.lang == "zh" and len(ui.notebook.tabs()) == 7
    assert ui.collect()["language"] == "zh"
    ui.fill_courses([{"id": 1, "name": "COMP1234 One"}, {"id": 2, "name": "INFO1234 Two"}])
    first = ui.course_tree.get_children()[0]
    ui.course_tree.selection_set(first)
    ui.toggle_course(None)
    assert ui.config["course_ids"] == [2]


def test_schedule_edit_and_restore(ui):
    ui.time_lists["normal_times"].delete(0, "end")
    ui.time_lists["normal_times"].insert("end", "09:25")
    assert ui.collect()["normal_times"] == ["09:25"]
    ui.reset_schedule()
    assert ui.collect()["normal_times"] == ["10:00", "18:00"]


def test_saved_credential_shows_state_after_save_and_language_rebuild(ui, monkeypatch):
    monkeypatch.setattr("canvas_agent.gui.remove_task", lambda root: None)
    ui.work = lambda operation, callback: callback(operation())
    ui.secret_vars["pushplus"].set("synthetic-pushplus-credential")
    assert "New value" in ui.credential_status["pushplus"].get()
    ui.save_settings()
    assert ui.secret_vars["pushplus"].get() == SAVED_SECRET_MASK
    assert "Saved" in ui.credential_status["pushplus"].get()
    assert "synthetic-pushplus" not in ui.credential_status["pushplus"].get()
    assert ui.secrets.get("pushplus") == "synthetic-pushplus-credential"
    ui.switch_language()
    assert "已保存" in ui.credential_status["pushplus"].get()
    assert ui.secret_vars["pushplus"].get() == SAVED_SECRET_MASK


def test_unsaved_credential_is_preserved_when_switching_language(ui):
    ui.secret_vars["ai"].set("synthetic-pending-ai")
    ui.switch_language()
    assert ui.secret_vars["ai"].get() == "synthetic-pending-ai"
    assert "保存设置后生效" in ui.credential_status["ai"].get()


def test_dashboard_counts_selected_academic_courses_and_filters_old_cache(ui, task, now):
    from dataclasses import replace

    from canvas_agent.models import Snapshot
    from canvas_agent.storage import Store

    courses = [
        {"id": 1, "name": "COMP1234 Course"},
        {"id": 2, "name": "INFO1234 Other"},
        {"id": 3, "name": "Academic Honesty Training"},
    ]
    store = Store(ui.data_root)
    try:
        store.set("course_catalog", courses)
        store.snapshot(
            Snapshot(
                courses,
                [task, replace(task, key="3:assignment:9", course_id=3)],
                [],
                [(1, "assignments"), (3, "assignments")],
                [],
            ),
            now,
        )
    finally:
        store.close()
    ui.config["course_ids"] = [1, 3]
    ui.refresh()
    assert len(ui.course_rows) == 2 and len(ui.task_rows) == 1
    assert "Monitored courses: 1" in ui.summary.get()


def test_masked_saved_fields_are_not_written_as_new_credentials(ui, monkeypatch):
    monkeypatch.setattr("canvas_agent.gui.remove_task", lambda root: None)
    ui.work = lambda operation, callback: callback(operation())
    ui.secrets.set("canvas", "synthetic-saved-canvas")
    ui.secrets.set("pushplus", "synthetic-saved-pushplus")
    for name in ("canvas", "pushplus"):
        ui.restore_secret_placeholder(name)
        assert ui.secret_vars[name].get() == SAVED_SECRET_MASK
        assert ui.secret_input(name) == ""
    before = (ui.data_root / "canvas.dpapi").read_bytes()
    ui.save_settings()
    ui.save_settings()
    assert (ui.data_root / "canvas.dpapi").read_bytes() == before
    assert ui.secrets.get("canvas") == "synthetic-saved-canvas"
    assert ui.secrets.get("pushplus") == "synthetic-saved-pushplus"


def test_saved_mask_click_replace_and_blur_restore(ui, monkeypatch):
    monkeypatch.setattr("canvas_agent.gui.remove_task", lambda root: None)
    ui.work = lambda operation, callback: callback(operation())
    ui.secrets.set("ai", "synthetic-old-ai")
    ui.restore_secret_placeholder("ai")
    entries = []

    def visit(widget):
        if widget.winfo_class() == "TEntry" and str(widget.cget("textvariable")) == str(ui.secret_vars["ai"]):
            entries.append(widget)
        for child in widget.winfo_children():
            visit(child)

    visit(ui.tabs["ai"])
    assert len(entries) == 1
    entries[0].event_generate("<FocusIn>")
    assert ui.secret_vars["ai"].get() == ""
    entries[0].event_generate("<FocusOut>")
    assert ui.secret_vars["ai"].get() == SAVED_SECRET_MASK
    entries[0].event_generate("<FocusIn>")
    ui.secret_vars["ai"].set("synthetic-replacement-ai")
    ui.save_settings()
    assert ui.secrets.get("ai") == "synthetic-replacement-ai"
    assert ui.secret_vars["ai"].get() == SAVED_SECRET_MASK


def test_canvas_connection_test_uses_stored_key_instead_of_mask(ui, monkeypatch):
    captured = []
    ui.vars["canvas_url"].set("https://canvas.example")
    ui.secrets.set("canvas", "synthetic-actual-canvas")
    ui.restore_secret_placeholder("canvas")
    from canvas_agent.models import Snapshot

    class API:
        def __init__(self, base, token):
            captured.append(token)

        def identity(self):
            return "synthetic-user"

        def courses(self, ended):
            return []

        def sync(self, courses):
            return Snapshot([], [], [], [], [])

    monkeypatch.setattr("canvas_agent.gui.CanvasAPI", API)
    ui.work = lambda operation, callback: callback(operation())
    ui.text_window = lambda *args: None
    ui.test_connection()
    assert captured == ["synthetic-actual-canvas"]


def test_dashboard_and_preview_treat_disabled_source_as_note(ui, task, now):
    from canvas_agent.models import Snapshot
    from canvas_agent.storage import Store

    cap = {"course_id": 1, "kind": "quizzes", "state": "disabled_by_course", "code": "quiz_list_disabled"}
    store = Store(ui.data_root)
    try:
        store.snapshot(
            Snapshot(
                [{"id": 1, "name": "INFO5990"}],
                [task],
                [],
                [(1, "assignments"), (1, "announcements")],
                [],
                [cap],
            ),
            now,
        )
    finally:
        store.close()
    ui.refresh()
    assert "Assignments and announcements synchronized" in ui.summary.get()
    assert "INCOMPLETE" not in ui.summary.get()
    windows = []
    ui.text_window = lambda title, body: windows.append(body)
    ui.view_weekly()
    ui.view_sources()
    assert "Data incomplete" not in windows[0] and "独立测验无法保证全量枚举" in windows[0]
    assert "Course data sources are checked again on every sync" in windows[1]


def test_check_now_does_not_show_raw_coverage_json(ui, monkeypatch):
    monkeypatch.setattr(
        "canvas_agent.gui.run",
        lambda root: {"status": "limited", "complete": False, "tasks": 48, "capabilities": [{}]},
    )
    ui.work = lambda operation, callback: callback(operation())
    ui.check_now()
    assert ui.status.get() == "Synchronized 48 tasks; 1 data source notes."


def test_clock_last_check_and_task_timestamps_use_sydney(ui, task, monkeypatch):
    from datetime import UTC, datetime

    from canvas_agent.models import Snapshot
    from canvas_agent.storage import Store

    class Clock(datetime):
        value = datetime(2026, 10, 20, 7, 28, tzinfo=UTC)

        @classmethod
        def now(cls, zone):
            return cls.value.astimezone(zone)

    monkeypatch.setattr("canvas_agent.gui.datetime", Clock)
    store = Store(ui.data_root)
    try:
        store.snapshot(
            Snapshot([{"id": 1, "name": "INFO5990"}], [task], [], [(1, "assignments")], []),
            datetime(2026, 10, 20, 7, 18, tzinfo=UTC),
        )
    finally:
        store.close()
    ui.refresh()
    assert "18:28:00 AEDT" in ui.local_clock.get()
    assert "Last check (local): 2026-10-20 18:18:00 AEDT" in ui.summary.get()
    values = ui.task_tree.item(ui.task_tree.get_children()[0], "values")
    assert values[-1] == "2026-10-20 18:18 AEDT"
    Clock.value = datetime(2026, 10, 20, 7, 29, tzinfo=UTC)
    ui.refresh_clock()
    assert "18:29:00 AEDT" in ui.local_clock.get()
    assert "18:18:00 AEDT" in ui.summary.get()


def test_saving_timezone_rebases_schedule_without_touching_credentials(ui, monkeypatch):
    from canvas_agent.storage import Store

    monkeypatch.setattr("canvas_agent.gui.remove_task", lambda root: None)
    ui.work = lambda operation, callback: callback(operation())
    ui.secrets.set("pushplus", "synthetic-retained-pushplus")
    before = (ui.data_root / "pushplus.dpapi").read_bytes()
    ui.vars["timezone"].set("UTC")
    ui.save_settings()
    assert ui.config["timezone"] == "UTC"
    assert (ui.data_root / "pushplus.dpapi").read_bytes() == before
    store = Store(ui.data_root)
    try:
        assert store.get("schedule_effective_from")
        assert store.get("needs_retry") is False
    finally:
        store.close()


def test_copilot_context_prompt_copy_and_revoke(ui):
    from test_v11_copilot import API

    from canvas_agent.assignment_context import fetch_context

    ui.copilot.show_context(fetch_context(API(), 1, 2, "COMP1234"))
    assert len(ui.notebook.tabs()) == 7
    assert "Correctness" in ui.copilot.context_text.get("1.0", "end")
    ui.copilot.copy_prompt()
    assert ui.root.clipboard_get() == ui.copilot.prompt_text.get("1.0", "end-1c")
    assert "Do not submit" in ui.root.clipboard_get()
    assert not ui.copilot.access.paths
    ui.copilot.revoke()


def test_copilot_local_grant_preview_then_explicit_send_only(ui, tmp_path, monkeypatch):
    from test_v11_copilot import API

    from canvas_agent.assignment_context import fetch_context
    from canvas_agent.copilot_gui import cloud_preview

    ui.copilot.show_context(fetch_context(API(), 1, 2, "COMP1234"))
    path = tmp_path / "selected.py"
    path.write_text("# Authorized text only", encoding="utf-8")
    monkeypatch.setattr("canvas_agent.copilot_gui.filedialog.askopenfilenames", lambda **kw: [str(path)])
    monkeypatch.setattr("canvas_agent.copilot_gui.messagebox.askyesno", lambda *a, **kw: True)
    ui.work = lambda operation, callback: callback(operation())
    ui.copilot.grant(False)
    ui.copilot.local_review()
    sent = []
    monkeypatch.setattr(
        "canvas_agent.copilot_gui.AIClient.request_json",
        lambda self, instruction, text: sent.append(text) or {"status": "ok", "value": {}},
    )
    ui.config.update(ai_enabled=True, ai_consent=True)
    ui.work_ai = lambda operation, callback: callback(operation())
    ui.text_window = lambda *a: None
    ui.copilot.preview_cloud()
    assert not sent  # opening the preview must never transmit
    preview = [w for w in ui.copilot.window.winfo_children() if isinstance(w, tk.Toplevel)][0]
    button = [w for w in preview.winfo_children() if w.winfo_class() == "TButton"][0]
    button.invoke()
    assert sent == [cloud_preview(ui.copilot.context, ui.copilot.review_result, ui.secrets.values())]
    ui.copilot.revoke()
    assert not ui.copilot.access.paths and ui.copilot.review_result is None


def test_copilot_guardian_and_announcement_panels_construct(ui):
    ui.copilot.guardian_window()
    ui.copilot.announcements_window()
    assert ui.collect()["guardian_minutes"] == 60
    assert ui.collect()["guardian_repeat_minutes"] == 15
    assert len([w for w in ui.root.winfo_children() if isinstance(w, tk.Toplevel)]) == 2


def test_emergency_panel_displays_latest_unknown_instead_of_cached_confirmation(ui, task, now):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    from canvas_agent.models import Snapshot
    from canvas_agent.storage import Store

    state = Store(ui.data_root)
    try:
        state.snapshot(
            Snapshot(
                [{"id": 1}],
                [replace(task, due=(datetime.now(UTC) + timedelta(minutes=30)).isoformat())],
                [],
                [(1, "assignments")],
                [],
            ),
            now,
        )
        state.set("verification:" + task.key, {"status": "Unknown / Unable to Verify"})
    finally:
        state.close()
    ui.copilot.guardian_window()
    trees = []

    def visit(widget):
        if widget.winfo_class() == "Treeview":
            trees.append(widget)
        for child in widget.winfo_children():
            visit(child)

    window = [w for w in ui.root.winfo_children() if isinstance(w, tk.Toplevel)][0]
    visit(window)
    assert trees[0].item(trees[0].get_children()[0], "values")[-1] == "Unknown / Unable to Verify"
