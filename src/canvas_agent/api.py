"""Read-only Canvas client. Never forwards credentials to pagination/redirect hosts."""

import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import requests

from .config import https_url
from .courses import academic_courses
from .models import Announcement, Snapshot, Task, submission_state, timestamp
from .security import plain, plain_lines, safe_link
from .transport import canvas_session


class APIError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Do not include request URLs, tokens, or response bodies.


class CanvasAPI:
    def __init__(self, base, token, session=None, sleep=time.sleep, now=lambda: datetime.now(UTC)):
        self.base = https_url(base)
        self.token = token
        self.session = session or canvas_session()
        self.sleep, self.now = sleep, now

    def _url(self, path):
        url = urljoin(self.base + "/api/v1/", path)
        p, b = urlsplit(url), urlsplit(self.base)
        if (
            p.scheme != "https"
            or p.netloc != b.netloc
            or p.username
            or p.fragment
            or not p.path.startswith(urlsplit(self.base).path + "/api/v1/")
        ):
            raise APIError("unsafe_pagination")
        return url

    def get(self, path, params=None):
        url = self._url(path)
        for attempt in range(4):
            try:
                r = self.session.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=(8, 25),
                    allow_redirects=False,
                )
            except requests.exceptions.SSLError:
                raise APIError("tls_verification_failed") from None
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 3:
                    raise APIError("network_or_timeout") from None
                self.sleep(2**attempt)
                continue
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                if attempt == 3:
                    raise APIError("rate_limited" if r.status_code == 429 else "canvas_unavailable")
                delay = 2**attempt
                retry = r.headers.get("Retry-After")
                if retry:
                    try:
                        delay = max(0, float(retry))
                    except ValueError:
                        try:
                            delay = max(0, (parsedate_to_datetime(retry) - self.now()).total_seconds())
                        except (ValueError, TypeError):
                            delay = 2**attempt
                if delay > 60:
                    raise APIError("retry_later")  # defer; never retry sooner than the server permits
                self.sleep(delay)
                continue
            if r.status_code != 200:
                # Only an explicit, known Canvas server message establishes a disabled page.
                # Missing navigation and arbitrary 404 responses are not proof of this state.
                if r.status_code == 404:
                    try:
                        payload = r.json()
                        message = payload.get("message", "") if isinstance(payload, dict) else ""
                        if isinstance(message, str) and message.strip().casefold().rstrip(".") == (
                            "that page has been disabled for this course"
                        ):
                            raise APIError("course_page_disabled")
                    except (ValueError, AttributeError):
                        pass
                raise APIError(
                    {
                        400: "bad_request",
                        401: "invalid_token",
                        403: "permission_denied",
                        404: "unsupported_or_missing",
                    }.get(r.status_code, "unexpected_http")
                )
            try:
                return r.json(), r.links.get("next", {}).get("url")
            except (ValueError, AttributeError):
                raise APIError("invalid_response") from None
        raise APIError("retry_exhausted")

    def pages(self, path, params=None):
        items, visited = [], set()
        for _ in range(1000):
            canonical = self._url(path)
            if canonical in visited:
                raise APIError("pagination_loop")
            visited.add(canonical)
            data, nxt = self.get(path, params)
            if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
                raise APIError("invalid_response")
            items.extend(data)
            if not nxt:
                return items
            path, params = nxt, None
        raise APIError("pagination_limit")

    def identity(self):
        user, _ = self.get("users/self/profile")
        if not isinstance(user, dict) or not user.get("id"):
            raise APIError("invalid_profile")
        return str(user["id"])

    def courses(self, include_ended=False):
        params = {"per_page": 100, "enrollment_type": "student"}
        if not include_ended:
            params["enrollment_state"] = "active"
        courses = self.pages("courses", params)
        return [
            {
                "id": int(c["id"]),
                "name": plain(c.get("name", "Course"), 200),
                "course_code": plain(c.get("course_code", ""), 200),
            }
            for c in academic_courses(courses)
            if c.get("name")
        ]

    def sync(self, courses):
        tasks, announcements, successes, failures, capabilities = {}, [], [], [], []
        for course in courses:
            cid, name = course["id"], course["name"]
            assignment_keys, assignment_quiz_ids = set(), set()
            for kind in ("assignments", "quizzes", "announcements"):
                try:
                    path = f"courses/{cid}/{kind}"
                    params = {"per_page": 100}
                    if kind == "assignments":
                        params["include[]"] = "submission"
                    if kind == "announcements":
                        path = f"courses/{cid}/discussion_topics"
                        params["only_announcements"] = "true"
                    raw_items = self.pages(path, params)
                    # Build this entire scope first, so malformed pages never masquerade as complete.
                    staged_tasks, staged_ann = {}, []
                    for raw in raw_items:
                        if (
                            raw.get("published") is False
                            or raw.get("is_announcement") is False
                            and kind == "announcements"
                        ):
                            continue
                        rid = int(raw["id"])
                        url = safe_link(raw.get("html_url", ""), self.base)
                        if kind == "announcements":
                            for field in ("posted_at", "updated_at"):
                                timestamp(raw.get(field))
                            staged_ann.append(
                                Announcement(
                                    f"{cid}:announcement:{rid}",
                                    cid,
                                    name,
                                    plain(raw.get("title", "Announcement"), 300),
                                    raw.get("posted_at"),
                                    raw.get("updated_at"),
                                    plain_lines(raw.get("message", ""), 200000),
                                    url,
                                )
                            )
                            continue
                        aid = raw.get("assignment_id") if kind == "quizzes" else rid
                        key = f"{cid}:assignment:{aid}" if aid else f"{cid}:quiz:{rid}"
                        if kind == "quizzes" and key in assignment_keys:
                            # Assignment submission and user-specific due date are authoritative.
                            continue
                        for field in ("due_at", "unlock_at", "lock_at"):
                            timestamp(raw.get(field))
                        # Quiz attempts are not guessed from quiz-wide counters.
                        status = (
                            submission_state(raw.get("submission")) if kind == "assignments" else "Unknown"
                        )
                        staged_tasks[key] = Task(
                            key,
                            cid,
                            name,
                            plain(raw.get("title" if kind == "quizzes" else "name", "Task"), 300),
                            kind,
                            raw.get("due_at"),
                            status,
                            url,
                            raw.get("points_possible"),
                            raw.get("unlock_at"),
                            raw.get("lock_at"),
                            None,
                            bool((raw.get("submission") or {}).get("excused")),
                        )
                    staged_quiz_ids = {
                        int(r["quiz_id"])
                        for r in raw_items
                        if kind == "assignments" and r.get("quiz_id") and r.get("published") is not False
                    }
                    tasks.update(staged_tasks)
                    announcements.extend(staged_ann)
                    if kind == "assignments":
                        assignment_keys.update(staged_tasks)
                        assignment_quiz_ids.update(staged_quiz_ids)
                    successes.append((cid, kind))
                except (APIError, ValueError, KeyError, TypeError) as e:
                    code = e.code if isinstance(e, APIError) else "invalid_response"
                    if kind == "quizzes" and code == "course_page_disabled":
                        recovered, recovery = self.recover_module_quizzes(
                            cid, name, assignment_keys, assignment_quiz_ids
                        )
                        tasks.update(recovered)
                        capabilities.append(
                            {
                                "course_id": cid,
                                "kind": "quizzes",
                                "state": "disabled_by_course",
                                "code": "quiz_list_disabled",
                                "recovery": recovery,
                            }
                        )
                        if recovery["status"] != "ok":
                            failures.append(
                                {"course_id": cid, "kind": "quiz_recovery", "code": recovery["code"]}
                            )
                        elif recovery["unresolved"]:
                            failures.append(
                                {"course_id": cid, "kind": "quiz_details", "code": "unverified_quiz_details"}
                            )
                    else:
                        failures.append({"course_id": cid, "kind": kind, "code": code})
        return Snapshot(courses, list(tasks.values()), announcements, successes, failures, capabilities)

    def recover_module_quizzes(self, cid, name, assignment_keys, covered_quiz_ids):
        """Supplement unavailable quiz lists through visible modules, without claiming full coverage."""
        recovered, refs = {}, {}
        result = {
            "modules": 0,
            "quiz_references": 0,
            "covered_by_assignments": 0,
            "recovered": 0,
            "unresolved": 0,
            "status": "ok",
        }
        try:
            modules = self.pages(
                f"courses/{cid}/modules", {"per_page": 100, "include[]": ["items", "content_details"]}
            )
            result["modules"] = len(modules)
            for module in modules:
                if module.get("published") is False:
                    continue
                items = module.get("items")
                if not isinstance(items, list) or len(items) != module.get("items_count"):
                    items = self.pages(
                        f"courses/{cid}/modules/{int(module['id'])}/items",
                        {"per_page": 100, "include[]": "content_details"},
                    )
                for item in items:
                    if not isinstance(item, dict):
                        raise APIError("invalid_response")
                    if item.get("type") == "Quiz" and item.get("published") is not False:
                        refs[int(item["content_id"])] = item
            result["quiz_references"] = len(refs)
            for qid, item in refs.items():
                if qid in covered_quiz_ids:
                    result["covered_by_assignments"] += 1
                    continue
                if result["recovered"] + result["unresolved"] >= 200:
                    raise APIError("recovery_limit")
                try:
                    raw, _ = self.get(f"courses/{cid}/quizzes/{qid}")
                    if not isinstance(raw, dict) or int(raw.get("id", 0)) != qid:
                        raise APIError("invalid_response")
                    aid = raw.get("assignment_id")
                    key = f"{cid}:assignment:{int(aid)}" if aid else f"{cid}:quiz:{qid}"
                    if key in assignment_keys:
                        result["covered_by_assignments"] += 1
                        continue
                except APIError:
                    # Visible module metadata can still supply a title/date; submission remains Unknown.
                    raw = item.get("content_details") or {}
                    if not isinstance(raw, dict):
                        raise APIError("invalid_response") from None
                    raw = raw | {"title": item.get("title", "Quiz"), "html_url": item.get("html_url", "")}
                    key = f"{cid}:quiz:{qid}"
                    result["unresolved"] += 1
                for field in ("due_at", "unlock_at", "lock_at"):
                    timestamp(raw.get(field))
                recovered[key] = Task(
                    key,
                    cid,
                    name,
                    plain(raw.get("title", "Quiz"), 300),
                    "quizzes",
                    raw.get("due_at"),
                    "Unknown",
                    safe_link(raw.get("html_url", ""), self.base),
                    raw.get("points_possible"),
                    raw.get("unlock_at"),
                    raw.get("lock_at"),
                )
                result["recovered"] += 1
        except (APIError, ValueError, KeyError, TypeError) as error:
            result.update(
                status="failed", code=error.code if isinstance(error, APIError) else "invalid_response"
            )
        return recovered, result
