"""Read-only PE dependency closure. Never loads a GUI or mutates system runtime state."""

import argparse
import json
from pathlib import Path

import pefile
from build_manifest import file_hash


def verify(candidate):
    payload = Path(candidate) / "payload/CanvasDeadlineAgent"
    binaries = [p for p in payload.rglob("*") if p.suffix.lower() in {".exe", ".pyd", ".dll"}]
    names = {p.name.lower(): p for p in binaries}
    prerequisites = {"vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "mfc140u.dll"}
    # Microsoft system components on the supported Windows target, not copied from the host.
    system = {
        "kernel32.dll",
        "ntdsapi.dll",
        "user32.dll",
        "advapi32.dll",
        "shell32.dll",
        "shlwapi.dll",
        "ole32.dll",
        "oleaut32.dll",
        "ws2_32.dll",
        "crypt32.dll",
        "bcrypt.dll",
        "bcryptprimitives.dll",
        "secur32.dll",
        "rpcrt4.dll",
        "version.dll",
        "ntdll.dll",
        "gdi32.dll",
        "gdi32full.dll",
        "comdlg32.dll",
        "comctl32.dll",
        "winmm.dll",
        "winspool.drv",
        "imm32.dll",
        "uxtheme.dll",
        "dwmapi.dll",
        "propsys.dll",
        "iphlpapi.dll",
        "netapi32.dll",
        "wtsapi32.dll",
        "userenv.dll",
        "msvcrt.dll",
        "mscoree.dll",
        "oleacc.dll",
        "dnsapi.dll",
        "psapi.dll",
        "ucrtbase.dll",
        "normaliz.dll",
        "wintrust.dll",
        "winhttp.dll",
        "urlmon.dll",
        "wininet.dll",
        "shcore.dll",
        "dwrite.dll",
        "d2d1.dll",
        "d3d11.dll",
        "dxgi.dll",
        "wldap32.dll",
        "dbghelp.dll",
        "powrprof.dll",
    }
    missing, rows = [], []
    for path in binaries:
        pe = pefile.PE(str(path))
        imported = []
        for table in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for entry in getattr(pe, table, []):
                name = entry.dll.decode("ascii").lower()
                if name in names:
                    classification = "payload"
                elif name in prerequisites:
                    classification = "Microsoft_user_installed_prerequisite"
                elif name in system or name.startswith(("api-ms-win-", "ext-ms-win-")):
                    classification = "Windows_system"
                else:
                    classification = "unresolved"
                    missing.append({"file": str(path.relative_to(payload)), "dependency": name})
                imported.append({"name": name, "classification": classification})
        rows.append(
            {
                "file": path.relative_to(payload).as_posix(),
                "sha256": file_hash(path),
                "machine": hex(pe.FILE_HEADER.Machine),
                "imports": imported,
            }
        )
    forbidden = sorted(names.keys() & prerequisites)
    result = {
        "status": "passed" if not missing and not forbidden else "failed",
        "files": rows,
        "missing_dependencies": missing,
        "accidentally_bundled_Microsoft_runtime": forbidden,
        "exe_sha256": file_hash(payload / "CanvasDeadlineAgent.exe"),
        "scope": "PE imports only; real loading checked separately",
    }
    (Path(candidate) / "evidence/NATIVE_DEPENDENCY_CHECK.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    if result["status"] != "passed":
        raise ValueError("Native dependency closure failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=Path)
    report = verify(parser.parse_args().candidate)
    print(json.dumps({"status": report["status"], "files": len(report["files"])}))
