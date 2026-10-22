"""Create a new P0 QA directory without replacing previous candidates."""

import argparse
import hashlib
import json
from pathlib import Path

from export_ui_preview import export
from ssl_resources import ssl_resources

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="p0-startupfix-20261022-01")
    name = parser.parse_args().name
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("Expected a QA directory name")
    target = root / "qa-export" / name
    target.mkdir(exist_ok=False)
    pins = {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in (root / "frontend").iterdir()
        if file.is_file()
    }
    (target / "frontend-sha256.json").write_text(json.dumps(pins, indent=2), encoding="utf-8")
    (target / "ssl-runtime-resources.json").write_text(json.dumps(ssl_resources(), indent=2), encoding="utf-8")
    export(target / "UI-Preview.html")
    print(target)
