"""Release mode/identity/isolation; no desktop, system task or external-service operation."""

import json
import sys

import pytest
import release_entry
from build_manifest import source_snapshot

from canvas_agent import app, release_info
from canvas_agent.release_check import check, readback
from canvas_agent.web_bridge import Bridge


def test_release_default_invokes_production_app_without_appending_qa(monkeypatch):
    calls = []
    monkeypatch.setattr(app, "main", lambda: calls.append(sys.argv[1:]) or 0)
    assert release_entry.entry([]) == 0
    assert calls == [[]]


@pytest.mark.parametrize("flag", sorted(release_entry.DEVELOPMENT_FLAGS))
def test_release_rejects_development_modes_before_app_or_renderer(monkeypatch, flag):
    monkeypatch.setattr(app, "main", lambda: pytest.fail("GUI must not be reached"))
    assert release_entry.entry([flag]) == 2
    assert release_entry.entry([flag + "=true"]) == 2


def test_release_identity_comes_from_packaged_metadata_and_is_validated(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    file = tmp_path / "release-info.json"
    file.write_text(json.dumps({"version": "1.2.0-beta.1"}))
    assert release_info.version() == "1.2.0-beta.1"
    file.write_text(json.dumps({"version": "untrusted arbitrary input"}))
    with pytest.raises(ValueError):
        release_info.version()


def test_real_production_first_run_and_DPAPI_restart_check(tmp_path):
    root = tmp_path / "isolated-release"
    result = check(root)
    assert result["status"] == "passed" and result["production_default"]
    assert len(result["cases"]) == 4 and result["forbidden_gui_imports"] == []
    assert readback(root)["status"] == "passed"
    assert not (root / "QA_ONLY.json").exists()
    assert Bridge(root, qa=False).invoke("get_state", {})["data"]["tasks"] == []


def test_release_selfcheck_preserves_nonempty_directories_and_rejects_unmarked_readback(tmp_path):
    file = tmp_path / "config.json"
    file.write_text("preserve")
    assert release_entry.entry(["--release-selfcheck", "startup", "--data-dir", str(tmp_path)]) == 2
    assert file.read_text() == "preserve"
    assert release_entry.entry(["--release-selfcheck", "readback", "--data-dir", str(tmp_path)]) == 2


def test_release_outputs_and_coverage_are_not_source_archive_inputs(tmp_path):
    from prepare_release_candidate import TARGET, VERSION

    assert TARGET.name == "v" + VERSION
    (tmp_path / "source.py").write_text("pass")
    (tmp_path / ".coverage").write_bytes(b"not source")
    output = tmp_path / "release-prep/v1.2.0-beta.1"
    output.mkdir(parents=True)
    (output / "secret.dpapi").write_bytes(b"not a real credential")
    assert set(source_snapshot(tmp_path)) == {"source.py"}
