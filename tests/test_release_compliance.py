"""Release-boundary regressions: no renderer, native calls or external service requests."""

import json
from pathlib import Path
from types import SimpleNamespace

import collect_licenses as collector
import pytest
import release_compliance as policy
from test_license_collection import isolated  # noqa: F401 - reuse the original isolated fixture


@pytest.mark.parametrize(
    "name",
    [
        "PyInstaller",
        "PyInstaller.building.utils",
        "webview.__pyinstaller.hook-webview",
        "setuptools._vendor.autocommand",
    ],
)
def test_build_modules_are_not_runtime_modules(name):
    assert not policy.runtime_module(name)


@pytest.mark.parametrize("name", ["webview.platforms.edgechromium", "packaging.version", "pyimod01_archive"])
def test_do_not_remove_runtime_backends_or_bootloader_exception_modules(name):
    assert policy.runtime_module(name)


def test_windows_11_system_dlls_are_not_redistributed_but_TLS_is_preserved():
    rows = [
        ("api-ms-win-core-console-l1-1-0.dll", "unrelated/native/libheif/x.dll", "BINARY"),
        ("ucrtbase.dll", "unrelated/native/libheif/ucrtbase.dll", "BINARY"),
        ("_ssl.pyd", "python/_ssl.pyd", "EXTENSION"),
        ("libcrypto-3-x64.dll", "python/libcrypto-3-x64.dll", "BINARY"),
        ("VCRUNTIME140.dll", "python/VCRUNTIME140.dll", "BINARY"),
    ]
    retained, removed = policy.runtime_binaries(rows)
    assert retained == rows[2:] and len(removed) == 2
    with pytest.raises(ValueError, match="Unreviewed"):
        policy.runtime_binaries([("unexpected.dll", "native/libheif/bin/unexpected.dll", "BINARY")])


def test_record_relative_licenses_cannot_overwrite_another_original(isolated):  # noqa: F811 - imported fixture
    dist = isolated.packages["requests"]
    second = dist.locate_file(Path("vendor/LICENSE"))
    second.parent.mkdir()
    second.write_bytes(b"other copyright; distinct required original")
    dist.files.append(Path("vendor/LICENSE"))
    collector.collect_licenses(isolated.target, isolated.project, preserve_paths=True)
    assert (isolated.target / "requests/licenses/LICENSE").read_bytes() == b"synthetic package terms\n"
    assert (isolated.target / "requests/vendor/LICENSE").read_bytes() == second.read_bytes()


def test_missing_or_unsafe_declared_terms_fail_before_output(tmp_path):
    dist = SimpleNamespace(files=[Path("missing/LICENSE")], locate_file=lambda f: tmp_path / f)
    with pytest.raises(FileNotFoundError):
        policy.notice_records(dist)
    dist.files = [Path("../LICENSE")]
    with pytest.raises(ValueError, match="Unsafe"):
        policy.notice_records(dist)
    assert not (tmp_path / "output").exists()


def test_an_actual_additional_distribution_without_terms_is_rejected(tmp_path, monkeypatch):
    dist = SimpleNamespace(version="0.0", files=[])
    monkeypatch.setattr(policy, "actual_distributions", lambda *args: {"extra": dist})
    monkeypatch.setattr(policy.metadata, "distribution", lambda name: dist)
    with pytest.raises(ValueError, match="lacks complete original"):
        policy.collect_closure(tmp_path, tmp_path / "payload", tmp_path / "analysis")
    assert not (tmp_path / "payload").exists()


def test_release_archive_gate_refuses_unverified_native_components(tmp_path, monkeypatch):
    import prepare_release_candidate as builder

    monkeypatch.setattr(builder, "TARGET", tmp_path)
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/NATIVE_REDISTRIBUTION_GATE.json").write_text('{"status":"BLOCKED"}')
    with pytest.raises(ValueError, match="Native redistribution evidence incomplete"):
        builder.archives()
    assert not (tmp_path / "artifacts").exists()


def test_installer_opt_in_and_application_license_remain_explicit_draft():
    root = Path(collector.PROJECT_ROOT)
    script = (root / "installer/canvas-agent.iss").read_text(encoding="utf-8")
    line = next(s for s in script.splitlines() if 'Description: "Launch Canvas Deadline Agent"' in s)
    assert "unchecked" in line and "skipifsilent" in line
    assert "PrivilegesRequired=lowest" in script
    assert "NO PUBLIC LICENSE GRANT" in (root / "LICENSE").read_text(encoding="utf-8")
    draft = (root / "docs/LICENSE_SOURCE_AVAILABLE_DRAFT.md").read_text(encoding="utf-8")
    assert "NOT EFFECTIVE" in draft and "Schedule A" in draft


def test_all_supplemental_originals_are_hash_bound():
    import hashlib

    directory = Path(collector.PROJECT_ROOT) / "docs/third-party"
    manifest = json.loads((directory / "REDISTRIBUTION_SOURCES.json").read_text(encoding="utf-8"))
    assert not manifest["legal_approval"]
    assert any(x["destination"].startswith("sources/certifi-") for x in manifest["files"])
    for row in manifest["files"]:
        assert hashlib.sha256((directory / row["file"]).read_bytes()).hexdigest() == row["sha256"]


@pytest.mark.parametrize("kind,expected", [(".NET Framework", "passed"), ("unexpected runtime", "failed")])
def test_frozen_diagnostic_requires_actual_runtime_kind_and_always_releases_it(
    tmp_path, monkeypatch, kind, expected
):
    import sys

    import clr_loader

    from canvas_agent.release_check import check

    monkeypatch.setattr(
        "canvas_agent.release_check._native_dependency_check", lambda require: {"passed": True}
    )
    released = []
    runtime = SimpleNamespace(info=lambda: SimpleNamespace(kind=kind), shutdown=lambda: released.append(True))
    monkeypatch.setattr(clr_loader, "get_netfx", lambda: runtime)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    result = check(tmp_path / "isolated-runtime-check")
    assert result["status"] == expected
    assert released == [True]
