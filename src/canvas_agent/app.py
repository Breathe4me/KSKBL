import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import data_directory


def main():
    parser = argparse.ArgumentParser(description="Canvas Deadline Agent")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--data-dir", type=Path, help="Explicit isolated data directory for development/tests"
    )
    parser.add_argument(
        "--trace-native", action="store_true", help="Record process-launch call sites without arguments"
    )
    parser.add_argument(
        "--mock", "--qa", dest="qa", action="store_true", help="Explicit isolated synthetic QA mode"
    )
    parser.add_argument(
        "--mapping-probe", action="store_true", help="QA-only one-paragraph offline mapping probe"
    )
    parser.add_argument(
        "--preflight-only", action="store_true", help="Report WebView2 prerequisite without opening a window"
    )
    parser.add_argument("--backend-check", action="store_true", help="QA-only backend initialization; no GUI")
    parser.add_argument(
        "--assignment-check", action="store_true", help="QA-only mutations in NEW synthetic directory; no GUI"
    )
    group = parser.add_mutually_exclusive_group()
    parser.add_argument(
        "--credential-check", action="store_true", help="QA-only actual DPAPI check in NEW directory; no GUI"
    )
    parser.add_argument("--tls-check", action="store_true", help="QA-only planned loopback HTTPS; no GUI")
    group.add_argument("--scheduled", action="store_true")
    group.add_argument(
        "--guardian", action="store_true", help="Independent deadline checks; no daily-slot dependency"
    )
    group.add_argument("--check", action="store_true")
    group.add_argument("--remove-task", action="store_true")
    group.add_argument(
        "--test-notification", action="store_true", help="Send a local native Windows test notification"
    )
    group.add_argument(
        "--smoke-test",
        action="store_true",
        help="VM-only: open synthetic WebView2 GUI, validate startup, write result, then close",
    )
    args = parser.parse_args()
    if (
        args.qa
        or args.mapping_probe
        or args.preflight_only
        or args.backend_check
        or args.assignment_check
        or args.credential_check
        or args.tls_check
    ):
        if (
            args.scheduled
            or args.guardian
            or args.check
            or args.remove_task
            or args.test_notification
            or args.smoke_test
        ):
            parser.error("QA mode cannot register/run native monitoring or notifications")
        from ui_review_entry import main as qa_main

        forwarded = ["--mock"]
        if args.data_dir:
            forwarded += ["--data-dir", str(args.data_dir)]
        if args.mapping_probe:
            forwarded += ["--mapping-probe"]
        if args.preflight_only:
            forwarded += ["--preflight-only"]
        if args.backend_check:
            forwarded += ["--backend-check"]
        if args.assignment_check:
            forwarded += ["--assignment-check"]
        if args.credential_check:
            forwarded += ["--credential-check"]
        if args.tls_check:
            forwarded += ["--tls-check"]
        return qa_main(forwarded)
    if args.smoke_test and (
        args.data_dir is None or (args.data_dir.exists() and any(args.data_dir.iterdir()))
    ):
        parser.error("--smoke-test requires a new, empty explicit --data-dir")
    root = args.data_dir or data_directory()
    if (root / "QA_ONLY.json").exists():
        parser.error("A synthetic QA profile cannot be opened as a real account profile")
    root.mkdir(parents=True, exist_ok=True)
    if args.trace_native:
        from .process_diagnostics import enable

        enable(root)
    if args.test_notification:
        from .notifications import WindowsChannel

        result = {"version": __version__, "backend": "native_winrt"}
        try:
            WindowsChannel().send("Canvas Deadline Agent", "Local notification test / 本地通知测试", "", True)
            result["status"] = "api_accepted"
            exit_code = 0
        except Exception as e:
            result.update(status="failed", code=getattr(e, "code", type(e).__name__))
            exit_code = 3
        (root / "notification-test.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return exit_code
    if args.remove_task:
        from .schedule import remove_all_tasks as remove_task
        from .windows_native import WindowsAPIError

        result = {"version": __version__, "operation": "remove_task"}
        try:
            remove_task(root)
            result["status"] = "ok"
            exit_code = 0
        except WindowsAPIError as error:
            result.update(status="failed", code=error.code)
            if error.hresult is not None:
                result["hresult"] = f"0x{error.hresult:08X}"
            exit_code = 3
        except Exception:
            result.update(status="failed", code="task_cleanup_failed")
            exit_code = 3
        try:
            (root / "task-cleanup-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        except OSError:
            return 3
        return exit_code
    if args.scheduled or args.check or args.guardian:
        from .engine import run
        from .security import AlreadyRunning

        try:
            result = run(root, scheduled=args.scheduled, guardian_only=args.guardian)
            if args.check:
                print(json.dumps(result))
            return 0 if result["status"] in ("ok", "limited", "disabled", "not_due") else 2
        except AlreadyRunning:
            return 0
        except Exception:
            return 3  # no exception strings: credentials may be present in third-party errors
    from .web_shell import launch

    try:
        if args.smoke_test:
            from .web_qa import seed

            seed(root)
        launch(root, qa=args.smoke_test, smoke_test=args.smoke_test)
        return 0
    except Exception as error:
        # Stable type only. Never open a fallback Tk window or silently install a runtime.
        (root / "startup-error.json").write_text(
            json.dumps({"status": "failed", "code": type(error).__name__, "renderer": "edgechromium"}),
            encoding="utf-8",
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
