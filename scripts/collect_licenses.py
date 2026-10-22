"""Collect onedir licenses; validate pinned upstream texts before writing anything."""

import hashlib
import importlib.metadata
import json
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYWINRT_COMPONENTS = (
    "winrt-runtime",
    "winrt-Windows.Foundation",
    "winrt-Windows.Foundation.Collections",
    "winrt-Windows.Data.Xml.Dom",
    "winrt-Windows.UI.Notifications",
)
PACKAGES = (
    "requests",
    "urllib3",
    "charset-normalizer",
    "idna",
    "certifi",
    "tzdata",
    "pyinstaller",
    "pywin32",
    *PYWINRT_COMPONENTS,
    "typing_extensions",
    "pypdf",
    "defusedxml",
    "pywebview",
    "pythonnet",
    "clr_loader",
    "cffi",
    "pycparser",
    "proxy_tools",
    "bottle",
)
PINNED_SOURCES = {
    "pywinrt": ("3.2.1", "pywinrt-3.2.1-LICENSE.txt", PYWINRT_COMPONENTS),
    "tcl": ("8.6.12", "tcl-8.6.12-license.terms", ("Tcl",)),
}


def checked_sources(project):
    directory = project / "docs" / "third-party"
    manifest_path = directory / "SOURCES.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported license source manifest")
    sources = {}
    for key, (version, filename, components) in PINNED_SOURCES.items():
        record = manifest["sources"][key]
        if (
            record["version"] != version
            or record["file"] != filename
            or record["components"] != list(components)
        ):
            raise ValueError(f"License source version/component mismatch: {key}")
        source = directory / filename
        data = source.read_bytes()  # missing or unreadable required texts must fail the build
        if not data or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError(f"License source SHA-256 mismatch: {key}")
        sources[key] = source
    return sources, manifest_path


def collect_licenses(
    target, project=PROJECT_ROOT, require_tcl=True, package_names=None, preserve_paths=False
):
    """Target is <onedir>/notices/licenses; no product imports, GUI or network calls."""
    target, project = Path(target), Path(project)
    sources, manifest_path = checked_sources(project)
    names = tuple(package_names) if package_names is not None else PACKAGES
    distributions = {name: importlib.metadata.distribution(name) for name in names}
    for name in PYWINRT_COMPONENTS:
        if distributions[name].version != "3.2.1":
            raise ValueError(f"PyWinRT runtime version mismatch: {name}")
    init = target.parent.parent / "_internal" / "_tcl_data" / "init.tcl"
    matches = (
        re.findall(r"(?m)^\s*package\s+require\s+-exact\s+Tcl\s+(\S+)", init.read_text(encoding="utf-8"))
        if require_tcl or init.exists()
        else []
    )
    if (require_tcl or init.exists()) and matches != ["8.6.12"]:
        raise ValueError("Tcl payload version mismatch; expected 8.6.12")

    copies = []
    for name, dist in distributions.items():
        for entry in dist.files or []:
            if any(term in Path(entry).name.lower() for term in ("license", "copying", "notice", "authors")):
                source = Path(dist.locate_file(entry))
                if not source.is_file():
                    raise FileNotFoundError(f"Required package license missing: {name}/{entry}")
                relative = Path(entry) if preserve_paths else Path(entry).name
                if preserve_paths and (relative.is_absolute() or ".." in relative.parts):
                    raise ValueError("Unsafe license record path")
                copies.append((source, target / name / relative))
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise FileNotFoundError("Required Python LICENSE.txt is missing")
    copies.append((python_license, target / "Python-LICENSE.txt"))
    copies.extend((sources["pywinrt"], target / name / "LICENSE.txt") for name in PYWINRT_COMPONENTS)
    copies.extend(
        (
            (sources["tcl"], target / "tcl" / "license.terms"),
            (manifest_path, target / "SOURCES.json"),
        )
    )
    for source, destination in copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)  # preserve original bytes, including line endings
    return [destination for _, destination in copies]


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist/CanvasDeadlineAgent/notices/licenses")
    collected = collect_licenses(output)
    print(f"Collected {len(collected)} license/provenance files")
