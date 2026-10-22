"""Real Windows DPAPI in fresh synthetic profiles; external service calls remain Fake only."""

import json

import pytest

from canvas_agent.ai import AIClient
from canvas_agent.config import DEFAULTS, load, save
from canvas_agent.security import CredentialError, Secrets, ai_key
from canvas_agent.startup_diagnostics import StartupDiagnostics
from canvas_agent.storage import Store
from canvas_agent.web_bridge import Bridge
from canvas_agent.web_qa import prepare_qa_root


def live(root):
    root.mkdir()
    save(root / "config.json", DEFAULTS)
    return Bridge(root, qa=False)


@pytest.mark.parametrize("kind", ["canvas", "pushplus", "ai"])
def test_QA_denial_is_explicit_and_never_persists_credentials(tmp_path, kind):
    root = prepare_qa_root(tmp_path / "qa")
    bridge = Bridge(root, qa=True)
    result = bridge.invoke("save_credential", {"kind": kind, "value": "SYNTHETIC-NOT-REAL"})
    assert result == {"ok": False, "error": "qa_credentials_disabled"}
    assert not list(root.glob("*.dpapi"))
    state = bridge.invoke("get_state", {})["data"]
    assert state["credential_policy"]["can_save"] is False
    assert state["credentials"][kind] == "missing"


@pytest.mark.parametrize("kind", ["canvas", "pushplus", "ai"])
def test_real_DPAPI_add_update_delete_restart_no_secret_DTO_or_log(tmp_path, kind):
    root = tmp_path / "live-isolated"
    bridge = live(root)
    diag = StartupDiagnostics(root, operations_enabled=True)
    bridge._diagnostics = diag
    for suffix in ("A", "B"):
        secret = "SYNTHETIC-AUDIT-SECRET-" + suffix
        assert bridge.invoke("save_credential", {"kind": kind, "value": secret})["ok"]
        assert Secrets(root).get(kind) == secret
        state = Bridge(root, qa=False).invoke("get_state", {})["data"]
        assert state["credentials"][kind] == "saved" and secret not in json.dumps(state)
        assert secret not in (root / "config.json").read_text(encoding="utf-8")
        assert all(secret.encode() not in file.read_bytes() for file in root.glob("*.dpapi"))
        assert secret not in (diag.directory / "operations.jsonl").read_text(encoding="utf-8")
    assert bridge.invoke("remove_credential", {"kind": kind})["ok"]
    assert Secrets(root).get(kind) == ""


def test_provider_and_custom_endpoint_keys_are_isolated_and_snapshot_bound(tmp_path):
    root = tmp_path / "keys"
    bridge = live(root)
    configs = [
        DEFAULTS,
        DEFAULTS | {"ai_provider": "OpenAI", "ai_url": "https://api.openai.com/v1"},
        DEFAULTS | {"ai_provider": "Custom", "ai_url": "https://ai-a.example/v1"},
        DEFAULTS | {"ai_provider": "Custom", "ai_url": "https://ai-b.example/v1"},
    ]
    for index, config in enumerate(configs):
        save(root / "config.json", config)
        assert Secrets(root).get("ai") == ""
        assert bridge.invoke("save_credential", {"kind": "ai", "value": f"SYNTHETIC-PROVIDER-{index}"})["ok"]
    assert len(list(root.glob("ai-*.dpapi"))) == 4
    for index, config in enumerate(configs):
        # The on-disk config still points at ai-b; an old request snapshot reads ONLY its own key.
        assert ai_key(Secrets(root), config) == f"SYNTHETIC-PROVIDER-{index}"
    assert bridge.invoke("remove_credential", {"kind": "ai"})["ok"]
    assert ai_key(Secrets(root), configs[3]) == "" and ai_key(Secrets(root), configs[0])


def test_legacy_ai_blob_preserved_and_requires_explicit_rebind(tmp_path):
    from canvas_agent.security import dpapi

    root = tmp_path / "legacy"
    bridge = live(root)
    original = dpapi(b"SYNTHETIC-LEGACY", True)
    (root / "ai.dpapi").write_bytes(original)
    assert Secrets(root).get("ai") == ""
    state = bridge.invoke("get_state", {})["data"]
    assert state["credential_policy"]["ai_legacy_rebind_required"] is True
    assert bridge.invoke("save_credential", {"kind": "ai", "value": "SYNTHETIC-BOUND"})["ok"]
    assert Secrets(root).get("ai") == "SYNTHETIC-BOUND"
    assert (root / "ai.dpapi").read_bytes() == original
    assert bridge.invoke("get_state", {})["data"]["credential_policy"]["ai_legacy_rebind_required"] is False


def test_corrupt_optional_key_does_not_break_core_state_redaction(tmp_path):
    root = tmp_path / "corrupt"
    bridge = live(root)
    vault = Secrets(root)
    vault.set("canvas", "SYNTHETIC-CANVAS")
    vault.set("ai", "SYNTHETIC-AI")
    next(root.glob("ai-*.dpapi")).write_bytes(b"SYNTHETIC-CORRUPT-BLOB")
    assert vault.values() == ["SYNTHETIC-CANVAS"]
    state = bridge.invoke("get_state", {})
    assert state["ok"] and state["data"]["credentials"]["ai"] == "unreadable"
    assert state["data"]["credentials"]["canvas"] == "saved"


