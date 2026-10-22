"""Local build provenance, not a signature or public-release approval. No subprocess or network."""

import argparse
import hashlib
import importlib.metadata
import json
import sys
import tomllib
from pathlib import Path

EXCLUDED = {".deps", ".git", ".pytest_cache", "__pycache__", ".ruff_cache", "build", "dist", "build-candidates", "reports", ".ui-deps", "review-builds", "qa-export", "design-reference", "release-prep", ".coverage"}


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_snapshot(root):
    import os

    result = {}
    for directory, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED)
        files = [name for name in files if name not in EXCLUDED]
        for name in directories + sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 1024:
                raise ValueError("Reparse points are not accepted in a source snapshot")
        for name in sorted(files):
            path = Path(directory) / name
            result[path.relative_to(root).as_posix()] = file_hash(path)
    return result


def snapshot_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare(project, candidate, build_id):
    candidate.mkdir(exist_ok=False, parents=True)
    snapshot = source_snapshot(project)
    source = {
        "files": snapshot,
        "inventory_sha256": snapshot_hash(snapshot),
        "git_head": None,
        "git_state": "Not attested; source inventory is the build identity",
    }
    (candidate / "source-before.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    version = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"] if (project / "pyproject.toml").exists() else "1.1.0"
    info = {
        "version": version,
        "build_id": build_id,
        "source_inventory_sha256": source["inventory_sha256"],
        "python": sys.version.split()[0],
        "tools": {name: importlib.metadata.version(name) for name in ("pyinstaller", "setuptools")},
        "formal_release_allowed": False,
        "security_clearance": "Pending",
    }
    (candidate / "build-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    strings = {
        "FileDescription": "Canvas Deadline Agent development candidate",
        "FileVersion": build_id,
        "ProductName": "Canvas Deadline Agent",
        "ProductVersion": version,
        "OriginalFilename": "CanvasDeadlineAgent.exe",
        "Comments": "Security Pending; not approved for public release",
    }
    resource = (
        f"VSVersionInfo(ffi=FixedFileInfo(filevers={tuple(int(v) for v in version.split('.')) + (0,)}, prodvers={tuple(int(v) for v in version.split('.')) + (0,)}, "
        "mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=["
        "StringFileInfo([StringTable('040904b0', ["
        + ",".join("StringStruct(" + repr(k) + "," + repr(v) + ")" for k, v in strings.items())
        + "])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])"
    )
    (candidate / "version-info.txt").write_text(resource, encoding="utf-8")


def finalize(project, candidate):
    before = json.loads((candidate / "source-before.json").read_text(encoding="utf-8"))
    current = source_snapshot(project)
    if current != before["files"]:
        raise ValueError("Source changed during build; do not distribute this candidate")
    payload = candidate / "payload" / "CanvasDeadlineAgent"
    build = json.loads((candidate / "build-info.json").read_text(encoding="utf-8"))
    installer = candidate / ("CanvasDeadlineAgent-Setup-v" + build["version"] + ".exe")
    if not (payload / "CanvasDeadlineAgent.exe").is_file() or not installer.is_file():
        raise ValueError("Both the complete payload and installer are required")
    manifest = {
        "build": json.loads((candidate / "build-info.json").read_text(encoding="utf-8")),
        "source": before,
        "payload_files": {
            p.relative_to(payload).as_posix(): file_hash(p) for p in sorted(payload.rglob("*")) if p.is_file()
        },
        "installer": {"name": installer.name, "sha256": file_hash(installer)},
        "attestation": "Unsigned local build record, not independently extracted installer payload",
        "formal_release_allowed": False,
    }
    (candidate / "BUILD_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "finalize"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--build-id")
    args = parser.parse_args()
    project, candidate = args.project.resolve(), args.candidate.resolve()
    if not candidate.is_relative_to(project / "build-candidates"):
        raise ValueError("Candidate output must be inside the development build-candidates directory")
    if args.action == "prepare":
        if not args.build_id or not all(c.isalnum() or c in ".-_" for c in args.build_id):
            raise ValueError("A simple unique build identifier is required")
        prepare(project, candidate, args.build_id)
    else:
        finalize(project, candidate)


if __name__ == "__main__":
    main()
