"""Scan distribution source and all local Git commits. Report paths/rules, never matches."""

import argparse
import json
import re
import subprocess
from pathlib import Path

RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "service-key": re.compile(rb"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}\b"),
    "literal-credential": re.compile(
        rb"""(?i)(?:token|api_key|password)\s*[:=]\s*["'][a-zA-Z0-9_./+-]{24,}["']"""
    ),
    "private-ip": re.compile(rb"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"),
    "personal-email": re.compile(rb"\b[A-Za-z0-9._%+-]+@(?:gmail|hotmail|outlook|qq|163)\.[A-Za-z]{2,}\b"),
}
EXCLUDED = {".git", "build", "dist", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__", "htmlcov"}
EXCLUDED |= {".deps", "qa", "reports"}
PRIVATE_SUFFIXES = {".sqlite", ".db", ".dpapi", ".log", ".bak"}


def scan(root):
    findings = []

    def inspect(name, data):
        path = Path(name)
        if path.suffix in PRIVATE_SUFFIXES or path.name.startswith(".env"):
            findings.append({"file": name, "rule": "private-file"})
        for rule, pattern in RULES.items():
            if pattern.search(data):
                findings.append({"file": name, "rule": rule})

    for path in root.rglob("*"):
        if path.is_file() and not any(
            part in EXCLUDED or part.endswith(".egg-info") for part in path.relative_to(root).parts
        ):
            inspect(path.relative_to(root).as_posix(), path.read_bytes())
    revisions = []
    if (root / ".git").exists():
        result = subprocess.run(["git", "rev-list", "--all"], cwd=root, capture_output=True, check=False)  # noqa: S603,S607
        revisions = result.stdout.decode().splitlines()
        for rev in revisions:
            files = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", rev], cwd=root, capture_output=True, check=True
            )  # noqa: S603,S607
            for name in files.stdout.decode().splitlines():
                data = subprocess.run(
                    ["git", "show", f"{rev}:{name}"], cwd=root, capture_output=True, check=True
                ).stdout  # noqa: S603,S607
                inspect(f"history/{rev[:12]}/{name}", data)
    return {
        "status": "passed" if not findings else "blocked",
        "git_commits_scanned": len(revisions),
        "scope": "new project source only; original repositories unavailable",
        "findings": findings,
        "limitation": "Pattern-based check; manual review and original-history audit remain required",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = scan(Path(__file__).resolve().parents[1])
    output = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output)
    raise SystemExit(0 if result["status"] == "passed" else 1)
