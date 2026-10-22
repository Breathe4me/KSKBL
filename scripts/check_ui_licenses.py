"""Read-only UI dependency inventory, plus explicit collection after all checks pass."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path

PINS = {
    "pywebview": "6.2.1",
    "pythonnet": "3.2.1",
    "clr_loader": "0.3.1",
    "cffi": "2.1.1",
    "pycparser": "3.11",
    "proxy_tools": "0.1.0",
    "bottle": "0.13.4",
    "typing_extensions": "4.16.0",
}


def inventory(project):
    directory = Path(project) / "docs/third-party"
    manifest_path = directory / "UI_SOURCES.json"
    supplemental = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    records, problems = [], []
    for name, version in PINS.items():
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            problems.append(f"{name}: distribution missing")
            continue
        files = [
            Path(dist.locate_file(f))
            for f in dist.files or []
            if Path(f).name.lower().startswith(("license", "copying", "notice", "authors"))
        ]
        if dist.version != version:
            problems.append(f"{name}: version {dist.version}, expected {version}")
        record = {"component": name, "version": dist.version, "files": []}
        for file in files:
            if not file.is_file() or not file.stat().st_size:
                problems.append(f"{name}: declared terms missing: {file.name}")
            else:
                record["files"].append(
                    {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                )
        records.append(record)
    # The wheel embeds Microsoft WebView2 DLLs but no accompanying SDK license file.
    # Supplemental terms must be verified against a recorded upstream source before packaging.
    sdk = {
        "component": "Microsoft.Web.WebView2 SDK",
        "version": supplemental.get("Microsoft.Web.WebView2 SDK", {}).get("version"),
        "files": [],
    }
    records.append(sdk)
    for record in records:
        if any(
            Path(entry["path"]).name.lower().startswith(("license", "copying")) for entry in record["files"]
        ):
            continue
        source = supplemental.get(record["component"], {})
        relative = Path(source.get("file", ""))
        file = (directory / relative).resolve()
        if (
            not relative.is_absolute()
            and file.is_relative_to(directory.resolve())
            and file.is_file()
            and source.get("source_url", "").startswith("https://")
            and source.get("sha256") == hashlib.sha256(file.read_bytes()).hexdigest()
        ):
            record["files"].append(
                {"path": str(file), "sha256": source["sha256"], "source_url": source["source_url"]}
            )
        else:
            problems.append(f"{record['component']}: complete verified license text missing")
    for record in records:
        source = supplemental.get(record["component"], {})
        for extra in source.get("additional_files", []):
            file = (directory / extra["file"]).resolve()
            if (
                file.is_relative_to(directory.resolve())
                and file.is_file()
                and extra.get("source_url", "").startswith("https://")
                and hashlib.sha256(file.read_bytes()).hexdigest() == extra.get("sha256")
            ):
                record["files"].append(
                    {"path": str(file), "sha256": extra["sha256"], "source_url": extra["source_url"]}
                )
            else:
                problems.append(f"{record['component']}: supplemental notice missing or mismatched")
        for relative, binding in source.get("binary_mapping", {}).items():
            base = Path(importlib.metadata.distribution("pywebview").locate_file("webview/lib")).resolve()
            file = (base / relative).resolve()
            if (
                not file.is_relative_to(base)
                or not file.is_file()
                or hashlib.sha256(file.read_bytes()).hexdigest() != binding["sha256"]
            ):
                problems.append(f"{record['component']}: SDK binary source binding mismatch")
    return {"status": "blocked" if problems else "passed", "components": records, "blockers": problems}


def collect(project, destination):
    result = inventory(project)
    if result["blockers"]:
        raise ValueError("UI license preflight failed: " + "; ".join(result["blockers"]))
    destination = Path(destination)
    for record in result["components"]:
        name = record["component"].replace(" ", "-")
        for entry in record["files"]:
            source = Path(entry["path"])
            target = destination / name / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    public = {
        "status": result["status"],
        "components": [
            {
                "component": record["component"],
                "version": record.get("version"),
                "files": [
                    {"name": Path(entry["path"]).name, "sha256": entry["sha256"]} for entry in record["files"]
                ],
            }
            for record in result["components"]
        ],
    }
    (destination / "UI_LICENSE_INVENTORY.json").write_text(json.dumps(public, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    parser.add_argument("--collect", type=Path)
    args = parser.parse_args()
    result = inventory(args.project)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.collect:
        collect(args.project, args.collect)
    print(json.dumps({"status": result["status"], "blockers": result["blockers"]}))
    raise SystemExit(bool(result["blockers"]))
