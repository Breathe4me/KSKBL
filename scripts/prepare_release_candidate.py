"""Local-only production RC preparation; no upload, GUI execution or public-release override."""

import argparse
import importlib.metadata as metadata
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

from build_manifest import file_hash, snapshot_hash, source_snapshot
from check_ui_licenses import inventory
from release_compliance import collect_closure, native_gate, stage_native_inputs
from ssl_resources import public_ssl_resources

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.2.0-beta.1"
TARGET = Path(os.environ.get("CDA_RELEASE_PREP", ROOT / "release-prep" / ("v" + VERSION))).resolve()
if not TARGET.is_relative_to(ROOT / "release-prep"):
    raise ValueError("Release preparation must stay inside release-prep")


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def prepare():
    if inventory(ROOT)["status"] != "passed":
        raise ValueError("Verified UI license texts/source bindings required before building")
    for name in ("evidence", "artifacts", "repository"):
        (TARGET / name).mkdir(parents=True, exist_ok=True)
    inputs = TARGET / "build-inputs"
    inputs.mkdir(exist_ok=False)
    stage_native_inputs(ROOT, os.environ["CDA_NATIVE_INPUTS"], inputs / "native-assets")
    source = source_snapshot(ROOT)
    write(inputs / "source-before.json", source)
    write(inputs / "ssl-runtime-resources.json", public_ssl_resources())
    write(
        inputs / "frontend-sha256.json",
        {file.name: file_hash(file) for file in (ROOT / "frontend").iterdir() if file.is_file()},
    )
    record = {
        "version": VERSION,
        "core_version": "1.2.0",
        "default_mode": "production",
        "synthetic_profile_bundled": False,
        "publication_approved": False,
        "application_license": "DRAFT_NO_PUBLIC_GRANT",
        "build_purpose": "INTERNAL_VERIFICATION_ONLY"
        if os.environ.get("CDA_VERIFY_ONLY") == "1"
        else "LOCAL_RC_PREPARATION",
        "source_inventory_sha256": snapshot_hash(source),
    }
    write(inputs / "release-info.json", record)
    write(
        TARGET / "evidence/BUILD_INPUTS.json",
        record | {"python": sys.version, "pyinstaller": metadata.version("pyinstaller")},
    )
    strings = {
        "FileDescription": "Canvas Deadline Agent local Beta release candidate",
        "FileVersion": VERSION,
        "ProductName": "Canvas Deadline Agent",
        "ProductVersion": VERSION,
        "OriginalFilename": "CanvasDeadlineAgent.exe",
        "Comments": "Local RC; public publication and application license approval pending",
    }
    text = (
        "VSVersionInfo(ffi=FixedFileInfo(filevers=(1,2,0,0), prodvers=(1,2,0,0), mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=[StringFileInfo([StringTable('040904b0', ["
        + ",".join("StringStruct(" + repr(k) + "," + repr(v) + ")" for k, v in strings.items())
        + "])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])"
    )
    (inputs / "version-info.txt").write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {"status": "local_build_prepared", "public_release_allowed": False, "source_files": len(source)}
        )
    )


def collect_payload():
    payload = TARGET / "payload/CanvasDeadlineAgent"
    if (payload / "PAYLOAD_SHA256.json").exists():
        raise FileExistsError("Refusing finalized payload replacement")
    destination = payload / "notices/licenses"
    analysis = TARGET / "build-work/ReleaseCandidate/Analysis-00.toc"
    collect_closure(ROOT, payload, analysis)
    write(
        TARGET / "evidence/NATIVE_REDISTRIBUTION_GATE.json",
        native_gate(ROOT, payload, analysis, TARGET / "build-inputs/native-assets"),
    )
    for filename in (
        "openssl-3.5.8-LICENSE.txt",
        "NATIVE_SOURCES.json",
        "UI_SOURCES.json",
        "NATIVE_DISTRIBUTION.json",
    ):
        shutil.copyfile(ROOT / "docs/third-party" / filename, destination / filename)
    for name in (
        "LICENSE",
        "README.md",
        "PRIVACY.md",
        "SECURITY.md",
        "INSTALL.md",
        "KNOWN_LIMITATIONS.md",
        "THIRD_PARTY_NOTICES.md",
    ):
        shutil.copyfile(ROOT / name, payload / name)
    shutil.copyfile(ROOT / "scripts/Check-Prerequisites.ps1", payload / "Check-Prerequisites.ps1")
    required = [
        "python312.dll",
        "_ssl.pyd",
        "libssl-3-x64.dll",
        "libcrypto-3-x64.dll",
        "certifi/cacert.pem",
        "ssl-runtime-resources.json",
        "release-info.json",
        "_sqlite3.pyd",
        "pythonnet/runtime/Python.Runtime.dll",
        "clr_loader/ffi/dlls/amd64/ClrLoader.dll",
        "webview/lib/Microsoft.Web.WebView2.Core.dll",
        "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
        "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
    ]
    for relative in required:
        if not (payload / "_internal" / relative).is_file():
            raise FileNotFoundError(relative)
    for row in public_ssl_resources()["files"]:
        if file_hash(payload / "_internal" / row["destination"]) != row["sha256"]:
            raise ValueError("TLS companion policy hash mismatch")
    for file in (ROOT / "frontend").iterdir():
        if file.is_file() and file_hash(file) != file_hash(payload / "_internal/frontend" / file.name):
            raise ValueError("Frontend changed")
    forbidden = [
        file
        for file in payload.rglob("*")
        if file.is_file()
        and (
            file.suffix.lower() in {".dpapi", ".sqlite", ".db", ".key", ".pfx", ".p12", ".log"}
            or file.name in {"config.json", "QA_ONLY.json", "UI-Preview.html", "qa_mock_adapter.js"}
        )
    ]
    if forbidden:
        raise ValueError("User/profile/mock files must not enter a release")
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(payload / "CanvasDeadlineAgent.exe"))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    for name in (
        "ui_review_entry",
        "canvas_agent.web_qa",
        "canvas_agent.backend_check",
        "canvas_agent.credential_check",
        "tkinter",
    ):
        if name in pyz.toc:
            raise ValueError("QA/legacy GUI module unexpectedly bundled: " + name)
    pins = {
        file.relative_to(payload).as_posix(): file_hash(file)
        for file in sorted(payload.rglob("*"))
        if file.is_file()
    }
    write(payload / "PAYLOAD_SHA256.json", pins)
    (payload / "SHA256SUMS.txt").write_text(
        "".join(value + "  " + name + "\n" for name, value in pins.items()), encoding="utf-8"
    )
    write(
        TARGET / "evidence/PAYLOAD_VERIFICATION.json",
        {
            "status": "PASS_LOCAL_STATIC_ONLY",
            "files": len(pins),
            "required_files": required,
            "default_mode": "production",
            "QA_modules_excluded": True,
            "frontend_hashes_match": True,
            "no_user_or_QA_data": True,
            "exe_sha256": file_hash(payload / "CanvasDeadlineAgent.exe"),
        },
    )
    print(json.dumps({"status": "payload_collected_verified", "files": len(pins)}))


