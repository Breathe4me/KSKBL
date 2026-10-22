from dataclasses import replace
from datetime import timedelta

from conftest import Response, Session

from canvas_agent.api import CanvasAPI
from canvas_agent.courses import academic_courses
from canvas_agent.models import Snapshot
from canvas_agent.storage import Store


def test_course_scope_excludes_training_even_with_canvas_course_code():
    raw = [
        {"id": 1, "name": "Academic Honesty Education Module 2026", "course_code": "AHEM2026TRAINING"},
        {"id": 2, "name": "Anti-Slavery Awareness", "course_code": "Training"},
        {"id": 3, "name": "Cybersecurity", "course_code": "COMP4618_COMP5618"},
        {"id": 4, "name": "IDEA9106 Design Thinking"},
    ]
    # Use complete code tokens; named learning modules without such tokens are excluded.
    api = CanvasAPI("https://canvas.example", "synthetic", Session(Response(raw)))
    courses = api.courses()
    assert [c["id"] for c in courses] == [3, 4]
    assert courses[0]["course_code"] == "COMP4618 / COMP5618"


def test_course_regex_does_not_match_embedded_or_long_codes():
    assert not academic_courses([{"id": 1, "name": "ABCDEF1234"}, {"id": 2, "name": "COMP12345"}])


def recovered_snapshot(detail=None, detail_error=None):
    items = [
        {"type": "Quiz", "content_id": 3},
        {
            "type": "Quiz",
            "content_id": 5,
            "title": "Module quiz",
            "content_details": {"due_at": "2026-10-21T10:00:00Z"},
        },
    ]
    session = Session(
        Response(
            [{"id": 2, "name": "Graded quiz", "quiz_id": 3, "submission": {"workflow_state": "submitted"}}]
        ),
        Response({"message": "That page has been disabled for this course"}, status=404),
        Response([{"id": 10, "items_count": 2, "items": items}]),
        Response(
            detail or {"id": 5, "title": "Extra quiz", "due_at": "2026-10-21T10:00:00Z"},
            status=detail_error or 200,
        ),
        Response([]),
    )
    snap = CanvasAPI("https://canvas.example", "synthetic", session).sync([{"id": 1, "name": "COMP1234"}])
    return snap, session


def test_module_recovery_deduplicates_assignment_and_keeps_limited_coverage():
    snap, session = recovered_snapshot()
    assert len(snap.tasks) == 2 and not snap.complete and snap.status == "limited"
    assert snap.tasks[0].completed and snap.tasks[1].status == "Unknown"
    assert not snap.failures and snap.capabilities[0]["recovery"]["covered_by_assignments"] == 1
    assert snap.capabilities[0]["recovery"]["recovered"] == 1
    assert not any("/quizzes/3" in url for url, _ in session.calls)


def test_module_details_do_not_guess_submission_or_complete_status():
    snap, _ = recovered_snapshot(detail_error=403)
    assert snap.status == "partial" and not snap.complete
    assert snap.tasks[1].title == "Module quiz" and snap.tasks[1].status == "Unknown"
    assert snap.capabilities[0]["recovery"]["unresolved"] == 1


def test_large_module_fetches_paginated_items():
    session = Session(
        Response([]),
        Response({"message": "That page has been disabled for this course"}, status=404),
        Response([{"id": 10, "items_count": 1}]),
        Response([{"type": "Quiz", "content_id": 5}]),
        Response({"id": 5, "title": "Additional"}),
        Response([]),
    )
    snap = CanvasAPI("https://canvas.example", "synthetic", session).sync([{"id": 1, "name": "COMP1234"}])
    assert snap.tasks[0].title == "Additional"
    assert "/modules/10/items" in session.calls[3][0]


def test_partial_recovery_keeps_old_items_and_individual_freshness(tmp_path, task, now):
    store = Store(tmp_path)
    try:
        old = replace(task, key="1:quiz:99", kind="quizzes", title="Old cached quiz")
        store.snapshot(Snapshot([{"id": 1, "name": "COMP1234"}], [old], [], [(1, "quizzes")], []), now)
        snap, _ = recovered_snapshot()
        store.snapshot(snap, now + timedelta(hours=1))
        cached = {t["key"]: t for t in store.cached()}
        assert len(cached) == 3 and cached[old.key]["checked"] == now.isoformat()
        assert cached["1:quiz:5"]["checked"] == (now + timedelta(hours=1)).isoformat()
        assert store.get("last_status") == "limited" and store.get("last_complete") is False
    finally:
        store.close()
