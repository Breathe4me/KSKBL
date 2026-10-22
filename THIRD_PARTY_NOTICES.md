# Third-party notices — v1.2.0-beta.1 local RC

Dependencies retain their own rights and are not relicensed under the proposed application source-available policy. This inventory is not approval to publish.

| Component | Original terms and status |
|---|---|
| Python 3.12.14 / vendor runtime | PSF and historical licenses; Microsoft distributable-code terms in Python-LICENSE.txt |
| OpenSSL 3.5.8 | Original Apache-2.0 text in openssl-3.5.8-LICENSE.txt; exact binary binding and Apache-2.0 original included; complete build history is not a license condition |
| libffi-8.dll | official CPython cpython-bin-deps 3.4.4 x64 bytes and exact MIT original; fixed commit/SHA in NATIVE_DISTRIBUTION.json |
| SQLite 3.53.1 | Public domain; bundled through Python; original SQLite code is public domain; vendor origin and exact bytes recorded |
| requests / urllib3 / charset-normalizer / idna / certifi / tzdata | Original installed LICENSE/NOTICE files, including MPL-2.0 CA-bundle notice |
| PyWinRT five components 3.2.1 | Pinned complete upstream MIT texts and copyright, not metadata labels |
| pywin32 / typing_extensions / pypdf / defusedxml | Original installed license and notice files |
| pywebview 6.2.1 | BSD-3-Clause; installed text verified against exact official tag |
| pythonnet / clr_loader / cffi / pycparser / bottle | Original installed texts; cffi 2.1.1 says MIT No Attribution |
| proxy_tools 0.1.0 | Installed metadata says MIT; actual upstream BSD-style original retained verbatim with Armin Ronacher and Jonathan Tushman copyright |
| Microsoft.Web.WebView2 SDK 1.0.3856.49 | Exact official NuGet LICENSE.txt and NOTICE.txt; all five bundled SDK binaries hash-match archive |
| PyInstaller bootloader | GPL-2.0-or-later with bootloader exception; original COPYING.txt collected |
| Tcl/Tk legacy source | Version-pinned original terms retained; production RC excludes Tk runtime; not a claim of a bundled Tk dependency |
| Inno Setup compiler | Build tool, not shipped; its original local license is recorded separately |

Full collected texts are under packaged notices/licenses. Source originals and SHA-256 mappings are under docs/third-party/SOURCES.json, UI_SOURCES.json and NATIVE_SOURCES.json. The UI collector fails for missing/mismatched originals, notices or SDK binary mappings. proxy_tools upstream contains a BSD-style license despite the MIT metadata label; no generic MIT template replaces it. The WebView2 SDK NOTICE retains its embedded third-party acknowledgements.

The Python runtime companion codex-rejected-cas.pem is carried verbatim with its original SHA-256 as required by the build runtime, preserving its rejection policy. It is not a replacement public CA bundle. No commercial font files are bundled.

The identified native license obligations and any explicit changes must be satisfied. Complete build history alone is not a blanket blocker. Final application licensing, security clearance and maintainer authorization for public publication are separate.

## Release remediation additions (not a public clearance)
This installer is made using RemObjects Pascal Script, created by Carlo Kok and RemObjects Software: https://github.com/remobjects/pascalscript . The original fixed Inno 6.7.3 Pascal Script and Inno Setup license texts are included in notices/licenses/installer.
For certifi 2026.10.19, complete MPL-2.0 text and exact package Source Code Form are provided under notices/licenses/certifi and notices/licenses/sources/certifi-2026.10.19-source.tar.gz. The source archive is byte-bound to the installed Python/PEM files; its public source URL and SHA are in REDISTRIBUTION_SOURCES.json.
The full frozen closure's original notices are preserved by package RECORD-relative path, including any retained build-derived dependencies. PyInstaller tool modules are not covered by a blanket bootloader-exception assertion and are forbidden in the release runtime.
Windows 11 supplies API-set and UCRT system components; the release spec no longer redistributes unrelated copies found in the builder PATH. Unknown or changed native inputs still fail the byte/notice gate; Microsoft runtime DLLs now use a checked user-installed prerequisite.

## Native obligations for this internal candidate
Applicable CPython incorporated-code originals (asyncio/uvloop, libmpdec, Expat, HACL*, SipHash/dtoa/cfuhash), Unicode permission/copyright, zlib, liblzma and libffi are under notices/licenses/native. PYTHON_BUILD_CHANGES.md truthfully records packaging and dependency substitutions; a complete supplier build-history attestation is not imposed as an additional condition of permissive licenses.
The _lzma extension is from fixed CPython 3.12.14 python-build-standalone 20260901 with liblzma 5.8.3 (0BSD). The previous unknown-version extension is not included. libffi-8.dll is the unmodified CPython official 3.4.4 artifact at commit 94cb9a1c7feb608adf2b9f8fe2dbd6925ffbf90d.
Microsoft VCRUNTIME140.dll, VCRUNTIME140_1.dll and MSVCP140.dll are NOT bundled. A Microsoft x64 VC v14 Runtime, 14.44.35211.0 or later, is a user-installed prerequisite from Microsoft. The installer checks it before changing application files. Portable users can run Check-Prerequisites.ps1. No runtime is silently downloaded or installed. The Windows binary Python license's applicable Microsoft embedded-code conditions are preserved; third-party rights are not restricted by the application's proposed license.
These obligations and byte bindings are checked by NATIVE_DISTRIBUTION.json. This is not malware clearance, final application-license approval or public-publication authorization.

The same Microsoft runtime prerequisite also supplies mfc140u.dll for the retained pywin32 Pythonwin component. This library is not bundled or deleted to hide a dependency; Setup checks it too.
