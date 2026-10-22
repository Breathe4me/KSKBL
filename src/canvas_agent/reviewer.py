"""Static checks only. Local text transfer is separately previewed and confirmed in GUI."""

import ast
import json
import re
from pathlib import Path

from .material_files import MaterialError
from .security import redact


def review(context, access):
    if not access.paths:
        raise MaterialError("local_access_not_authorized")
    files = access.inventory()
    result = {
        "satisfied": [],
        "possibly_unsatisfied": [],
        "missing_files": [],
        "issues": [],
        "suggestions": [],
        "unverified": [],
        "files": files,
        "label": "Static observations only; no grade prediction. Code was not executed.",
    }
    all_text = "\n".join(item["text"] for item in files)
    for item in files:
        if item["status"] != "ok":
            result["unverified"].append(f"{item['name']}: {item['status']}")
        if Path(item["name"]).suffix == ".py":
            try:
                tree = ast.parse(item["text"])
                result["satisfied"].append(item["name"] + ": Python syntax parsed (not executed).")
                if not ast.get_docstring(tree):
                    result["suggestions"].append(
                        item["name"] + ": consider module documentation where required."
                    )
            except (SyntaxError, ValueError, RecursionError):
                result["issues"].append(item["name"] + ": Python syntax could not be parsed.")
        if re.search(r"\b(TODO|FIXME)\b", item["text"]):
            result["issues"].append(
                item["name"] + ": contains TODO/FIXME markers; inspect for unfinished work."
            )
    extensions = context.get("allowed_extensions", [])
    if extensions and files and not any(Path(i["name"]).suffix.lstrip(".") in extensions for i in files):
        result["possibly_unsatisfied"].append(
            "No selected file matches Canvas allowed submission extensions."
        )
    # Only exact, explicit filenames are mechanically checked; absence is not a semantic judgment.
    required = set(
        re.findall(r"(?<![\w/])([\w-]+\.(?:pdf|docx|py|zip|md|txt|csv))\b", context["requirements"], re.I)
    )
    names = {i["name"].casefold() for i in files}
    result["missing_files"] = [name for name in sorted(required) if name.casefold() not in names]
    for criterion in context["rubric"]:
        result["unverified"].append(
            f"Rubric: {criterion['description']} — requires human/authorized AI evidence review."
        )
    if not context["rubric"]:
        result["unverified"].append("Rubric unavailable; coverage cannot be confirmed.")
    if re.search(r"citations?|references?|bibliography|引用|参考文献", context["requirements"], re.I):
        if not re.search(r"https?://|\bdoi\b|references|bibliography|参考文献", all_text, re.I):
            result["possibly_unsatisfied"].append(
                "No obvious citation markers found; check the required citation style."
            )
        result["unverified"].append("Citation authenticity, source quality and plagiarism are not verified.")
    result["unverified"].append(
        "Semantic correctness, formatting fidelity and full rubric satisfaction require review."
    )
    return result


def cloud_preview(context, result, secrets=()):
    """Returns the EXACT user-message text. No network action here."""
    payload = {
        "purpose": "Review only within explicit course AI policy; no guaranteed grade, no execution or submission.",
        "title": context["title"],
        "requirements": context["requirements"],
        "rubric": context["rubric"],
        "ai_restrictions": context["ai_restrictions"],
        "files": [{"name": f["name"], "status": f["status"], "text": f["text"]} for f in result["files"]],
    }
    text = redact(json.dumps(payload, ensure_ascii=False, indent=2), secrets)
    if len(text) > 60000:
        raise MaterialError("cloud_preview_too_large_select_fewer_files")
    return text
