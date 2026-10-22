"""Specific native redistribution and packaging regressions; no network or GUI."""

import hashlib
import json
from pathlib import Path

import pytest
import release_compliance as policy

ROOT = Path(__file__).resolve().parents[1]


def test_exact_notices_include_all_identified_embedded_copyrights():
    config = policy.native_distribution(ROOT)
    originals = ROOT / "docs/third-party"
    text = "\n".join((originals / r["file"]).read_text(encoding="utf-8") for r in config["notice_records"])
    for owner in ("MagicStack", "Stefan Krah", "Expat maintainers", "HACL* Contributors", "Unicode, Inc."):
        assert owner in text
    assert "brief summary" in text
    assert len(config["native_files"]) == 24
    assert not config["complete_build_history_required"]
    assert not config["public_release_approved"]


def test_replacement_inputs_and_prerequisites_have_narrow_exact_scope():
    config = policy.native_distribution(ROOT)
    assert set(config["overrides"]) == {"_lzma.pyd", "libffi-8.dll"}
    assert "5.8.3" in config["overrides"]["_lzma.pyd"]["component"]
    assert "94cb9a1c7feb608adf2b9f8fe2dbd6925ffbf90d" in config["overrides"]["libffi-8.dll"]["origin_url"]
    assert set(config["msvc_prerequisite"]["files"]) == {
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "mfc140u.dll",
    }
    script = (ROOT / "scripts/Check-Prerequisites.ps1").read_text(encoding="utf-8")
    assert "14.44.35211.0" in script and "exit 2" in script
    assert "Start-Process" not in script and "Invoke-WebRequest" not in script
    installer = (ROOT / "installer/canvas-agent.iss").read_text(encoding="utf-8")
    assert "GetVersionNumbers" in installer and "RuntimeFiles" in installer
    assert "Nothing will be downloaded or installed automatically" in installer


def test_missing_notice_or_changed_hash_fails(tmp_path):
    directory = tmp_path / "docs/third-party"
    directory.mkdir(parents=True)
    original = json.loads((ROOT / "docs/third-party/NATIVE_DISTRIBUTION.json").read_text())
    (directory / "NATIVE_DISTRIBUTION.json").write_text(json.dumps(original))
    with pytest.raises(FileNotFoundError):
        policy.native_distribution(tmp_path)
    for row in original["notice_records"]:
        file = directory / row["file"]
        file.parent.mkdir(exist_ok=True)
        file.write_bytes(b"not the required original")
    with pytest.raises(ValueError, match="missing or changed"):
        policy.native_distribution(tmp_path)


def test_override_and_external_runtime_are_fail_closed(tmp_path, monkeypatch):
    old, new = tmp_path / "old.pyd", tmp_path / "_lzma.pyd"
    old.write_bytes(b"old")
    new.write_bytes(b"official")
    config = {
        "overrides": {
            "_lzma.pyd": {
                "sha256": hashlib.sha256(b"official").hexdigest(),
                "replaces_sha256": hashlib.sha256(b"old").hexdigest(),
            }
        },
        "msvc_prerequisite": {"files": ["msvcp140.dll"]},
    }
    monkeypatch.setattr(policy, "native_distribution", lambda p: config)
    entries = [("_lzma.pyd", str(old), "EXTENSION"), ("winrt/MSVCP140.dll", "unused", "BINARY")]
    retained, removed, substitutions = policy.release_native_binaries(entries, tmp_path, tmp_path)
    assert retained == [("_lzma.pyd", str(new), "EXTENSION")]
    assert len(removed) == len(substitutions) == 1
    new.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        policy.release_native_binaries(entries, tmp_path, tmp_path)
    with pytest.raises(ValueError, match="absent"):
        policy.release_native_binaries([], tmp_path, tmp_path)
