import copy
import hashlib
from datetime import UTC, datetime

import pytest

from canvas_agent.config import DEFAULTS
from canvas_agent.models import Task


def pytest_make_parametrize_id(config, val, argname):
    if isinstance(val, (str, bytes)) and len(val) > 100:
        data = val.encode() if isinstance(val, str) else val
        return argname + "-" + hashlib.sha256(data).hexdigest()[:8]
    return None


@pytest.fixture
def config():
    # Legacy rule regressions isolate the independent v1.1 Guardian; its integration has dedicated tests.
    return copy.deepcopy(DEFAULTS | {"timezone": "UTC", "guardian_enabled": False})


@pytest.fixture
def now():
    return datetime(2026, 10, 19, 10, 0, tzinfo=UTC)


@pytest.fixture
def task():
    return Task(
        "1:assignment:2",
        1,
        "Example Course",
        "Example task",
        "assignments",
        "2026-10-21T10:00:00Z",
        "Confirmed Not Submitted",
        "https://canvas.example/courses/1/assignments/2",
    )


class Response:
    def __init__(self, data=None, status=200, next_url=None, headers=None):
        self.data, self.status_code = data, status
        self.headers = headers or {}
        self.links = {"next": {"url": next_url}} if next_url else {}

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    post = get


@pytest.fixture(autouse=True)
def no_real_native_side_effects(monkeypatch):
    """Tests must explicitly replace native boundaries with fakes before calling them."""
    from canvas_agent import notifications, schedule

    def denied(*args, **kwargs):
        raise AssertionError("Real native API access is forbidden in Mock regressions")

    monkeypatch.setattr(schedule, "scheduler_connection", denied)
    monkeypatch.setattr(notifications, "apartment", denied)
    # Product code can only use explicitly supplied fake sessions in these regressions.
    import requests

    monkeypatch.setattr(requests.sessions.Session, "request", denied)
