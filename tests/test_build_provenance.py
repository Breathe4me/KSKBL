"""Provenance/archiving tests use synthetic text bytes, never a real installer or compiler."""

import json
import zipfile

import pytest
from build_manifest import file_hash, finalize, prepare, source_snapshot
from deliver_v11 import archive


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    monkeypatch.setattr("build_manifest.importlib.metadata.version", lambda _: "synthetic-version")
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("# source v1")
    (project / ".git").write_text("private worktree pointer")
    value = project / "build-candidates/batch-1"
    prepare(project, value, "1.1.0-auditfix-batch1")
    payload = value / "payload/CanvasDeadlineAgent"
    payload.mkdir(parents=True)
    (payload / "CanvasDeadlineAgent.exe").write_bytes(b"synthetic, not executable")
    (payload / "dependency.dll").write_bytes(b"synthetic dependency")
    (value / "CanvasDeadlineAgent-Setup-v1.1.0.exe").write_bytes(b"synthetic installer, not executable")
    return project, value


def test_manifest_binds_source_full_payload_installer_and_build_identity(candidate):
    project, value = candidate
    finalize(project, value)
    result = json.loads((value / "BUILD_MANIFEST.json").read_text())
    assert result["formal_release_allowed"] is False
    assert result["build"]["build_id"] == "1.1.0-auditfix-batch1"
    assert set(result["payload_files"]) == {"CanvasDeadlineAgent.exe", "dependency.dll"}
    assert result["installer"]["sha256"] == file_hash(value / result["installer"]["name"])
    assert ".git" not in result["source"]["files"]
    assert source_snapshot(project) == result["source"]["files"]
    assert "1.1.0-auditfix-batch1" in (value / "version-info.txt").read_text()


def test_build_source_change_fails_before_manifest_is_written(candidate):
    project, value = candidate
    (project / "main.py").write_text("# changed while compiler ran")
    with pytest.raises(ValueError, match="Source changed"):
        finalize(project, value)
    assert not (value / "BUILD_MANIFEST.json").exists()


def test_archiver_refuses_historic_release_path_without_writing(tmp_path):
    project = tmp_path / "project"
    old = project / "releases/v1.1.0"
    old.mkdir(parents=True)
    sentinel = old / "old.exe"
    sentinel.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="isolated development"):
        archive(old, project)
    assert sentinel.read_bytes() == b"preserve" and len(list(old.iterdir())) == 1


@pytest.mark.parametrize("tamper", ["changed", "extra"])
def test_tampered_or_extra_payload_is_rejected_before_any_archive(candidate, tamper):
    project, value = candidate
    finalize(project, value)
    target = value / "payload/CanvasDeadlineAgent"
    (target / ("dependency.dll" if tamper == "changed" else "unexpected.dll")).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        archive(value, project)
    assert not list(value.glob("*.zip"))


def test_candidate_archives_are_exact_and_never_overwritten(candidate):
    project, value = candidate
    finalize(project, value)
    hashes = archive(value, project)
    assert len(hashes) == 3
    with zipfile.ZipFile(value / "CanvasDeadlineAgent-Portable-v1.1.0.zip") as zipped:
        assert zipped.testzip() is None and len(zipped.namelist()) == 2
    with zipfile.ZipFile(value / "CanvasDeadlineAgent-Source-v1.1.0.zip") as zipped:
        assert zipped.namelist() == ["canvas-deadline-agent-v1.1/main.py"]
    with pytest.raises(FileExistsError):
        archive(value, project)
    assert hashes["CanvasDeadlineAgent-Portable-v1.1.0.zip"] == file_hash(
        value / "CanvasDeadlineAgent-Portable-v1.1.0.zip"
    )
