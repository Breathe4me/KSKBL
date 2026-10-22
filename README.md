# Canvas Deadline Agent

**🌐 Language / 语言： [🇬🇧 English](README.md) | [🇨🇳 简体中文](README.zh-CN.md)**

---

Tired of constantly checking Canvas because you're worried about missing a deadline?

# Canvas Deadline Agent

**Tired of constantly checking Canvas because you're worried about missing a deadline?**

Canvas Deadline Agent is a Windows desktop application designed to help students manage coursework across multiple Canvas LMS courses.

It brings your synced assignments together in one place, shows how much time you have left before each deadline, and provides local task management and optional WeChat reminders.

It's particularly useful for students taking multiple courses who don't want to open every Canvas course page just to check what's due.

**Current Version:** v1.2.0-beta.1 · Windows Beta

> This is an independently developed third-party application. It is not an official product of Canvas, Instructure, or any university. It does not automatically submit assignments and cannot guarantee access to every quiz.

## 📥 Download

**Windows Beta v1.2.0-beta.1**

[📥 Download KSKBL for Windows](https://github.com/Breathe4me/KSKBL/releases/tag/v1.2.0-beta.1)

Open the **Assets** section and download the file ending in `-Setup.exe`.

The portable ZIP version is also available for users who prefer not to use an installer.

> Beta software. Some Canvas quizzes may not be accessible through the API.

## Features

| Where to find it | What it does |
|---|---|
| **Today's Overview** | See upcoming assignments and deadline countdowns in one place. |
| **All Assignments** | View synced assignments from different courses together. |
| **Submission History** | Distinguish between Canvas-reported submissions and tasks marked as completed locally. |
| **WeChat Reminders** | Configure PushPlus to receive deadline reminders through WeChat. |
| **Settings** | Manage your Canvas connection, synchronization, and other preferences. |

In **All Assignments**, find an assignment and click **View Details** to see available instructions and related information.

Use the **···** menu next to an assignment to ignore it, mark it as completed locally, or restore its previous status.

**Important:** Marking an assignment as completed in this application does not submit it to Canvas.

### Deadline Reminders

Canvas Deadline Agent also supports configurable deadline checks and reminders.

Depending on your settings, it can help you identify approaching deadlines and provides an emergency mode for assignments that are within 60 minutes of their due time.

Reminder delivery depends on your computer's running state, network connection, configured schedule, and notification service.

## Installation

1. Open the [Releases page](https://github.com/Breathe4me/KSKBL/releases).
2. Select the latest Beta release.
3. Expand **Assets**.
4. Download the installer ending in `-Setup.exe`.
5. Open your Windows **Downloads** folder.
6. Double-click the installer and follow the installation instructions.
7. Open the Windows Start menu and search for **Canvas Deadline Agent**.

The application is primarily tested on **Windows 11 x64**.

### System Requirements

- Windows 11 x64 (primary tested environment)
- Microsoft Edge WebView2 Runtime
- Microsoft Visual C++ x64 Runtime version 14.44.35211.0 or later, including MFC
- An internet connection for Canvas synchronization and online notifications

The required Microsoft components can be obtained from Microsoft's official website.

**You do not need to install Python separately.**

This Beta is unsigned. Windows may display a security or publisher warning. Do not disable your antivirus or operating system protections to run the application.

## Connecting Canvas

Canvas is the learning management system used by many universities to manage courses, assignments, quizzes, and announcements.

To connect your account:

1. Open **Canvas Deadline Agent**.
2. Click **Settings** in the left sidebar.
3. Locate the Canvas connection settings.
4. Complete the connection using an authorization method permitted by your institution.
5. Click **Verify Account** to check your connection.
6. Click **Sync Now** to retrieve available course information.
7. Return to **All Assignments** to view the synced tasks.

### About Canvas API Tokens

Some current test builds support manually entering Canvas API credentials. However, this does not mean manual token-based integration is permitted for every institution or for general third-party distribution.

The authorization method must comply with Canvas and your institution's requirements.

Never share your Canvas password or API token with other people. If your institution does not permit the available connection method, wait for a supported authorization option.

### What happens if some assignments are missing?

Some courses restrict access to particular Canvas API endpoints, especially quiz listings.

You might see a message indicating that part of the synchronized information is unavailable.

**This does not mean you have no assignments or quizzes.**

For important deadlines, always double-check your university's official Canvas website.

## Setting Up WeChat Reminders with PushPlus

Canvas Deadline Agent supports optional WeChat notifications through [PushPlus](https://www.pushplus.plus/).

PushPlus is a third-party notification service. You can use the application without enabling it.

### Step 1: Get your PushPlus token

1. Open the [PushPlus website](https://www.pushplus.plus/).
2. Sign in to your PushPlus account.
3. Open the [one-to-one message page](https://www.pushplus.plus/push1.html).
4. Find the **User Token** section.
5. Click the copy button to copy your token.

### Step 2: Connect PushPlus to the app

1. Open **Canvas Deadline Agent**.
2. Click **WeChat Reminders** in the left sidebar.
3. Locate the PushPlus token field.
4. Paste your copied token.
5. Save your settings and enable reminders using the controls shown in the application.
6. Make sure your PushPlus account is linked to the correct WeChat notification channel.
7. Send a test notification, if the test option is available, and confirm that it arrives.

PushPlus may require additional account verification before allowing messages to be delivered.

### Important reminder notes

Notifications are not guaranteed if your computer is shut down, offline, or unable to run the scheduled checks. Delivery also depends on PushPlus availability and your notification settings.

## Optional AI Features

Canvas Deadline Agent provides optional AI-assisted workflows.

Users can configure supported AI services with their own API keys (BYOK — Bring Your Own Key).

Depending on the available features and permissions, AI assistance can help with:

- Summarizing course announcements.
- Organizing assignment instructions.
- Extracting and reviewing available rubric information.
- Preparing prompts and reference materials for further work.
- Reviewing user-authorized local files.

AI integration is optional and is not required for normal assignment tracking.

Some third-party AI providers may charge for API usage.

**The application does not automatically submit AI-generated work to Canvas.** Always review AI-generated information and follow your institution's academic integrity requirements.

## Things to Keep in Mind

- Some universities restrict access to Canvas Quiz APIs, so certain quizzes may not appear.
- A message such as **Partial Data Unavailable** does not mean there are no outstanding tasks.
- **Completed Locally** is a personal task marker, not proof of submission.
- Background reminders are not guaranteed to work while your computer is turned off.
- AI output may be incomplete or inaccurate and should be reviewed.
- For critical deadlines and submissions, your university's official Canvas records remain the source of truth.

## Privacy & Security

Canvas Deadline Agent runs locally on your Windows computer and uses Windows security mechanisms to protect stored credentials.

When you enable optional integrations such as PushPlus or third-party AI providers, relevant data may be transmitted to those external services.

Do not share Canvas tokens, PushPlus tokens, AI API keys, or personal information in public screenshots, GitHub Issues, or chat messages.

## Project Status

Canvas Deadline Agent is currently in **Beta**.

Features may change, and some functions may not work consistently across all Canvas institutions.

If you encounter a bug or have a feature suggestion, please open an issue in this repository:

[Report an issue](https://github.com/Breathe4me/KSKBL/issues)

Please do not include passwords, API keys, access tokens, or other sensitive information in public issues.

## Disclaimer

Canvas Deadline Agent is an independently developed, unofficial third-party application.

It is not affiliated with, endorsed by, or operated by Instructure, Canvas LMS, or any university.

The software is intended to assist with coursework organization, not to replace official university systems or the user's responsibility to check deadlines and submit work.

© 2026 Breathe4me. Rights in original project content are reserved. Third-party components remain subject to their respective licenses. The project's intended personal educational and commercial-use licensing terms are under finalization.
