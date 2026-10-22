# Contributing

Repository publication and contribution licensing are not finalized. The proposed application license is source-available, not MIT/Apache; confirm contributor rights and terms before accepting outside changes. No CLA or copyright assignment is implied.

Preserve the approved UI and existing P0 navigation, bootstrap, message, Busy, SQLite and TLS fixes. Do not remove tests or weaken assertions. Use fake external services, temporary SQLite profiles and fabricated credentials. Never use real Canvas/PushPlus/paid AI in automation.

Run the guarded Code-Only commands in BUILD_AND_TEST.md. Do not run tests/test_gui.py or tests/test_v12_desktop.py on a primary desktop. Native GUI/installer/Task Scheduler acceptance is manual in CanvasDeadlineAgent-Smoke with authorization. Do not disable protection, register host tasks, control desktop/VM, publish artifacts or push Git as part of testing.

Keep `.deps`, `.ui-deps`, virtualenvs, all profiles/databases/DPAPI blobs, reports, build outputs and release-prep out of Git. Public source archives are generated from an explicit file list and scanned; `.gitignore` alone is not evidence that existing history is clean.
