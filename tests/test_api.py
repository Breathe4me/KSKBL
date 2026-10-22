import pytest
import requests
from conftest import Response, Session

from canvas_agent.api import APIError, CanvasAPI


def client(*responses):
    sleeps = []
    session = Session(*responses)
    return CanvasAPI("https://canvas.example", "synthetic-token", session, sleeps.append), session, sleeps


def test_pagination():
    api, session, _ = client(
        Response([{"id": 1}], next_url="https://canvas.example/api/v1/courses?page=2"), Response([{"id": 2}])
    )
    assert len(api.pages("courses", {"per_page": 100})) == 2
    assert session.calls[1][1]["params"] is None
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "bad_request"),
        (401, "invalid_token"),
        (403, "permission_denied"),
        (404, "unsupported_or_missing"),
        (302, "unexpected_http"),
    ],
)
def test_no_retry_definitive_error(status, code):
    api, session, sleeps = client(Response(status=status))
    with pytest.raises(APIError, match=code):
        api.pages("courses")
    assert len(session.calls) == 1
    assert sleeps == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_bounded_retry(status):
    api, session, sleeps = client(*[Response(status=status) for _ in range(4)])
    with pytest.raises(APIError):
        api.pages("courses")
    assert len(session.calls) == 4 and sleeps == [1, 2, 4]


def test_retry_after():
    api, _, sleeps = client(Response(status=429, headers={"Retry-After": "5"}), Response([]))
    assert api.pages("courses") == []
    assert sleeps == [5]


def test_long_retry_is_deferred():
    api, session, sleeps = client(Response(status=429, headers={"Retry-After": "120"}))
    with pytest.raises(APIError, match="retry_later"):
        api.pages("courses")
    assert len(session.calls) == 1 and sleeps == []


def test_timeout():
    api, session, _ = client(*[requests.Timeout() for _ in range(4)])
    with pytest.raises(APIError, match="network_or_timeout"):
        api.pages("courses")
    assert len(session.calls) == 4


@pytest.mark.parametrize(
    "next_url",
    [
        "https://evil.example/api/v1/courses",
        "http://canvas.example/api/v1/courses",
        "https://canvas.example@evil.example/api/v1/courses",
        "https://canvas.example/logout",
    ],
)
def test_pagination_does_not_leak_token(next_url):
    api, session, _ = client(Response([], next_url=next_url))
    with pytest.raises(APIError, match="unsafe_pagination"):
        api.pages("courses")
    assert len(session.calls) == 1


def test_pagination_loop():
    api, session, _ = client(Response([], next_url="https://canvas.example/api/v1/courses"))
    with pytest.raises(APIError, match="pagination_loop"):
        api.pages("courses")
    assert len(session.calls) == 1


def test_partial_course_does_not_become_empty_success():
    api, _, _ = client(
        Response([{"id": 2, "name": "A", "submission": {"workflow_state": "submitted"}}]),
        Response(status=403),
        Response([]),
    )
    snap = api.sync([{"id": 1, "name": "Example"}])
    assert not snap.complete and len(snap.tasks) == 1
    assert (1, "quizzes") not in snap.successful
    assert snap.tasks[0].completed


def test_assignment_quiz_id_dedup_and_same_title():
    api, _, _ = client(
        Response([{"id": 2, "name": "Same", "submission": {"workflow_state": "submitted"}}]),
        Response(
            [{"id": 5, "assignment_id": 2, "name": "Same"}, {"id": 6, "assignment_id": 3, "name": "Same"}]
        ),
        Response([]),
    )
    snap = api.sync([{"id": 1, "name": "C"}])
    assert snap.complete and len(snap.tasks) == 2
    assert snap.tasks[0].completed and snap.tasks[1].status == "Unknown"


def test_malformed_scope_not_committed():
    api, _, _ = client(Response([{"id": 1}, {"id": 2, "due_at": "bad"}]), Response([]), Response([]))
    snap = api.sync([{"id": 1, "name": "C"}])
    assert not snap.tasks and (1, "assignments") not in snap.successful


@pytest.mark.parametrize("data", [{}, "wrong", [None]])
def test_bad_list(data):
    api, _, _ = client(Response(data))
    with pytest.raises(APIError, match="invalid_response"):
        api.pages("courses")


def test_empty_courses():
    api, _, _ = client(Response([]))
    assert api.courses() == []
    assert api.sync([]).complete


def test_profile_validation():
    api, _, _ = client(Response({"name": "Example"}))
    with pytest.raises(APIError, match="invalid_profile"):
        api.identity()
