"""Immutable packaged release identity, with the unchanged source core version as fallback."""

import json
import re
import sys
from pathlib import Path

from . import __version__


def version():
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        file = Path(sys._MEIPASS) / "release-info.json"
        if file.is_file():
            value = json.loads(file.read_text(encoding="utf-8"))["version"]
            if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-beta\.\d+)?", value):
                raise ValueError("Invalid release identity")
            return value
    return __version__
