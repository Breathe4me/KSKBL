"""Archive only a manifest-bound development candidate. Never changes historic releases/reports."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from build_manifest import file_hash, source_snapshot


def archive(candidate, project):
    candidate, project = candidate.resolve(), project.resolve()
    if not candidate.is_relative_to(project / "build-candidates"):
        raise ValueError("Only isolated development candidates may be archived")
    manifest = json.loads((candidate / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("formal_release_allowed") is not False:
        raise ValueError("Development archive must retain the public-release block")
    if source_snapshot(project) != manifest["source"]["files"]:
        raise ValueError("Sources changed since the recorded build")
    installer = candidate / manifest["installer"]["name"]
    if not installer.resolve().is_relative_to(candidate):
        raise ValueError("Unsafe installer path")
    if file_hash(installer) != manifest["installer"]["sha256"]:
        raise ValueError("Installer hash mismatch")
    payload = candidate / "payload/CanvasDeadlineAgent"
    actual_members = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
    if actual_members != set(manifest["payload_files"]):
        raise ValueError("Payload inventory changed since build")
    jobs = [
        (
            "CanvasDeadlineAgent-Source-v1.1.0.zip",
            project,
            manifest["source"]["files"],
            "canvas-deadline-agent-v1.1",
        ),
        (
            "CanvasDeadlineAgent-Portable-v1.1.0.zip",
            candidate / "payload/CanvasDeadlineAgent",
            manifest["payload_files"],
            "CanvasDeadlineAgent",
        ),
    ]
    if (candidate / "SHA256SUMS.txt").exists():
        raise FileExistsError("Checksums already exist; use a new candidate")
    for name, root, files, _prefix in jobs:
        if (candidate / name).exists():
            raise FileExistsError("An archive already exists; use a new candidate")
        for relative, expected in files.items():
            path = root / relative
            if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
                raise ValueError("Unsafe manifest member")
            if file_hash(path) != expected:
                raise ValueError("Manifest member hash mismatch")
    hashes = {installer.name: file_hash(installer)}
    for name, root, files, prefix in jobs:
        with zipfile.ZipFile(candidate / name, "x", zipfile.ZIP_DEFLATED) as target:
            for relative, expected in sorted(files.items()):
                data = (root / relative).read_bytes()
                if hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError("A member changed while archiving")
                target.writestr(prefix + "/" + relative, data)
        hashes[name] = file_hash(candidate / name)
    with (candidate / "SHA256SUMS.txt").open("x", encoding="ascii") as stream:
        for name, digest in sorted(hashes.items()):
            stream.write(digest + "  " + name + "\n")
    return hashes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    archive(args.candidate, project)


if __name__ == "__main__":
    main()
