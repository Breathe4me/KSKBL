# Build and test (Code-Only)

Source core version is 1.2.0; the immutable release-info.json identifies this package as 1.2.0-beta.1. Build/test Python 3.12, pinned pyproject dependencies, PyInstaller and Inno Setup 6 are required on the builder. Users do not install Python. No tools are downloaded or installed automatically.

Use an isolated environment and dependency path. Install dependencies only when separately approved. Never copy virtualenvs, `.ui-deps`, private profiles or QA outputs into source/release archives.

```
python -B -m ruff check src scripts tests
python -B -m pytest -q -p code_only_guard --ignore=tests/test_gui.py --ignore=tests/test_v12_desktop.py
```

Set PYTHONPATH to this project's src/scripts and explicitly selected build dependencies. Headless browser scripts require an already installed Playwright/Edge runtime; do not launch a visible browser. Run scripts/test_frontend.cjs, test_startup_frontend.cjs, test_bootstrap_protocol.cjs, test_assignment_mutation.cjs, test_operation_trace.cjs, test_full_integration.cjs and test_credentials_frontend.cjs against newly generated isolated fixtures. Never reuse a real profile.

The local release builder uses ReleaseCandidate.spec and scripts/release_entry.py. Unlike QAExport.spec, normal launch calls the production app without adding --mock; QA/review/seeding modules are excluded. Explicit --release-selfcheck startup uses a NEW directory for actual empty production Bridge/DPAPI validation. Explicit --release-selfcheck tls accepts only a prepared local loopback plan. These are no-window diagnostics, not GUI acceptance, and their temporary profiles are never packed.

Before building, collect version/hash-bound third-party originals, preserve ssl-runtime-resources.json and all frontend hashes. The vendor Python's `codex-rejected-cas.pem` must be present beside frozen ssl.py. Missing resources fail preparation/finalization; never monkeypatch SSLContext or set verify=False. Local HTTPS checks use throwaway test CA files without changing OS trust.

The script scripts/prepare_release_candidate.py supports local prepare/collect/archives stages and refuses overwriting existing outputs. See its --help and the local evidence directory for exact executable paths/commands. The legacy scripts/build.ps1 retains its own visual/license gates. No public-clearance flag is set by a local build.

No-window tests must mock external services/notifications/scheduler or use the local HTTPS fixture. Do not execute Setup/uninstallers, GUI launch, VirtualBox, real Canvas, PushPlus or paid AI automatically. Manual acceptance runs only in existing CanvasDeadlineAgent-Smoke. Do not push Git or create a release from build scripts.
