# Security policy — release candidate

v1.2.0-beta.1 is a local candidate, not a security certification. Historical Avast SEC-01/SEC-03 attribution, a current malware result, signing decisions and manual real-service/installer acceptance remain release gates. Missing evidence is BLOCKED, not PASS.

HTTPS certificate and hostname verification remain enabled. The packaged Python SSL companion rejection policy `codex-rejected-cas.pem` is preserved verbatim and hash checked. No verify=False, whitelist or antivirus-disabling workaround is supported.

The Python/JS bridge exposes an allowlisted validated command endpoint, never arbitrary SQL, shell execution, saved-secret reads or generic file access. Canvas text is untrusted display data. Local completed/ignored states are distinct from remote submissions and are rechecked before notification delivery. AI/local-file access and notification scheduling require explicit user configuration/consent.

For a suspected vulnerability, do not create a public issue containing tokens, private coursework, databases or exploit details. The intended maintainer namespace is Breathe4me/CanvasDeadlineAgent; private security reporting/contact must be configured and confirmed before public publication. No private-reporting channel is claimed to exist yet. A confirmed security contact is a publication blocker.

Do not bypass SmartScreen/antivirus or add exclusions. Preserve detection name, timestamp, signed/hash identity and safe event evidence. Do not upload binaries or private logs to third-party services without separate approval.

## Confirmed local preparation scope
The owner selected no purchase of code-signing certificates and did not approve unsigned public distribution. Public release remains BLOCKED. Private reporting is planned, not enabled. See docs/SECURITY_CONTACT_TEMPLATE.md for placeholders and enablement verification; do not claim a working channel until the owner confirms it.
