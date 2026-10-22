"""Production-default release CLI; no QA seeding, mock UI or review entry on normal launch."""

import argparse
import sys

from canvas_agent.release_info import version

DEVELOPMENT_FLAGS = frozenset(
    {
        "--mock",
        "--qa",
        "--smoke-test",
        "--backend-check",
        "--assignment-check",
        "--credential-check",
        "--tls-check",
        "--mapping-probe",
    }
)


def entry(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if any(arg.split("=", 1)[0] in DEVELOPMENT_FLAGS for arg in arguments):
        return 2  # no native error dialog in a windowless diagnostic invocation
    if "--version" in arguments:
        print(version())
        return 0
    if "--release-selfcheck" in arguments:
        parser = argparse.ArgumentParser(description="Explicit no-window isolated release check")
        parser.add_argument("--release-selfcheck", choices=("startup", "readback", "tls"), required=True)
        parser.add_argument("--data-dir", required=True)
        args = parser.parse_args(arguments)
        if args.release_selfcheck == "tls":
            from canvas_agent.tls_check import check
        elif args.release_selfcheck == "readback":
            from canvas_agent.release_check import readback as check
        else:
            from canvas_agent.release_check import check
        try:
            return 0 if check(args.data_dir)["status"] == "passed" else 2
        except (OSError, ValueError):
            return 2  # diagnostic preconditions must not open a native exception dialog
    if "--preflight-only" in arguments:
        import json

        from canvas_agent.web_shell import webview_runtime

        result = webview_runtime()
        print(json.dumps(result))
        return 0 if result["available"] else 2
    from canvas_agent.app import main

    previous = sys.argv
    try:
        sys.argv = [previous[0], *arguments]
        return main()
    finally:
        sys.argv = previous


if __name__ == "__main__":
    raise SystemExit(entry())
