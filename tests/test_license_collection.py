"""License-only regression checks: no executable, installer, GUI or provider calls."""

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import collect_licenses as collector
import pytest

OFFICIAL_HASHES = {
    "pywinrt": "6e898069e8b3c6d8d23dc70ac7067cc2b7c9db14c36df873026758db82c0891d",
    "tcl": "c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16",
}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    project = tmp_path / "source"
    docs = project / "docs" / "third-party"
    shutil.copytree(collector.PROJECT_ROOT / "docs" / "third-party", docs)
    payload = tmp_path / "derived" / "CanvasDeadlineAgent"
    init = payload / "_internal" / "_tcl_data" / "init.tcl"
    init.parent.mkdir(parents=True)
    init.write_text("package require -exact Tcl 8.6.12\n", encoding="utf-8")
    binaries = {}
    for name in ("CanvasDeadlineAgent.exe", "dependency.dll", "projection.pyd"):
        path = payload / name
        path.write_bytes(b"synthetic bytes, never executed: " + name.encode())
        binaries[path] = path.read_bytes()
    base = tmp_path / "python"
    base.mkdir()
    (base / "LICENSE.txt").write_bytes(b"synthetic Python license\r\n")
    monkeypatch.setattr(sys, "base_prefix", str(base))
    packages = {}
    for name in collector.PACKAGES:
        package = tmp_path / "packages" / name
        package.mkdir(parents=True)
        files = []
        if name == "requests":
            license_path = package / "licenses" / "LICENSE"
            license_path.parent.mkdir()
            license_path.write_bytes(b"synthetic package terms\n")
            files = [Path("licenses/LICENSE")]
        packages[name] = SimpleNamespace(
            version="3.2.1",
            files=files,
            locate_file=lambda entry, directory=package: directory / entry,
        )
    monkeypatch.setattr(collector.importlib.metadata, "distribution", packages.__getitem__)
    return SimpleNamespace(
        project=project,
        docs=docs,
        target=payload / "notices" / "licenses",
        init=init,
        packages=packages,
        binaries=binaries,
        base=base,
    )


def test_checked_in_upstream_bytes_match_independent_pins():
    sources, manifest_path = collector.checked_sources(collector.PROJECT_ROOT)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key, expected_hash in OFFICIAL_HASHES.items():
        assert hashlib.sha256(sources[key].read_bytes()).hexdigest() == expected_hash
        assert manifest["sources"][key]["sha256"] == expected_hash
        assert manifest["sources"][key]["upstream_commit"] in manifest["sources"][key]["immutable_url"]


def test_collection_preserves_complete_originals_other_licenses_and_binary_bytes(isolated):
    collector.collect_licenses(isolated.target, isolated.project)
    for name in collector.PYWINRT_COMPONENTS:
        assert (isolated.target / name / "LICENSE.txt").read_bytes() == (
            isolated.docs / "pywinrt-3.2.1-LICENSE.txt"
        ).read_bytes()
    assert (isolated.target / "tcl" / "license.terms").read_bytes() == (
        isolated.docs / "tcl-8.6.12-license.terms"
    ).read_bytes()
    assert (isolated.target / "SOURCES.json").read_bytes() == (isolated.docs / "SOURCES.json").read_bytes()
    assert (isolated.target / "requests" / "LICENSE").read_bytes() == b"synthetic package terms\n"
    assert (isolated.target / "Python-LICENSE.txt").read_bytes() == b"synthetic Python license\r\n"
    assert all(path.read_bytes() == original for path, original in isolated.binaries.items())


@pytest.mark.parametrize("component", collector.PYWINRT_COMPONENTS)
def test_each_wrong_pywinrt_version_fails_before_any_output(isolated, component):
    isolated.packages[component].version = "3.2.2"
    with pytest.raises(ValueError, match="runtime version mismatch"):
        collector.collect_licenses(isolated.target, isolated.project)
    assert not isolated.target.exists()


@pytest.mark.parametrize("key", ["pywinrt", "tcl"])
@pytest.mark.parametrize("failure", ["missing", "changed", "empty"])
def test_missing_changed_or_empty_upstream_text_fails_without_touching_existing_output(
    isolated, key, failure
):
    manifest = json.loads((isolated.docs / "SOURCES.json").read_text(encoding="utf-8"))
    source = isolated.docs / manifest["sources"][key]["file"]
    if failure == "missing":
        source.unlink()
    else:
        source.write_bytes(b"" if failure == "empty" else b"MIT without the original copyrights")
    isolated.target.mkdir(parents=True)
    sentinel = isolated.target / "existing-license.txt"
    sentinel.write_bytes(b"preserve")
    with pytest.raises((FileNotFoundError, ValueError)):
        collector.collect_licenses(isolated.target, isolated.project)
    assert list(isolated.target.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"preserve"


@pytest.mark.parametrize("key", ["pywinrt", "tcl"])
@pytest.mark.parametrize(
    "field,value", [("version", "unexpected"), ("components", []), ("file", "other.txt")]
)
def test_manifest_version_file_and_component_mapping_must_match(isolated, key, field, value):
    path = isolated.docs / "SOURCES.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["sources"][key][field] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="version/component mismatch"):
        collector.collect_licenses(isolated.target, isolated.project)
    assert not isolated.target.exists()


@pytest.mark.parametrize("version", [None, "8.6.13", "9.0.0"])
def test_payload_tcl_version_is_required_and_pinned(isolated, version):
    if version is None:
        isolated.init.unlink()
    else:
        isolated.init.write_text(f"package require -exact Tcl {version}\n", encoding="utf-8")
    with pytest.raises((FileNotFoundError, ValueError)):
        collector.collect_licenses(isolated.target, isolated.project)
    assert not isolated.target.exists()


def test_missing_declared_package_license_is_not_silently_skipped(isolated):
    isolated.packages["requests"].locate_file(Path("licenses/LICENSE")).unlink()
    with pytest.raises(FileNotFoundError, match="package license missing"):
        collector.collect_licenses(isolated.target, isolated.project)
    assert not isolated.target.exists()


def test_python_license_is_required(isolated):
    (isolated.base / "LICENSE.txt").unlink()
    with pytest.raises(FileNotFoundError, match="Python LICENSE"):
        collector.collect_licenses(isolated.target, isolated.project)
    assert not isolated.target.exists()


def test_importing_collector_never_writes_default_dist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("license_collector_import_only", collector.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not (tmp_path / "dist").exists()
