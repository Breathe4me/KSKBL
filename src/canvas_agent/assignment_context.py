"""Authoritative assignment context. Missing information stays missing."""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .api import APIError
from .material_files import safe_name
from .security import plain_lines, safe_link


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag in ("a", "img"):
            value = dict(attrs).get("href" if tag == "a" else "src")
            if value:
                self.urls.append(value)


def fetch_context(api, course_id, assignment_id, course_name=""):
    cid, aid = int(course_id), int(assignment_id)
    source = f"{api.base}/courses/{cid}/assignments/{aid}"
    raw, _ = api.get(f"courses/{cid}/assignments/{aid}", {"include[]": "submission"})
    if not isinstance(raw, dict) or raw.get("id") != aid:
        raise APIError("invalid_assignment")
    description = raw.get("description") or ""
    # Keep full bounded text, and explicitly disclose any truncation.
    requirements = plain_lines(description, 200000)
    missing = []
    if len(description) > 200000:
        missing.append("Description exceeds display limit; consult the original Canvas page.")
    if not requirements.strip():
        missing.append("Assignment description unavailable or empty.")
    rubric = raw.get("rubric")
    if not isinstance(rubric, list) or not rubric:
        rubric = []
        rubric_status = "Absent, unpublished or inaccessible; no criteria inferred."
        missing.append("Rubric not provided by Canvas. Confirm with the teacher.")
    else:
        rubric_status = "Provided by Canvas"
    normalized = []
    for criterion in rubric:
        normalized.append(
            {
                "id": str(criterion.get("id", "")),
                "description": plain_lines(criterion.get("description", ""), 10000),
                "details": plain_lines(criterion.get("long_description", ""), 30000),
                "points": criterion.get("points"),
                "ratings": [
                    {
                        "description": plain_lines(r.get("description", ""), 10000),
                        "details": plain_lines(r.get("long_description", ""), 10000),
                        "points": r.get("points"),
                    }
                    for r in criterion.get("ratings", [])
                ],
            }
        )
    parser = Links()
    parser.feed(description)
    files, links = {}, []
    for value in parser.urls[:300]:
        url = urljoin(api.base + "/", value)
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password:
            continue
        if parts.netloc == urlsplit(api.base).netloc:
            match = re.search(r"(?:^|/)files/(\d+)(?:/|$)", parts.path)
            if match:
                fid = int(match.group(1))
                files[fid] = {
                    "file_id": fid,
                    "source_url": f"{api.base}/files/{fid}",
                    "status": "not_downloaded",
                }
        # Signed query strings, verifier tokens and fragments never enter generated context.
        clean = parts._replace(query="", fragment="").geturl()
        if clean not in links:
            links.append(clean)
    if files:
        missing.append(
            "Linked attachments must be downloaded and reviewed; indexed links alone are not file contents."
        )
    restrictions = [
        line
        for line in requirements.splitlines()
        if re.search(r"\bAI\b|artificial intelligence|ChatGPT|generative|人工智能|生成式", line, re.I)
    ]
    return {
        "course_id": cid,
        "assignment_id": aid,
        "course": course_name,
        "title": plain_lines(raw.get("name", ""), 1000),
        "due": raw.get("due_at"),
        "unlock": raw.get("unlock_at"),
        "lock": raw.get("lock_at"),
        "points": raw.get("points_possible"),
        "submission_types": raw.get("submission_types", []),
        "allowed_extensions": raw.get("allowed_extensions", []),
        "requirements": requirements,
        "teacher_instructions": requirements,
        "rubric": normalized,
        "rubric_status": rubric_status,
        "files": list(files.values()),
        "links": links,
        "ai_restrictions": restrictions,
        "policy_status": "Explicit assignment excerpts only; course-wide policy not verified.",
        "missing": missing,
        "url": safe_link(raw.get("html_url", source), api.base) or source,
    }


def integrate_materials(context, updates):
    by_id = {item["file_id"]: item for item in updates}
    context["files"] = [by_id.get(f["file_id"], f) for f in context["files"]]
    context["missing"] = [m for m in context["missing"] if not m.startswith("Linked attachments")]
    for item in context["files"]:
        if item.get("status") != "ok":
            context["missing"].append(
                f"Attachment {item['file_id']}: {item['status']}; review original source."
            )
        for line in item.get("text", "").splitlines():
            if re.search(r"\bAI\b|artificial intelligence|ChatGPT|generative|人工智能|生成式", line, re.I):
                excerpt = line[:3000] + " [Source: " + item["source_url"] + "]"
                if excerpt not in context["ai_restrictions"]:
                    context["ai_restrictions"].append(excerpt)
    return context


def context_markdown(context):
    c = context
    rubric = (
        "\n".join(
            f"- {r['description']} ({r['points']} points)\n  {r['details']}\n"
            + "\n".join(
                f"  - {v['description']} — {v['points']} points. {v['details']}" for v in r["ratings"]
            )
            for r in c["rubric"]
        )
        or c["rubric_status"]
    )
    files = (
        "\n".join(
            f"- Canvas file {f['file_id']}: {f.get('name', '')} [{f['status']}] {f['source_url']}"
            + (
                f"\nExported relative path: supporting_files/{int(f['file_id'])}-{safe_name(f['name'])}"
                if f.get("path")
                else ""
            )
            + (f"\n{f.get('text', '')}" if f.get("text") else "")
            for f in c["files"]
        )
        or "No linked files identified."
    )
    return {
        "assignment": f"# {c['title']}\n\n## Basic Information\nCourse: {c['course']}\n"
        + f"Due (Canvas): {c['due'] or 'Not specified'}\nAvailable from: {c['unlock']}\nUntil: {c['lock']}\n"
        + f"Points: {c['points']}\n\n## Complete Requirements\n{c['requirements']}\n\n"
        + f"## Submission Instructions\nTypes: {', '.join(c['submission_types'])}\n"
        + f"Allowed extensions: {', '.join(c['allowed_extensions']) or 'Not specified'}\n\n"
        + "## Important Constraints\n"
        + ("\n".join(c["ai_restrictions"]) or "AI policy unavailable; verify the permitted assistance scope.")
        + f"\n{c['policy_status']}\n\n## Missing Information\n"
        + "\n".join("- " + x for x in c["missing"])
        + "\n\n## Source References\n"
        + "\n".join([c["url"], *c["links"]]),
        "rubric": "# Rubric\n" + rubric,
        "requirements": "# Requirements\n" + c["requirements"] + "\n\n## Supporting Files\n" + files,
    }