def test_builtin_provider_mismatch_rejects_write_and_fake_HTTP(tmp_path):
    root = tmp_path / "mismatch"
    bridge = live(root)
    config = DEFAULTS | {"ai_enabled": True, "ai_consent": True, "ai_provider": "OpenAI"}
    save(root / "config.json", config)  # old config still loads; do not reintroduce startup ValueError
    assert load(root / "config.json")["ai_provider"] == "OpenAI"
    assert bridge.invoke("save_credential", {"kind": "ai", "value": "SYNTHETIC-OPENAI"}) == {
        "ok": False,
        "error": "ai_endpoint_mismatch",
    }

    class Forbidden:
        def post(self, *args, **kwargs):
            raise AssertionError("Endpoint mismatch must not send any request")

    assert (
        AIClient(config, "SYNTHETIC-OPENAI", Forbidden()).request_json("test", "test")["status"]
        == "provider_endpoint_mismatch"
    )
    assert not list(root.glob("*.dpapi"))


def test_DPAPI_failure_returns_safe_category_and_preserves_old_bytes(tmp_path, monkeypatch):
    import canvas_agent.security as security

    root = tmp_path / "failed"
    bridge = live(root)
    Secrets(root).set("canvas", "SYNTHETIC-OLD")
    previous = (root / "canvas.dpapi").read_bytes()

    def denied(*args):
        raise OSError("SENSITIVE-ERROR-NOT-FOR-LOGS")

    monkeypatch.setattr(security, "dpapi", denied)
    result = bridge.invoke("save_credential", {"kind": "canvas", "value": "SYNTHETIC-NEW"})
    assert result == {"ok": False, "error": "credential_storage_failed"}
    assert (root / "canvas.dpapi").read_bytes() == previous
    with pytest.raises(CredentialError, match="credential_storage_failed"):
        Secrets(root).set("ai", "SYNTHETIC-NEW")
    assert "SENSITIVE" not in json.dumps(result)


def test_explicit_rebind_can_repair_unreadable_canvas_blob(tmp_path):
    root = tmp_path / "repair"
    bridge = live(root)
    (root / "canvas.dpapi").write_bytes(b"SYNTHETIC-UNREADABLE")
    assert bridge.invoke("get_state", {})["data"]["credentials"]["canvas"] == "unreadable"
    assert bridge.invoke("save_credential", {"kind": "canvas", "value": "SYNTHETIC-REPLACEMENT"})["ok"]
    assert Secrets(root).get("canvas") == "SYNTHETIC-REPLACEMENT"


def test_all_provider_secrets_scrubbed_and_backups_exclude_scoped_blobs(tmp_path):
    import zipfile

    from canvas_agent.maintenance import backup

    root = tmp_path / "scrub"
    bridge = live(root)
    Secrets(root).set("ai", "SYNTHETIC-DEEPSEEK")
    config = DEFAULTS | {"ai_provider": "OpenAI", "ai_url": "https://api.openai.com/v1"}
    save(root / "config.json", config)
    Secrets(root).set("ai", "SYNTHETIC-OPENAI")
    assert "SYNTHETIC" not in bridge._scrub("SYNTHETIC-DEEPSEEK / SYNTHETIC-OPENAI")
    store = Store(root)
    store.close()
    archive = tmp_path / "backup.zip"
    backup(root, archive)
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == {"config.json", "state.sqlite"}


def test_credential_selfcheck_is_real_isolated_and_refuses_reuse(tmp_path):
    from canvas_agent.credential_check import check

    root = tmp_path / "new-credential-check"
    result = check(root)
    assert result["status"] == "passed" and len(result["cases"]) == 5
    assert result["external_clients_created"] == 0 and not result["gui_started"]
    original = (root / "credential-check-result.json").read_bytes()
    assert check(root)["code"] == "fresh_synthetic_directory_required"
    assert (root / "credential-check-result.json").read_bytes() == original


def test_fake_AI_request_uses_key_bound_to_request_snapshot(tmp_path):
    from conftest import Response, Session

    root = tmp_path / "request"
    live(root)
    one = DEFAULTS | {"ai_enabled": True, "ai_consent": True}
    two = one | {"ai_provider": "OpenAI", "ai_url": "https://api.openai.com/v1"}
    vault = Secrets(root)
    vault.set_ai(one, "SYNTHETIC-KEY-ONE")
    vault.set_ai(two, "SYNTHETIC-KEY-TWO")
    save(root / "config.json", two)
    session = Session(
        Response({})
    )  # malformed response is deliberate; validate actual outgoing contract only
    AIClient(one, ai_key(vault, one), session).request_json("test", "synthetic")
    assert session.calls[0][0] == "https://api.deepseek.com/chat/completions"
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer SYNTHETIC-KEY-ONE"
