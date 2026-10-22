"""Complete application CLI in a QA delivery: default synthetic, explicit --live for manual live acceptance."""

import sys

from canvas_agent.app import main


def entry(argv):
    arguments = list(argv)
    if "--live" in arguments:
        arguments.remove("--live")
        if "--data-dir" not in arguments:
            raise ValueError("Live integration review requires an explicit separate data directory")
    elif not any(flag in arguments for flag in ("--scheduled", "--guardian", "--remove-task")):
        if "--mock" not in arguments and "--qa" not in arguments:
            arguments.append("--mock")
    previous = sys.argv
    try:
        sys.argv = [previous[0], *arguments]
        return main()
    finally:
        sys.argv = previous


if __name__ == "__main__":
    raise SystemExit(entry(sys.argv[1:]))
