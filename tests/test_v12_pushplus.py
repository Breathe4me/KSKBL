"""Mock transport, quota gates and durable receipts; never sends a live notification."""

from datetime import timedelta

import pytest
import requests
from conftest import Response, Session

from canvas_agent.notifications import Dispatcher, PushPlusChannel
from canvas_agent.rules import Message
from canvas_agent.storage import Store


@pytest.mark.parametrize(
    "code,reason",
    [
        (900, "account_restricted"),
        (905, "identity_required"),
        (903, "invalid_token"),
        (888, "quota_or_credit"),
        (403, "access_denied"),
    ],
)
def test_official_rejection_is_safe_terminal_account_gate(tmp_path, now, code, reason):
    session = Session(Response({"code": code, "msg": "private-token-synthetic"}))
    store = Store(tmp_path)
    channel = PushPlusChannel("private-token-synthetic", session)
    dispatcher = Dispatcher(store, {"pushplus": channel}, [channel.token], "")
    result = dispatcher.send_result(Message("one", "t", "b"), ["pushplus"], now)
    assert result["channels"]["pushplus"] == "pushplus_" + reason
    assert (
        dispatcher.send_result(Message("two", "t", "b"), ["pushplus"], now)["channels"]["pushplus"]
        == "rate_limited_or_restricted"
    )
    assert len(session.calls) == 1
    assert "private-token-synthetic" not in str(store.events())
    store.close()


def test_api_acceptance_dedup_is_not_delivery_confirmation(tmp_path, now):
    session = Session(Response({"code": 200, "data": "synthetic-reference"}))
    store = Store(tmp_path)
    channel = PushPlusChannel("synthetic", session)
    dispatcher = Dispatcher(store, {"pushplus": channel}, ["synthetic"], "")
    for _ in range(3):
        assert dispatcher.send(Message("same", "t", "b"), ["pushplus"], now)
    assert len(session.calls) == 1
    assert "delivered" not in str(store.events())
    assert session.calls[0][1]["json"]["channel"] == "wechat"
    assert session.calls[0][1]["allow_redirects"] is False
    store.close()


def test_network_timeout_is_uncertain_never_blind_replay(tmp_path, now):
    session = Session(requests.Timeout("secret synthetic detail"))
    store = Store(tmp_path)
    dispatcher = Dispatcher(store, {"pushplus": PushPlusChannel("synthetic", session)}, [], "")
    for hour in range(3):
        assert not dispatcher.send(Message("same", "t", "b"), ["pushplus"], now + timedelta(hours=hour))
    assert len(session.calls) == 1
    assert store.delivery_status("same", "pushplus") == "uncertain"
    assert "secret" not in str(store.events())
    store.close()


@pytest.mark.parametrize("response", [Response({"code": 500}), Response({}, status=429)])
def test_explicit_failure_max_three_retries_spaced_15m(tmp_path, now, response):
    session = Session(response, response, response)
    store = Store(tmp_path)
    dispatcher = Dispatcher(store, {"pushplus": PushPlusChannel("synthetic", session)}, [], "")
    for minutes in (0, 1, 15, 16, 30, 60):
        assert not dispatcher.send(Message("same", "t", "b"), ["pushplus"], now + timedelta(minutes=minutes))
    assert len(session.calls) == 3
    store.close()


def test_per_minute_limit_defers_without_consuming_message_receipt(tmp_path, now):
    session = Session(*[Response({"code": 200}) for _ in range(6)])
    store = Store(tmp_path)
    dispatcher = Dispatcher(store, {"pushplus": PushPlusChannel("synthetic", session)}, [], "")
    for index in range(5):
        assert dispatcher.send(Message(str(index), "t", "b"), ["pushplus"], now)
    assert not dispatcher.send(Message("six", "t", "b"), ["pushplus"], now)
    assert store.delivery_status("six", "pushplus") is None
    assert dispatcher.send(Message("six", "t", "b"), ["pushplus"], now + timedelta(seconds=61))
    assert len(session.calls) == 6
    store.close()