def archives():
    payload = TARGET / "payload/CanvasDeadlineAgent"
    native = json.loads((TARGET / "evidence/NATIVE_REDISTRIBUTION_GATE.json").read_text(encoding="utf-8"))
    if native.get("status") != "PASS_NATIVE_REDISTRIBUTION_SCOPE":
        raise ValueError("Native redistribution evidence incomplete; no new RC archives or installer")
    for proof in ("FROZEN_RELEASE_CHECK.json", "FROZEN_TLS_CHECK.json", "NATIVE_DEPENDENCY_CHECK.json"):
        value = json.loads((TARGET / "evidence" / proof).read_text(encoding="utf-8"))
        if value.get("status") != "passed" or value.get("exe_sha256") != file_hash(
            payload / "CanvasDeadlineAgent.exe"
        ):
            raise ValueError("Actual frozen gates required before archiving")
    portable = TARGET / "artifacts" / f"CanvasDeadlineAgent-v{VERSION}-Portable.zip"
    with zipfile.ZipFile(portable, "x", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(payload.rglob("*")):
            if file.is_file():
                archive.write(file, f"CanvasDeadlineAgent-v{VERSION}/" + file.relative_to(payload).as_posix())
    source = source_snapshot(ROOT)
    if source != json.loads((TARGET / "build-inputs/source-before.json").read_text(encoding="utf-8")):
        raise ValueError("Source changed during the build")
    repository = TARGET / "repository"
    if any(repository.iterdir()):
        raise FileExistsError("Repository staging is not empty")
    for name in source:
        path = Path(name)
        public_root = {
            "README.md",
            "README_CN.md",
            "LICENSE",
            "PRIVACY.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "RELEASE_NOTES.md",
            "INSTALL.md",
            "KNOWN_LIMITATIONS.md",
            "BUILD_AND_TEST.md",
            "THIRD_PARTY_NOTICES.md",
            ".gitignore",
            "pyproject.toml",
            "requirements-runtime.txt",
            "requirements-ui.txt",
            "CanvasDeadlineAgent.spec",
            "ReleaseCandidate.spec",
            "QAExport.spec",
            "UIReview.spec",
        }
        if len(path.parts) == 1 and name not in public_root:
            continue
        if (
            path.parts[0] not in {"src", "scripts", "tests", "frontend", "assets", "installer", "docs"}
            and len(path.parts) != 1
        ):
            continue
        if (
            path.suffix
            in {".pyc", ".zip", ".exe", ".db", ".sqlite", ".log", ".dpapi", ".bak", ".key", ".pfx", ".p12"}
            or path.name.startswith(".env")
            or path.name == "config.json"
        ):
            continue
        destination = repository / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    source_archive = TARGET / "artifacts" / f"CanvasDeadlineAgent-v{VERSION}-Source.zip"
    with zipfile.ZipFile(source_archive, "x", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(repository.rglob("*")):
            if file.is_file():
                archive.write(
                    file, "CanvasDeadlineAgent-" + VERSION + "/" + file.relative_to(repository).as_posix()
                )
    with zipfile.ZipFile(portable) as archive:
        if archive.testzip():
            raise ValueError("ZIP CRC failure")
        for file in payload.rglob("*"):
            if file.is_file():
                import hashlib

                if hashlib.sha256(
                    archive.read(f"CanvasDeadlineAgent-v{VERSION}/" + file.relative_to(payload).as_posix())
                ).hexdigest() != file_hash(file):
                    raise ValueError("Portable archive mismatch")
    write(
        TARGET / "evidence/ARCHIVE_VERIFICATION.json",
        {
            "portable": "PASS_ALL_FILES_CRC_SHA256",
            "source": "current_clean_tree_no_history",
            "source_files": sum(file.is_file() for file in repository.rglob("*")),
            "source_inventory_sha256": snapshot_hash(source),
        },
    )
    print(
        json.dumps(
            {"status": "archives_created_verified", "portable": str(portable), "source": str(source_archive)}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "collect", "archives"))
    parser.add_argument("--local-only", action="store_true", required=True)
    args = parser.parse_args()
    {"prepare": prepare, "collect": collect_payload, "archives": archives}[args.stage]()
