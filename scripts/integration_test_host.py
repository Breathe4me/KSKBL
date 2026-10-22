"""Test-only fake external services; actual non-QA Bridge/CanvasAPI/SQLite over stdio."""

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_full_integration import School, Vault  # noqa: E402

from canvas_agent.api import CanvasAPI  # noqa: E402
from canvas_agent.config import DEFAULTS, save  # noqa: E402
from canvas_agent.web_bridge import Bridge  # noqa: E402


def denied(*args, **kwargs):
    raise AssertionError("External requests/native actions forbidden in headless integration host")


requests.sessions.Session.request = denied
root = Path(sys.argv[1])
root.mkdir(exist_ok=False)
save(root / "config.json", DEFAULTS | {"canvas_url": "https://canvas.example"})
school, vault = School(), Vault(root)
bridge = Bridge(
    root,
    secrets_factory=lambda _: vault,
    api_factory=lambda base, token: CanvasAPI(base, token, session=school, sleep=lambda _: None),
)
for line in sys.stdin:
    packet = json.loads(line)
    if "fixture" in packet:
        if packet["fixture"] == "fail":
            school.failure = 401
        elif packet["fixture"] == "submitted":
            school.submission = "submitted"
        else:
            school.failure = None
        result = {"fixture_only": True}
    else:
        result = bridge.invoke(packet["method"], packet.get("params", {}))
    print(json.dumps(result, ensure_ascii=False), flush=True)
