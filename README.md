# Canvas Deadline Agent

Windows student deadline manager with a local Python/SQLite backend and an offline WebView2 interface. Warm Sage and Soft Pink share the same layout; English and Chinese are supported.

**v1.2.0-beta.1 is a local release candidate. Public publication is NOT approved.** Installation/upgrade/uninstall, real Canvas permissions, notification delivery and remaining security checks require manual acceptance. See [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md) and [RELEASE_NOTES](RELEASE_NOTES.md).

This is an independent project. It is not affiliated with, supported, endorsed or certified by Instructure, Canvas, the University of Sydney or any university.

## Features

- Read-only Canvas course, assignment, quiz, announcement and submission-status synchronization.
- Local ignore, complete and restore choices persist independently of Canvas submission records.
- Optional Windows reminders, independent Task Scheduler monitoring and personal PushPlus reminders.
- Optional BYOK AI summaries and preparation tools; core tracking works with AI disabled.
- DPAPI-protected credentials; explicit authorization for selected local files and paid AI operations.

## Requirements and first setup

Windows 11 x64, .NET Framework 4.8 and Microsoft Edge WebView2 Runtime 120+ are required. Python is bundled. WebView2 is not downloaded or installed automatically. See [INSTALL](INSTALL.md).

Start the full installed/portable application. The release defaults to a real, empty v1.2 profile, not Synthetic QA. Open Settings → Canvas, enter the Canvas base URL and your own personal student API token, save securely, test the identity, then synchronize. Saved secrets are never returned to the frontend. No token means an empty/unconfigured state, not demonstration assignments.

AI and background monitoring start disabled. Enable reminders deliberately. PushPlus requires a personal token and third-party WeChat setup. Test notifications and paid AI requests require an explicit user action. There is no automatic assignment submission.

There is currently no separate multi-step first-run wizard; the setup path is the existing empty state and Settings page. That requested wizard remains a release acceptance gap rather than an invented completed feature.

## Accuracy and service limits

Canvas coverage depends on your student API permissions. Some courses disable Quiz listing; the application reports incomplete coverage rather than pretending there are no assignments. No tool guarantees discovery of every deadline. Keep checking the official course pages.

**Local complete does not mean Canvas submitted.** Canvas's official records remain authoritative; UNKNOWN is not a success or failure. AI is BYOK and may incur provider fees; extracted dates are not official deadlines. PushPlus API acceptance is not proof of delivery. Windows scheduling and actual notification delivery need manual verification on the user's computer.

## Privacy, source and licensing

See [PRIVACY](PRIVACY.md), [SECURITY](SECURITY.md) and [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md). The proposed application policy is free personal, noncommercial student study; commercial, institutional and enterprise use would require separate permission. **This source-available direction is not an OSI open-source license.** [LICENSE](LICENSE) is explicitly a draft/no-grant notice pending rights-holder confirmation and legal review; do not infer MIT/Apache rights for the application. Dependencies retain their own original terms.

Prepared namespace: `Breathe4me/CanvasDeadlineAgent` (intended repository, not created or published by this preparation). Do not assume a public download or release exists. No credentials, databases, local logs or build environments belong in a repository.

## Development

See [BUILD_AND_TEST](BUILD_AND_TEST.md) and [CONTRIBUTING](CONTRIBUTING.md). Preserve Code-Only mode for automation. Native installer/UI/scheduler tests belong in the existing Smoke VM and are performed manually. No upload, release creation or Git push is part of the build.


### Microsoft runtime prerequisite for the internal native-remediation candidate
Install the supported **Microsoft x64 Visual C++ v14 Runtime 14.44.35211.0 or later** directly from [Microsoft](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist). Its installation may require administrator consent; the Agent installer remains per-user. This candidate does not bundle these Microsoft DLLs and does not download or install the prerequisite automatically. Setup checks all four required DLL versions before copying application files. For Portable, run `powershell -NoProfile -File .\Check-Prerequisites.ps1` first, then launch the EXE from its complete directory. This prerequisite does not install Python. WebView2 Runtime remains separately required. Missing prerequisites are not a reason to disable Defender or bypass TLS verification.

The PowerShell check is optional. If script execution policy blocks it, keep the policy unchanged and use Setup's built-in check or Microsoft's runtime installer directly.

The same Microsoft runtime prerequisite also supplies mfc140u.dll for the retained pywin32 Pythonwin component. This library is not bundled or deleted to hide a dependency; Setup checks it too.
