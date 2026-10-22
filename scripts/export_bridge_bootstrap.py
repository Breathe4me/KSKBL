"""Export installed pywebview's real JS API for offscreen transport-contract tests. No native imports."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from webview.util import load_js_files

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    window = SimpleNamespace(
        uid="headless-contract",
        js_api_endpoint=None,
        state={},
        text_select=True,
        zoomable=False,
        draggable=False,
        easy_drag=False,
        frameless=False,
    )
    prelude, finish = load_js_files(window, "edgechromium")
    finish = finish % {"functions": json.dumps([{"func": "invoke", "params": ["method", "params", "trace"]}])}
    parser.parse_args().output.write_text(
        json.dumps({"prelude": prelude, "finish": finish}), encoding="utf-8"
    )
