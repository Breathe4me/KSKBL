# Architecture

The UI redesign uses bundled HTML/CSS/JavaScript in pywebview's Windows WebView2 renderer.
The approved prototype supplies the shared layout; theme variables supply the two palettes.
`web_shell.py` verifies frozen frontend hashes, assembles the real frontend into a per-run local
runtime-page folder and uses WebView2 virtual-host mapping. The lifecycle adapter maps the same
CoreWebView2 before pywebview assigns Source; no local HTTP server or fixed startup sleep is used.
Remote navigation/downloads remain denied. Native navigation + real DOM/bridge/backend/UI Ready
are all required; see startup diagnostics and the offline navigation regressions.
`web_bridge.py` exposes one validated `invoke(method, params)` capability boundary. Credentials
remain in Python/DPAPI; state DTOs contain credential presence only. `web_copilot.py` retains
explicit file grants, full-text cloud previews, single-use transfer tickets and host approvals.
CLI `--scheduled` uses the same existing engine without loading GUI. Legacy Tk controllers and
their original tests remain available as compatibility code; the application does not fall back to Tk.

Current delivery is code-only. Chromium DOM tests replace native window interaction during this
phase, but do not certify WebView2 transport, Windows DPI, accessibility or final visual acceptance.
The user has since approved the existing UI appearance; this functional integration does not redesign it
and does not infer acceptance of the newly built candidate. See FUNCTIONAL_INTEGRATION_MAP.md,
BRIDGE_API.md and INTEGRATION_VM_ACCEPTANCE.md for production services versus explicit QA behavior.

- `api.py`: HTTPS GET-only Canvas client, bounded retry, same-origin API pagination, redirects rejected.
- `models.py`, `rules.py`: identity-based deduplication, explicit submission states, UTC deadline arithmetic.
- `engine.py`: current-user OS lock around a check, account binding, complete-scope snapshots, announcement baselines.
- `storage.py`: SQLite WAL, FULL synchronous mode, transactions, schema version, bounded event log and delivery ledger.
- `config.py`, `security.py`: validated versioned JSON; atomic replacement; DPAPI credential blobs.
- `schedule.py`: per-user interactive Task Scheduler task; one-minute local gate, logon recovery and missed-slot coalescing.
- `notifications.py`: independent Windows/PushPlus adapters, safe links and text filtering.
- `ai.py`: optional consent-gated, one bounded request, untrusted JSON rendered as suggestions only.
- `maintenance.py`: private local backups, recovery backup, schema/integrity checks, credential-free diagnostics.

Task Scheduler uses a stable hashed name derived from the current-user data directory. It runs with
InteractiveToken/LeastPrivilege and IgnoreNew. No elevated service, password, remote backend or resident
GUI is required. The gate checks configured IANA-local slots and converts to UTC; DST gaps move forward,
folds run once. Daily catchup covers 36 hours and coalesces missed slots. Current-week report catchup occurs once.
Recovery retries partial/network sync every 15 minutes. Ordinary checks do not call AI unless enabled;
AI content changes are hashed to cap automatic requests to one per new announcement snapshot.

Cached failed scopes remain visible with timestamps and an incomplete banner. Reminders only use data read
in the current run. A linked quiz whose assignment scope failed is excluded from reminders. Assignment
ID links, never titles, deduplicate quizzes; standalone quiz submission state is Unknown.
Late-submission permission is Unknown unless a future documented API field establishes it; lock time alone
is insufficient evidence. Excused assignments stop reminders and are displayed as excused.

The ledger records `uncertain` before a notification request, then `sent` after channel acceptance.
After a crash or ambiguous failure, it suppresses repeats for that delivery key. This favors avoiding duplicate
messages at the cost of possible missed messages; exactly-once delivery cannot be guaranteed by these channels.
New scheduled slots intentionally create new strong/overdue reminder keys.

Credentials are protected at rest with current-user DPAPI. Cached coursework and settings are ordinary
current-user files and are not separately encrypted. Other software running as the same Windows user can
access them and can ask DPAPI to decrypt that user's secrets. Backups omit credentials and contain private text.

rc2: notifications use in-process PyWinRT; Task Scheduler uses in-process pywin32 COM. Per-thread apartment/interface lifetimes and HRESULT sanitization are in windows_native.py. No runtime interpreter or schtasks command is requested by application code. See AVAST_REVIEW_CN.md for observed native CMD events and release blockers.
