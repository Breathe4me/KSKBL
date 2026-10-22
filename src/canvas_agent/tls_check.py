"""QA-only real loopback HTTPS check; no GUI, real accounts or external destinations."""

import json
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .ai import AIClient
from .api import CanvasAPI
from .config import DEFAULTS, save
from .pushplus import PushPlusChannel
from .tls_diagnostics import exception_chain, snapshot
from .transport import WindowsTrustAdapter, canvas_session
from .web_bridge import Bridge


def require(condition):
    if not condition:
        raise RuntimeError("tls_check_assertion_failed")


def check(root):
    root = Path(root)
    if not root.is_dir() or {p.name for p in root.iterdir()} != {"tls-test-plan.json", "test-ca.pem"}:
        raise ValueError("Fresh isolated TLS plan directory required")
    plan = json.loads((root / "tls-test-plan.json").read_text(encoding="utf-8"))
    if set(plan) != {"trusted", "wrong_hostname", "untrusted"} or any(
        type(port) is not int or not 1 <= port <= 65535 for port in plan.values()
    ):
        raise ValueError("Invalid loopback TLS plan")
    base = f"https://127.0.0.1:{plan['trusted']}"
    ca = str(root / "test-ca.pem")
    cases, sessions = [], []
    result = {
        "status": "failed",
        "environment": snapshot(),
        "cases": cases,
        "gui_started": False,
        "real_credentials_used": False,
        "external_requests": 0,
    }
    original_request = requests.sessions.Session.request

    def loopback_only(session, method, url, **kwargs):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "127.0.0.1" or parsed.port not in plan.values():
            result["external_requests"] += 1
            raise ValueError("Only planned loopback HTTPS is allowed")
        if kwargs.get("verify", session.verify) is False:
            raise ValueError("TLS verification must remain enabled")
        return original_request(session, method, url, **kwargs)

    def session(secure=True):
        value = canvas_session() if secure else requests.Session()
        value.trust_env = False  # test-scoped: no proxy, netrc or real-user CA overrides
        value.verify = ca
        sessions.append(value)
        return value

    def passed(name, **details):
        cases.append({"case": name, "passed": True, **details})

    requests.sessions.Session.request = loopback_only
    try:
        context = ssl.create_default_context()
        require(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname)
        passed("default_context_initialization", verify_mode=int(context.verify_mode), check_hostname=True)
        adapter = WindowsTrustAdapter()
        proxy = adapter.proxy_manager_for("http://127.0.0.1:9")
        for ctx in (
            adapter.poolmanager.connection_pool_kw["ssl_context"],
            proxy.connection_pool_kw["ssl_context"],
        ):
            require(ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname)
        adapter.close()
        passed("direct_and_proxy_adapter_initialization")
        for secure in (False, True):
            response = session(secure).get(base + "/health", timeout=5)
            require(response.status_code == 200 and response.json() == {"ok": True})
        passed("plain_Requests_and_WindowsTrustAdapter_real_verified_HTTPS")

        class SyntheticVault:
            def __init__(self, _root):
                pass

            def get(self, name):
                return "SYNTHETIC-LOOPBACK-CANVAS" if name == "canvas" else ""

            def values(self):
                return ("SYNTHETIC-LOOPBACK-CANVAS",)

        data = root / "synthetic-services"
        data.mkdir()
        save(data / "config.json", DEFAULTS | {"canvas_url": base})
        (data / "QA_ONLY.json").write_text('{"mode":"synthetic_only","schema":1}', encoding="utf-8")
        bridge = Bridge(
            data,
            qa=False,
            secrets_factory=SyntheticVault,
            api_factory=lambda endpoint, token: CanvasAPI(endpoint, token, session=session()),
        )
        identity = bridge.invoke("test_identity", {})
        require(identity.get("ok") and identity["data"]["status"] == "identity_verified")
        sync = bridge.invoke("sync", {})
        require(sync.get("ok") and sync["data"]["complete"] and sync["data"]["tasks"] == 1)
        state = bridge.invoke("get_state", {})
        require(state.get("ok") and len(state["data"]["tasks"]) == 1)
        passed("real_Bridge_test_identity_sync_SQLite_state_over_local_HTTPS")

        class LocalPush:
            def __init__(self):
                self.session = session()

            def post(self, url, **kwargs):
                require(url == "https://www.pushplus.plus/send")
                return self.session.post(base + "/pushplus", **kwargs)

        outcome = PushPlusChannel("SYNTHETIC-LOOPBACK-PUSH", session=LocalPush()).send(
            "Synthetic", "Test", "", False
        )
        require(outcome["status"] == "accepted")
        passed("real_PushPlus_POST_local_URL_substitution_only_TLS_HTTP_not_mocked")
        client = AIClient(
            DEFAULTS
            | {
                "ai_enabled": True,
                "ai_consent": True,
                "ai_provider": "Custom",
                "ai_url": base + "/ai",
                "ai_model": "synthetic-only",
            },
            "SYNTHETIC-LOOPBACK-AI",
            session=session(False),
        )
        require(client.request_json("Synthetic local test", "No user data")["status"] == "ok")
        passed("real_AIClient_POST_over_verified_loopback_HTTPS")

        for secure in (False, True):
            for name in ("wrong_hostname", "untrusted"):
                try:
                    session(secure).get(f"https://127.0.0.1:{plan[name]}/health", timeout=5)
                except requests.exceptions.SSLError as error:
                    passed(
                        ("WindowsTrustAdapter" if secure else "Requests") + "_rejects_" + name,
                        exception_chain=exception_chain(error),
                    )
                else:
                    raise AssertionError("Invalid certificate accepted")
        broken = session()
        broken.verify = str(root / "deliberately-absent-test-ca.pem")
        try:
            broken.get(base + "/health", timeout=5)
        except OSError as error:
            passed("missing_CA_fails_closed", exception_chain=exception_chain(error))
        else:
            raise AssertionError("Missing CA unexpectedly accepted")
        result.update(
            status="passed",
            frozen=bool(getattr(sys, "frozen", False)),
            forbidden_gui_imports=[
                name
                for name in ("webview.platforms.winforms", "webview.platforms.edgechromium")
                if name in sys.modules
            ],
        )
        require(not result["forbidden_gui_imports"] and result["external_requests"] == 0)
    except Exception as error:
        result.update(status="failed", exception_chain=exception_chain(error))
    finally:
        requests.sessions.Session.request = original_request
        for value in sessions:
            value.close()
    (root / "tls-check-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
