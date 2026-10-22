"""Frozen SSL policy companion collection and safe diagnostics; no GUI or external accounts."""

import json
import ssl
from pathlib import Path
from types import SimpleNamespace

import pytest
from ssl_resources import ssl_resources

from canvas_agent.startup_diagnostics import StartupDiagnostics
from canvas_agent.tls_check import check
from canvas_agent.tls_diagnostics import exception_chain, snapshot


def fake_module(tmp_path, required=True):
    def needs_resource(cls):
        return "codex-rejected-cas.pem"

    def standard(cls):
        return None

    return SimpleNamespace(
        __file__=str(tmp_path / "ssl.py"),
        SSLContext=SimpleNamespace(__new__=needs_resource if required else standard),
    )


def test_missing_companion_stops_build_instead_of_first_connection(tmp_path):
    with pytest.raises(FileNotFoundError):
        ssl_resources(fake_module(tmp_path))


def test_companion_manifest_preserves_exact_trusted_certificate_bytes(tmp_path):
    value = Path(ssl.__file__).with_name("codex-rejected-cas.pem").read_bytes()
    (tmp_path / "codex-rejected-cas.pem").write_bytes(value)
    manifest = ssl_resources(fake_module(tmp_path))
    assert manifest["ssl_companion_required"]
    assert manifest["files"][0]["bytes"] == len(value)
    assert manifest["files"][0]["destination"] == "codex-rejected-cas.pem"
    assert len(manifest["files"][0]["sha256"]) == 64


def test_unmodified_standard_python_needs_no_vendor_companion(tmp_path):
    assert ssl_resources(fake_module(tmp_path, False))["files"] == []


def test_wrong_companion_format_is_rejected(tmp_path):
    (tmp_path / "codex-rejected-cas.pem").write_text("not a trusted certificate")
    with pytest.raises(ValueError):
        ssl_resources(fake_module(tmp_path))


def test_SSL_exception_chain_records_filename_not_secret_message(tmp_path):
    try:
        try:
            raise FileNotFoundError(2, "SYNTHETIC-NOT-FOR-LOGS", str(tmp_path / "missing-policy.pem"))
        except FileNotFoundError as cause:
            raise RuntimeError("SYNTHETIC-NOT-FOR-LOGS") from cause
    except RuntimeError as error:
        rows = exception_chain(error)
    assert [row["type"] for row in rows] == ["RuntimeError", "FileNotFoundError"]
    assert rows[1]["filename"] == str(tmp_path / "missing-policy.pem")
    assert "SYNTHETIC-NOT-FOR-LOGS" not in json.dumps(rows)
    metadata = snapshot()
    assert metadata["create_default_context_inputs"] == {"cafile": None, "capath": None, "cadata": None}
    assert metadata["certifi"]["exists"] and metadata["ssl_companion_policy"]["exists"]


def test_TLS_selfcheck_refuses_nonempty_unrelated_directory(tmp_path):
    sentinel = tmp_path / "config.json"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError):
        check(tmp_path)
    assert sentinel.read_text() == "preserve"


def test_TLS_selfcheck_rejects_unplanned_ports_before_network(tmp_path):
    (tmp_path / "test-ca.pem").write_text("unused")
    (tmp_path / "tls-test-plan.json").write_text(
        json.dumps({"trusted": True, "wrong_hostname": 0, "untrusted": -1})
    )
    with pytest.raises(ValueError):
        check(tmp_path)


def test_real_missing_SSL_companion_exception_is_persisted_without_secrets(tmp_path, monkeypatch):
    # Reproduce the same native OpenSSL FileNotFoundError, not a mocked SSL function.
    monkeypatch.setattr(ssl, "__file__", str(tmp_path / "ssl.py"))
    diagnostics = StartupDiagnostics(tmp_path / "profile")
    with pytest.raises(FileNotFoundError) as failure:
        ssl.create_default_context()
    diagnostics.exception("bridge_invoke", failure.value)
    records = [json.loads(line) for line in (diagnostics.directory / "startup.jsonl").read_text().splitlines()]
    record = next(row for row in records if row["event"] == "tls_initialization_error")
    assert record["chain"][0]["type"] == "FileNotFoundError"
    assert record["chain"][0]["filename"] is None  # OpenSSL does not attach the actual PEM path
    assert record["environment"]["ssl_companion_policy"]["path"] == str(tmp_path / "codex-rejected-cas.pem")
    assert record["environment"]["ssl_companion_policy"]["exists"] is False
