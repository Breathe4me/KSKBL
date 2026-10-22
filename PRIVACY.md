# Privacy Notice

Last reviewed: **23 October 2026**  
Applies to: **Canvas Deadline Agent v1.2**  
Public project attribution: **Breathe4me**, an individual developer.

Canvas Deadline Agent is a local Windows application with optional connections
to Canvas, PushPlus and an AI provider you select. This notice describes the
current application; those services, GitHub, Microsoft Windows and WebView2 have
their own terms and privacy practices.

**Publication detail still pending:** the responsible developer's final legal
identity and a verified private privacy contact must be confirmed. Breathe4me
is public attribution, not a substitute for legally required identity/contact
information. This notice is not a claim of completed legal compliance review.

## 1. Information stored on your computer

The application stores settings, cached course/assignment/quiz/announcement and
submission-status information, account-scope identifiers, local completion and
ignore choices, notes, reminder/delivery history and diagnostic records. Selected
or downloaded materials and user-created exports may also contain course or
personal information.

The normal release profile is:

```text
%LOCALAPPDATA%\CanvasDeadlineAgent-v1.2
```

QA profiles use a separate directory. The release does not automatically import
v1.1 or QA data. A portable program directory is not an encrypted data container;
the normal profile is still local to the Windows user unless explicitly configured
otherwise. Local settings, cached databases, logs and exports are **not all
encrypted by the application**. Protect your Windows account and device.

## 2. Credentials

Saved Canvas tokens, PushPlus tokens and AI API keys are protected using
**Windows DPAPI for the current Windows user**, rather than stored in ordinary
configuration JSON. Saved secrets are not returned through the frontend's general
state API. AI credentials are scoped to their provider and HTTPS endpoint.

Credentials you enter pass through the input interface to the backend for the
requested operation or protected storage. They are necessarily sent to the
corresponding provider when authenticating an authorized request. DPAPI does not
protect against a compromised Windows account or malicious software running with
equivalent access, and does not encrypt every database field or exported file.

## 3. When information leaves your computer

| Destination | Information and trigger |
| --- | --- |
| Your configured Canvas instance | Authenticated, read-only API requests when you test the connection, synchronize, verify submission status or have explicitly enabled background monitoring. The instance receives your token and requested course/resource identifiers. |
| PushPlus | Your personal token and selected reminder/test-message content when you request a test or enable that notification channel for authorized reminders. API acceptance does not prove WeChat delivery. |
| Your selected AI provider | Your API key and the course text, announcement, assignment requirements, rubric or explicitly authorized file content included in a request. AI is disabled by default and requires configuration and consent. Enabled AI workflows can run within that authorization; requests may incur provider charges. |
| A website you choose to open | Opening an official Canvas page or another external link uses your browser and that site's policies. Browser sign-in and cookies are managed outside this application. |

Only use accounts, data and local files you are entitled to access. Local-file
inspection requires explicit selection/authorization; authorizing local inspection
alone does not authorize cloud upload. Check the destination and authorized
content before an AI request. The application does not automatically submit
coursework to Canvas. Local completion is a local tracking choice, not a submission.

The developer does not operate a central account or course-data collection server
for these features. There is no implemented application analytics/advertising
telemetry or automatic diagnostic-report upload. The UI uses bundled resources,
without a CDN or local listening HTTP server. This does not promise the absence
of Windows/WebView2 platform traffic or provider-side logging. Providers may
process or retain requests in other countries under their own policies.

## 4. Your choices and defaults

- A fresh release profile contains no Canvas token or seeded student assignments.
- AI and background monitoring start disabled. Core local tracking works without AI.
- PushPlus requires your own configuration and an explicit test or enabled channel;
  the application does not send a first-run test automatically.
- Background reminders require explicit enablement. Some reminder-rule defaults
  are preconfigured; that is distinct from starting background monitoring.
- You can change settings, disable monitoring/channels/AI and remove saved
  credentials using the available controls. Disable related activity before removing
  a profile. Revoke a token/key at its provider if you need to invalidate it.

Revoking a local authorization prevents future use within that authorization; it
does not undo completed requests or delete copies already retained by a provider.

## 5. Logs, backups and sharing

Diagnostics include operational state, error classifications and safe stack/resource
metadata. Paths, times, resource hashes and identifiers can still reveal information
about your device or activity. Credential values and authentication headers must
not be included in reports; inspect and redact files before sharing them.

The application's backup operation excludes its separately stored credential files,
but includes configuration and the cached SQLite database. Backups can therefore
contain sensitive course/account information and local notes. A manually copied
whole profile may also include encrypted credential files. Exports and backups are
your responsibility to protect and are not automatically made anonymous.

Do not put tokens, keys, databases, student records or unredacted logs in GitHub
issues, pull requests or public repositories. If you voluntarily send a report,
the recipient and hosting platform will receive the contents you choose to share.

## 6. Retention, uninstall and deletion

The application does not promise a fixed automatic deletion period for all cached
data or diagnostics. Updates retain the v1.2 profile. Uninstall is designed to
remove the application's own scheduled tasks while retaining settings, cached
data and encrypted credentials; uninstall is **not** complete data erasure.

To remove local data, close the application and stop its background monitoring,
review any needed backup, then remove only your explicitly identified v1.2
profile. Separately review backups, exports and downloaded/selected files stored
elsewhere. Do not delete v1.1, QA, other-user or unrelated directories by mistake.
Revoke provider tokens separately where appropriate. Local deletion does not
remove Canvas records, previously delivered messages or provider-held AI data.

## 7. Contact and changes

The public maintainer identity is [Breathe4me](https://github.com/Breathe4me).
A verified private privacy/security contact has not yet been published. Do not
send sensitive information to an unverified address or use public issues for it.
[SECURITY.md](SECURITY.md) describes the current reporting arrangements; do not
assume GitHub Private Vulnerability Reporting is enabled unless the repository
actually offers it.

Future versions may change this notice to reflect actual data handling. Review
the notice shipped with the version you use. This document does not itself grant
an application license; see [LICENSE](LICENSE) and
[COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).
