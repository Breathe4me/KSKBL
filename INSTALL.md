# Installation and data

Requirements: Windows 11 x64, .NET Framework 4.8 and WebView2 Runtime 120+. Python is bundled. No automatic runtime download, security-policy change or administrator requirement is introduced. An unsupported/missing WebView2 Runtime must be resolved using an official installer by the user; the app does not silently fall back to an old renderer.

This is currently a LOCAL RC. Do not distribute until licensing/security/manual gates pass and the maintainer approves publication. Installer GUI has not been executed in this preparation.

Setup: run the complete Setup candidate manually in the existing Smoke VM. The per-user program default is `%LOCALAPPDATA%\Programs\CanvasDeadlineAgent-v1.2`; v1.1 and data folders must remain separate. Creating a desktop shortcut is optional. Launching at the installer finish screen is a user choice.

Portable: extract the full ZIP into its own program folder. Keep `_internal`, notices and all files together; do not run an EXE copied on its own or directly from a ZIP. Double-click CanvasDeadlineAgent.exe: production-default, empty v1.2 profile. No --live or --mock flag is required. Do not reuse an old QA program folder.

First use: Settings → Canvas → base HTTPS URL and personal token → save → identity test → sync. No token means unconfigured/empty, not demo tasks. There is no separate first-run wizard. AI/background monitoring start disabled; notifications, paid AI and scheduler changes require user action.

Data: `%LOCALAPPDATA%\CanvasDeadlineAgent-v1.2` by default; `--data-dir` can explicitly select a different profile. A QA_ONLY profile is rejected by normal production launch. No automatic import of v1.1 data/keys occurs. Explicit backup/import uses existing validation/backup/rollback and excludes keys.

Update: close app and background work, review a credential-free backup, then install the new v1.2 candidate over the same v1.2 program directory. Data remains outside the program folder. In-place upgrade and downgrade/migration behavior still require manual acceptance; don't claim them tested from a compile log.

Uninstall: the uninstaller first removes only this v1.2 data root's scheduled tasks; failure stops uninstall. It retains the profile, cached data and DPAPI credentials. Custom-profile tasks require explicit cleanup of that profile before removing program files. User data removal is a separate explicit owner decision, never automatic. No v1.1 task or folder may be removed.

Build identity, diagnostic paths, hashes and manual acceptance details accompany the local candidate. Report failures without tokens or private data; keep protection enabled. Do not bypass SmartScreen or use a whitelist as a test shortcut.


### Microsoft runtime prerequisite for the internal native-remediation candidate
Install the supported **Microsoft x64 Visual C++ v14 Runtime 14.44.35211.0 or later** directly from [Microsoft](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist). Its installation may require administrator consent; the Agent installer remains per-user. This candidate does not bundle these Microsoft DLLs and does not download or install the prerequisite automatically. Setup checks all four required DLL versions before copying application files. For Portable, run `powershell -NoProfile -File .\Check-Prerequisites.ps1` first, then launch the EXE from its complete directory. This prerequisite does not install Python. WebView2 Runtime remains separately required. Missing prerequisites are not a reason to disable Defender or bypass TLS verification.

The PowerShell check is optional and may be blocked by your Windows script execution policy. Do not change or bypass that policy. Use Setup's built-in prerequisite check, or install the supported runtime directly from Microsoft before using Portable.

The same Microsoft runtime prerequisite also supplies mfc140u.dll for the retained pywin32 Pythonwin component. This library is not bundled or deleted to hide a dependency; Setup checks it too.
