# v1.2 functional integration map

Baseline: `reports/functional-integration-20261022-150117/SOURCE_BASELINE.zip` (134 source files, archive contents verified). No Git repository exists in this work copy; no Git initialization/reset performed. The user's current instruction records visual approval; earlier reports predate that approval. No new native GUI acceptance is inferred.

| UI function | Python service / bridge | Starting status | Required integration |
|---|---|---|---|
| Dashboard, cached tasks, sync | Store, CanvasAPI, engine.run / get_state, sync | Partial | Coverage/freshness, safe sync-only flow, progress/error feedback |
| Assignment list | Store.cached, Tracking.rows / get_state | Partial | Search, course/status filters, stable due sorting |
| Ignore/complete/restore | Tracking.set / set_tracking | Connected | Local operation history, per-channel final filter, restart/account tests |
| Description, rubric, attachments | assignment_context.fetch_context / assignment_context | Partial | Render all existing context fields safely, explicit attachment/official links |
| Read-only submission verification | submission.verify / verify_submission | Connected | Latest result DTO, cache updates for UNKNOWN/pending/unsubmitted, separate local history |
| PushPlus binding/testing | Secrets(DPAPI), Dispatcher, PushPlusChannel | Partial | Safe status/receipts/budgets, explicit user receipt confirmation, no secret return |
| Daily/exam/Guardian scheduler | schedule, guardian, engine CLI | Partial | Read-only health, interval setting, optional 24h/15m stages, QA CLI routing |
| Settings and maintenance | config, maintenance, migration / save_settings, backup_data, import_backup | Connected | Complete low-frequency fields, data/log/version information |
| AI announcement extraction | AIClient, announcement_intelligence | Connected | Malformed-envelope handling and explicit error reasons |
| Standard/workspace prompts | prompt_builder, web_copilot | Connected | Explicit one-click native copy, no frontend clipboard secret API |
| Authorized files/cloud/export | LocalAccess, reviewer, web_copilot | Connected | Preserve grants/previews/tickets; revoke on window close |
| Emergency preparation | guardian.tracked_tasks, prompt/context services | Partial | A read-only eligible-task checklist; no automatic submission/AI |
| Real versus QA | app.main, Bridge, web_qa | Partial | QA must not read DPAPI; full CLI executable must support independent scheduled/guardian entry |
| Offline startup | ordered_initial_navigation, StartupDiagnostics | Connected | Preserve lifecycle ordering and all seven Ready stages |

Mock locations: `scripts/qa_mock_adapter.js` is only embedded by the offline preview exporter. `scripts/ui_review_entry.py`, `scripts/bridge_test_host.py`, and explicit `--mock/--qa` paths use synthetic mode. Production `app.main -> web_shell.launch -> Bridge(qa=False)` never seeds demo tasks or embeds Browser Mock Adapter.

Execution boundary: code-only tests use fake network, credentials, notifications, clipboard/dialog and scheduler adapters. Actual Canvas credentials, WeChat delivery, Task Scheduler registration/trigger/cleanup, WebView2/DPI/visual checks require later user-authorized Smoke VM tests. No source changes are made outside this work copy; existing candidate directories and design resources are preserved.

## Integration result

All rows above are now wired to the named services in production mode. The application frontend never embeds the browser mock adapter. Remaining differences are explicit QA denials and manual/native acceptance, not unlabelled placeholder actions.

| Area | Implemented connection / verification | Remaining actual-environment check |
|---|---|---|
| A/B | Existing CanvasAPI GET -> existing engine cache path -> Store/schema 2 -> get_state -> real frontend; search/course/state/due sorting; limited/stale/error feedback | School account scope and permissions |
| C | Existing Tracking service, transactional local history in the same DB, namespaced choices, per-channel final checks, weekly tracking revision gates including inflight AI supplements | Actual notification timing/delivery |
| D | Read-only verification and safe context/rubric/attachment metadata; current UNKNOWN invalidates stale success display; remote and local histories separate | Guest network/service edge cases |
| E | Existing DPAPI/PushPlus/Dispatcher; configured/accepted/user-confirmed receipt distinct, retry/budget state | Actual DPAPI protection and WeChat receipt |
| F | Existing scheduler/Guardian CLI, stable root-derived task identity, explicit enable/disable, interval and optional 24h/follow-up controls | Register, trigger with GUI closed, inspect and remove own tasks in guest |
| G | All non-secret DEFAULTS have UI controls; appearance preserved, atomic config persistence, native status query, maintenance paths/version/privacy | Native dialogs and task-state query |
| H | Existing AI cache/budget/parser/workspace workflow, explicit requests, one-click backend prompt copy, local emergency checklist; invalid envelopes report explicit reasons | Approved guest model endpoint, clipboard/dialog behavior |
| I | Same data root across GUI/monitor/verification, additive schema-2 history table with pre-change backup, existing import rollback, QA/live profile rejection | User-selected migration/restore only after separate authorization |

Visual resources `frontend/index.html`, `prototype.css`, and `app.css` stay unchanged. UI JavaScript adds necessary controls and data inside existing components, without replacing fonts, colours, sidebar or card styling. `startup.js` only adds bounded diagnostic codes and operation tracing; the ordered native mapping module remains preserved.

2026-10-22 full audit: QA credential rejection is intentional and now explicitly labelled. Actual production Bridge + temporary Windows DPAPI tests cover Canvas/PushPlus/AI add, replace, delete, restart, provider/endpoint isolation and error recovery. AI secrets previously shared an unscoped file; they now bind to provider/endpoint and the request configuration snapshot. Legacy unscoped keys are preserved and require explicit re-entry. The actual Windows guest DPAPI/UI interaction and real account/notification acceptance remain manual. Busy 6/6 is accepted as user-reported Smoke VM evidence; this audit does not replace it with a headless claim.
