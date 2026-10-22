# Known limitations and release gates

- Application license/ownership is unconfirmed: source-available policy is only a draft and needs final/legal review.
- No separate first-run wizard exists. Empty-state/Settings setup is implemented; the requested wizard must not be marked PASS.
- New production-default installer/upgrade/uninstall and actual native GUI behavior require manual acceptance.
- Real Canvas permissions, PushPlus receipt, Windows scheduler/notification delivery and paid AI endpoints have not been certified by local mock/TLS tests.
- Prior SEC-01/SEC-03 Avast evidence is unresolved; no claim of false positive or universal malware safety.
- Signing and current malware scan evidence are reported separately; unsigned builds must not be advertised as verified-publisher software.
- A Python dependency advisory query is not a complete vulnerability or supply-chain audit of native DLLs, WebView2 or the vendor-modified Python runtime. Unknown native provenance/version is BLOCKED.
- Legacy unscoped AI keys are preserved but require deliberate rebinding to the correct provider/HTTPS endpoint.
- Optional encrypted-PDF/image features may need dependencies not included in the build; unsupported cases must report failure.
- Partial/disabled Quiz APIs limit discovery. Local completion is not Canvas submission; UNKNOWN is not verified success. Official course records remain authoritative.
- No Git history is available in this work copy. The clean archive contains the audited current tree only; any repository history imported later needs separate scanning.
- Private vulnerability reporting/contact and final redistribution approval still need maintainer confirmation.
