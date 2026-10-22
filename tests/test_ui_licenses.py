"""Synthetic dependency metadata only. No network, binaries, installer or GUI execution."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import check_ui_licenses as checker
import pytest


@pytest.fixture
def licenses(tmp_path, monkeypatch):
    packages = {}
    for name, version in checker.PINS.items():
        file = tmp_path / "packages" / name / "LICENSE"
        file.parent.mkdir(parents=True)
        file.write_bytes(b"synthetic license fixture " + name.encode())
        packages[name] = SimpleNamespace(
            version=version, files=[Path("LICENSE")], locate_file=lambda entry, file=file: file
        )
    monkeypatch.setattr(checker.importlib.metadata, "distribution", packages.__getitem__)
    directory = tmp_path / "docs/third-party"
    directory.mkdir(parents=True)
    terms = directory / "synthetic-sdk-terms.txt"
    terms.write_bytes(b"synthetic SDK terms for isolated tests only")
    (directory / "UI_SOURCES.json").write_text(
        json.dumps(
            {
                "Microsoft.Web.WebView2 SDK": {
                    "file": terms.name,
                    "sha256": hashlib.sha256(terms.read_bytes()).hexdigest(),
                    "source_url": "https://official.example/synthetic-test-only",
                }
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, packages


def test_ui_collection_preserves_terms_bytes_after_success(licenses):
    root, packages = licenses
    assert checker.inventory(root)["status"] == "passed"
    checker.collect(root, root / "output")
    for name in packages:
        assert (root / "output" / name / "LICENSE").read_bytes() == packages[name].locate_file(
            None
        ).read_bytes()


@pytest.mark.parametrize(
    "problem", ["absent_proxy_terms", "missing_sdk_terms", "modified_sdk_terms", "wrong_version"]
)
def test_ui_licenses_fail_before_any_payload_write(licenses, problem):
    root, packages = licenses
    if problem == "absent_proxy_terms":
        packages["proxy_tools"].files = []
    elif problem == "missing_sdk_terms":
        (root / "docs/third-party/synthetic-sdk-terms.txt").unlink()
    elif problem == "modified_sdk_terms":
        (root / "docs/third-party/synthetic-sdk-terms.txt").write_bytes(b"changed")
    else:
        packages["pythonnet"].version = "0.0.0"
    with pytest.raises(ValueError, match="preflight failed"):
        checker.collect(root, root / "output")
    assert not (root / "output").exists()


def test_supplemental_SDK_notice_is_required_collected_and_hash_checked(licenses):
    root, _ = licenses
    file = root / "docs/third-party/SDK-NOTICE.txt"
    file.write_bytes(b"synthetic original notice")
    manifest = root / "docs/third-party/UI_SOURCES.json"
    value = json.loads(manifest.read_text())
    value["Microsoft.Web.WebView2 SDK"]["additional_files"] = [
        {
            "file": file.name,
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            "source_url": "https://official.example/synthetic-notice-only",
        }
    ]
    manifest.write_text(json.dumps(value))
    checker.collect(root, root / "collected")
    assert (root / "collected/Microsoft.Web.WebView2-SDK/SDK-NOTICE.txt").read_bytes() == file.read_bytes()
    file.write_bytes(b"changed")
    with pytest.raises(ValueError):
        checker.collect(root, root / "must-not-exist")
    assert not (root / "must-not-exist").exists()
