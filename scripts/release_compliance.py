"""Release-only collection policy; no GUI, product import, network or system mutation."""

import ast
import hashlib
import importlib.metadata as metadata
import json
import shutil
from pathlib import Path

FORBIDDEN_MODULES = ("webview.__pyinstaller", "PyInstaller", "setuptools", "_distutils_hack")


def runtime_module(name):
    return not any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_MODULES)


def windows_system_binary(name):
    """The supported Windows 11 OS supplies its API sets and Universal CRT."""
    name = Path(name).name.casefold()
    return name == "ucrtbase.dll" or name.startswith(("api-ms-win-", "ext-ms-win-"))


def runtime_binaries(entries):
    retained, removed = [], []
    for entry in entries:
        name, source, kind = entry
        if windows_system_binary(name):
            removed.append({"name": name, "reason": "Windows_11_system_component_not_redistributed"})
        elif "native/libheif/" in str(source).replace("\\", "/").casefold():
            raise ValueError("Unreviewed unrelated native search-path input")
        else:
            retained.append((name, source, kind))
    return retained, removed


def native_distribution(project):
    """Check concrete permissive-license obligations, not an invented source-history rule."""
    directory = Path(project) / "docs/third-party"
    policy = json.loads((directory / "NATIVE_DISTRIBUTION.json").read_text(encoding="utf-8"))
    if policy.get("schema") != 1 or not policy.get("native_files"):
        raise ValueError("Missing native distribution bindings")
    for row in policy["notice_records"]:
        file = (directory / row["file"]).resolve()
        if not file.is_relative_to(directory.resolve()):
            raise ValueError("Unsafe native notice path")
        if hashlib.sha256(file.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Native notice missing or changed")
    prerequisite = policy["msvc_prerequisite"]
    if prerequisite["mode"] != "user_installs_from_Microsoft_not_bundled" or set(prerequisite["files"]) != {
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "mfc140u.dll",
    }:
        raise ValueError("Unverified Microsoft runtime distribution policy")
    return policy


def stage_native_inputs(project, source, destination):
    policy = native_distribution(project)
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_relative_to((Path(project) / "release-prep").resolve()):
        raise ValueError("Native inputs must be in isolated release-prep")
    plan = []
    for name, row in policy["overrides"].items():
        file = source / name
        if Path(name).name != name or hashlib.sha256(file.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Official native input hash mismatch")
        plan.append(file)
    destination.mkdir(exist_ok=False)
    for file in plan:
        shutil.copyfile(file, destination / file.name)


def release_native_binaries(entries, project, native_inputs):
    """Substitute only hash-bound ABI-compatible inputs; use a checked system CRT prerequisite."""
    policy = native_distribution(project)
    retained, removed = runtime_binaries(entries)
    result, substitutions = [], []
    found = set()
    for name, source, kind in retained:
        normalized = name.replace("\\", "/")
        if Path(normalized).name.casefold() in policy["msvc_prerequisite"]["files"]:
            removed.append({"name": name, "reason": "Microsoft_runtime_user_installed_prerequisite"})
            continue
        if normalized in policy["overrides"]:
            row = policy["overrides"][normalized]
            original = hashlib.sha256(Path(source).read_bytes()).hexdigest()
            if original not in {row["replaces_sha256"], row["sha256"]}:
                raise ValueError("Unexpected native input to replace")
            source = Path(native_inputs) / normalized
            if hashlib.sha256(source.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("Replacement native input hash mismatch")
            substitutions.append({"name": normalized, "source": str(source), "sha256": row["sha256"]})
            found.add(normalized)
        result.append((name, str(source), kind))
    if found != set(policy["overrides"]):
        raise ValueError("Required native replacements absent from analysis")
    return result, removed, substitutions


def toc_records(file):
    rows = []

    def visit(value):
        if isinstance(value, (tuple, list)):
            if len(value) == 3 and all(isinstance(item, str) for item in value):
                rows.append(value)
            else:
                for child in value:
                    visit(child)

    visit(ast.literal_eval(Path(file).read_text(encoding="utf-8")))
    return rows


def frozen_inventory(exe):
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    forbidden = [name for name in pyz.toc if not runtime_module(name)]
    if forbidden:
        raise ValueError("Build-tool modules in frozen runtime: " + ", ".join(sorted(forbidden)))
    return set(pyz.toc) | set(archive.toc)


def actual_distributions(analysis, exe, payload):
    modules = frozen_inventory(exe)
    owners = {}
    distributions = list(metadata.distributions())
    for dist in distributions:
        for entry in dist.files or []:
            path = str(Path(dist.locate_file(entry)).resolve()).casefold()
            owners.setdefault(path, []).append(dist)
    found, unknown = {}, []
    for name, source, kind in toc_records(analysis):
        if kind not in {"PYMODULE", "PYSOURCE", "EXTENSION", "BINARY", "DATA"}:
            continue
        packaged_file = (Path(payload) / "_internal" / name).is_file()
        if name not in modules and not packaged_file:
            continue
        file = Path(source)
        if not file.is_file():
            continue
        matches = owners.get(str(file.resolve()).casefold(), [])
        for dist in matches:
            found[dist.metadata["Name"]] = dist
        if not matches and any(term in str(file) for term in ("site-packages", ".ui-deps", "\\.deps\\")):
            if file.suffix.lower() in {".py", ".dll", ".pyd"}:
                unknown.append(name)
    if unknown:
        raise ValueError("Unidentified frozen third-party files: " + ", ".join(sorted(set(unknown))))
    return found


def notice_records(dist):
    records = []
    for entry in dist.files or []:
        relative = Path(entry)
        if not any(term in relative.name.lower() for term in ("license", "copying", "notice", "authors")):
            continue
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe license record path")
        source = Path(dist.locate_file(entry))
        data = source.read_bytes()
        if not data:
            raise ValueError("Empty license original")
        records.append((relative, source, hashlib.sha256(data).hexdigest()))
    return records


def collect_closure(project, payload, analysis):
    """Stage originals for the actual frozen closure, with collision-free RECORD paths."""
    from check_ui_licenses import collect as collect_ui
    from collect_licenses import PACKAGES, PYWINRT_COMPONENTS, collect_licenses

    project, payload = Path(project), Path(payload)
    actual = actual_distributions(analysis, payload / "CanvasDeadlineAgent.exe", payload)
    names = sorted(set(PACKAGES) | set(actual))
    # Validate all originals before any output. Pinned missing-wheel terms are checked by collectors.
    plans = {name: notice_records(metadata.distribution(name)) for name in names}
    allowed_supplements = set(PYWINRT_COMPONENTS) | {"proxy_tools"}
    if any(not files and name not in allowed_supplements for name, files in plans.items()):
        raise ValueError("Actual dependency lacks complete original license")
    target = payload / "notices/licenses"
    manifest = json.loads((project / "docs/third-party/REDISTRIBUTION_SOURCES.json").read_text())
    supplemental = []
    for record in manifest["files"]:
        source = (project / "docs/third-party" / record["file"]).resolve()
        destination = (target / record["destination"]).resolve()
        if not source.is_relative_to((project / "docs/third-party").resolve()):
            raise ValueError("Unsafe supplemental source")
        if not destination.is_relative_to(target.resolve()):
            raise ValueError("Unsafe supplemental destination")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Supplemental license/source hash mismatch")
        supplemental.append((source, destination))
    collect_licenses(target, project, require_tcl=False, package_names=names, preserve_paths=True)
    collect_ui(project, target)
    import shutil

    for source, destination in supplemental:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    result = []
    for name in names:
        dist = metadata.distribution(name)
        files = [
            {"record_path": relative.as_posix(), "sha256": digest} for relative, _, digest in plans[name]
        ]
        result.append(
            {"component": name, "version": dist.version, "actually_frozen": name in actual, "files": files}
        )
    value = {
        "status": "ORIGINALS_COLLECTED_NOT_LEGAL_APPROVAL",
        "components": result,
        "supplemental_sources": manifest,
        "native_redistribution_approved": False,
    }
    (target / "RELEASE_LICENSE_CLOSURE.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    return value


def native_gate(project, payload, analysis, native_inputs=None):
    """Require specific notices and byte bindings; no blanket vendor-history veto."""
    payload, project = Path(payload), Path(project)
    policy = native_distribution(project)
    sources = {name.replace("\\", "/"): Path(source) for name, source, _ in toc_records(analysis)}
    if native_inputs:
        for name in policy["overrides"]:
            sources[name] = Path(native_inputs) / name
    for record in policy["notice_records"]:
        original = project / "docs/third-party" / record["file"]
        staged = payload / "notices/licenses" / record["destination"]
        if not staged.is_file() or original.read_bytes() != staged.read_bytes():
            raise ValueError("Native notice was not actually staged")
    sdk = json.loads((project / "docs/third-party/UI_SOURCES.json").read_text(encoding="utf-8"))[
        "Microsoft.Web.WebView2 SDK"
    ]["binary_mapping"]
    rows = []
    for file in sorted(payload.rglob("*")):
        if file.suffix.lower() not in {".exe", ".dll", ".pyd"} or file.parent == payload:
            continue
        name = file.relative_to(payload / "_internal").as_posix()
        source = sources.get(name)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        state, reason = "BLOCKED", "native_source_or_redistribution_basis_unverified"
        if not source or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            reason = "build_input_identity_mismatch_or_missing"
        elif name.startswith("webview/lib/") and name.removeprefix("webview/lib/") in sdk:
            binding = sdk[name.removeprefix("webview/lib/")]
            if binding["sha256"] == digest:
                state, reason = "PASS", "official_NuGet_hash_and_original_LICENSE_NOTICE"
        elif file.name.casefold().startswith(("vcruntime", "msvcp")):
            reason = "Microsoft_runtime_must_be_external_prerequisite_not_bundled"
        elif name in policy["native_files"]:
            if policy["native_files"][name]["sha256"] == digest:
                state, reason = "PASS", "hash_bound_permissive_terms_notices_and_packaging_change_summary"
            else:
                reason = "reviewed_native_byte_binding_changed"
        elif "codex-runtimes" in str(source):
            reason = "new_unreviewed_vendor_native_file"
        else:
            state, reason = (
                "PASS_PACKAGE_TERMS_SCOPE",
                "installed_distribution_identity_and_original_terms_collected",
            )
        rows.append({"file": name, "sha256": digest, "status": state, "reason": reason})
    if not rows:
        raise ValueError("No native DLLs examined; cannot approve an empty inventory")
    blocked = [row for row in rows if row["status"] == "BLOCKED"]
    return {
        "status": "BLOCKED" if blocked else "PASS_NATIVE_REDISTRIBUTION_SCOPE",
        "files": rows,
        "blockers": blocked,
        "public_release_approved": False,
        "msvc_prerequisite": policy["msvc_prerequisite"],
        "complete_vendor_build_history_required_by_identified_licenses": False,
        "limitation": "Package terms scope is not a malware verdict or final legal approval.",
    }
