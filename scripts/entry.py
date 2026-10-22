import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    project = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(project / "src"), str(project / ".ui-deps"), str(project / ".deps")]

from canvas_agent.app import main  # noqa: E402 - isolated source scheduler bootstrap

if __name__ == "__main__":
    raise SystemExit(main())
