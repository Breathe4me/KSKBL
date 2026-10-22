"""Opt-in pytest gate: reject native-window test collection before fixtures execute."""

from pathlib import Path

import pytest


def pytest_collection_modifyitems(items):
    forbidden = {"test_gui.py", "test_v12_desktop.py"}
    if any(Path(item.path).name in forbidden for item in items):
        raise pytest.UsageError(
            "Code-Only mode forbids native GUI tests. Exclude tests/test_gui.py and "
            "tests/test_v12_desktop.py; run them only in a separately authorized VM session."
        )
