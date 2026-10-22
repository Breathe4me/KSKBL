"""Preview export and portable entry checks without loading CLR, GUI or real services."""

import json

import export_ui_preview
import pytest
import ui_review_entry


def test_html_uses_current_frontend_and_explicit_mock(tmp_path):
    file = tmp_path / "UI-Preview.html"
    record = export_ui_preview.export(file)
    source = file.read_text(encoding="utf-8")
    for relative in ("frontend/app.js", "frontend/app.css", "frontend/prototype.css"):
        assert (export_ui_preview.PROJECT / relative).read_text(encoding="utf-8") in source
    assert "Browser Mock Adapter" in source and "BROWSER MOCK" in source
    assert "__QA_FIXTURE__" not in source and "https://cdn" not in source
    assert record["credentials"] == "none"
    with pytest.raises(FileExistsError):
        export_ui_preview.export(file)


def test_portable_only_uses_marked_synthetic_data(tmp_path):
    root = tmp_path / "qa-profile"
    ui_review_entry.prepare_qa_root(root)
    assert json.loads((root / "QA_ONLY.json").read_text(encoding="utf-8"))["mode"] == "synthetic_only"
    assert ui_review_entry.prepare_qa_root(root) == root
    other = tmp_path / "unrelated"
    other.mkdir()
    (other / "sentinel.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="unmarked"):
        ui_review_entry.prepare_qa_root(other)
    assert (other / "sentinel.txt").read_text(encoding="utf-8") == "preserve"


def test_portable_missing_runtime_reports_error_without_window(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ui_review_entry, "webview_runtime", lambda: {"available": False, "reason": "missing"})
    monkeypatch.setattr(ui_review_entry, "launch", lambda *args, **kwargs: pytest.fail("GUI forbidden"))
    root = tmp_path / "qa-profile"
    assert ui_review_entry.main(["--mock", "--data-dir", str(root)]) == 2
    assert "No automatic download" in capsys.readouterr().err
    assert (root / "startup-error.json").is_file()


def test_portable_preflight_does_not_create_profile_or_gui(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ui_review_entry, "webview_runtime", lambda: {"available": True, "version": "155.0.0.0"}
    )
    monkeypatch.setattr(ui_review_entry, "launch", lambda *args, **kwargs: pytest.fail("GUI forbidden"))
    root = tmp_path / "unused"
    assert ui_review_entry.main(["--preflight-only", "--data-dir", str(root)]) == 0
    assert not root.exists()
