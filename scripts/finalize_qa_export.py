"""Static QA payload checks, available license collection, manifests and ISO staging. No execution."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from build_manifest import source_snapshot
from check_ui_licenses import inventory
from collect_licenses import PACKAGES, PYWINRT_COMPONENTS, checked_sources
from PyInstaller.archive.readers import CArchiveReader
from ssl_resources import ssl_resources

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "qa-export"
PAYLOAD = EXPORT / "portable/CanvasDeadlineAgent-UI-QA"


def sha(file):
    value = hashlib.sha256()
    with Path(file).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write(file, value):
    Path(file).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def finalize(export_directory=None, full_app=False):
    global EXPORT, PAYLOAD
    if export_directory:
        EXPORT = Path(export_directory).resolve()
        if not EXPORT.is_relative_to((ROOT / "qa-export").resolve()):
            raise ValueError("QA export must remain inside the isolated qa-export directory")
        PAYLOAD = EXPORT / "portable/CanvasDeadlineAgent-UI-QA"
    if (EXPORT / "iso-content").exists() or (PAYLOAD / "PAYLOAD_SHA256.json").exists():
        raise FileExistsError("Refusing to replace an already finalized QA payload")
    program = PAYLOAD / "CanvasDeadlineAgent-UI-QA.exe"
    if full_app:
        proof = json.loads((EXPORT / "FROZEN_BACKEND_CHECK.json").read_text(encoding="utf-8"))
        if (
            proof.get("status") != "passed"
            or proof.get("exe_sha256") != sha(program)
            or not proof.get("cases")
            or not all(case.get("passed") for case in proof["cases"])
        ):
            raise ValueError("Actual frozen backend bootstrap gate failed; do not finalize or create ISO")
        mutations = json.loads((EXPORT / "FROZEN_ASSIGNMENT_CHECK.json").read_text(encoding="utf-8"))
        if mutations.get("status") != "passed" or mutations.get("exe_sha256") != sha(program):
            raise ValueError("Actual frozen assignment write gate failed; do not finalize or create ISO")
        credential_proof = json.loads((EXPORT / "FROZEN_CREDENTIAL_CHECK.json").read_text(encoding="utf-8"))
        if credential_proof.get("status") != "passed" or credential_proof.get("exe_sha256") != sha(program):
            raise ValueError("Actual frozen DPAPI check failed; do not finalize or create ISO")
        tls_proof = json.loads((EXPORT / "FROZEN_TLS_CHECK.json").read_text(encoding="utf-8"))
        if tls_proof.get("status") != "passed" or tls_proof.get("exe_sha256") != sha(program):
            raise ValueError("Actual frozen local HTTPS check failed; do not finalize or create ISO")
    ssl_manifest = json.loads((PAYLOAD / "_internal/ssl-runtime-resources.json").read_text(encoding="utf-8"))
    if ssl_manifest != ssl_resources():
        raise ValueError("SSL resource build provenance mismatch")
    for resource in ssl_manifest["files"]:
        if sha(PAYLOAD / "_internal" / resource["destination"]) != resource["sha256"]:
            raise ValueError("SSL companion policy resource missing or changed")
    archive = CArchiveReader(str(program))  # parse bytes only; never starts the EXE
    pyz_name = next(name for name in archive.toc if name.endswith(".pyz"))
    modules = archive.open_embedded_archive(pyz_name).toc
    required_modules = [
        "canvas_agent.web_bridge",
        "canvas_agent.web_shell",
        "canvas_agent.web_qa",
        "canvas_agent.startup_diagnostics",
        "canvas_agent.webview_native",
        "canvas_agent.storage",
        "canvas_agent.engine",
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "pythonnet",
        "clr_loader",
        "cffi",
    ]
    if full_app:
        required_modules += [
            "canvas_agent.app",
            "canvas_agent.credential_check",
            "canvas_agent.tls_check",
            "canvas_agent.tls_diagnostics",
            "canvas_agent.schedule",
            "canvas_agent.guardian",
            "canvas_agent.backend_check",
            "ui_review_entry",
        ]
    missing = [name for name in required_modules if name not in modules]
    required_files = [
        "_internal/frontend-sha256.json",
        "_internal/ssl-runtime-resources.json",
        "_internal/python312.dll",
        "_internal/_ssl.pyd",
        "_internal/libssl-3-x64.dll",
        "_internal/libcrypto-3-x64.dll",
        "_internal/certifi/cacert.pem",
        "_internal/base_library.zip",
        "_internal/_sqlite3.pyd",
        "_internal/pythonnet/runtime/Python.Runtime.dll",
        "_internal/clr_loader/ffi/dlls/amd64/ClrLoader.dll",
        "_internal/webview/lib/Microsoft.Web.WebView2.Core.dll",
        "_internal/webview/lib/Microsoft.Web.WebView2.WinForms.dll",
        "_internal/webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
    ]
    missing += [name for name in required_files if not (PAYLOAD / name).is_file()]
    if not list((PAYLOAD / "_internal").glob("_cffi_backend*.pyd")):
        missing.append("_cffi_backend*.pyd")
    if missing:
        raise ValueError("Incomplete QA runtime payload: " + ", ".join(missing))
    source_files = {}
    for file in (ROOT / "frontend").iterdir():
        if file.is_file():
            bundled = PAYLOAD / "_internal/frontend" / file.name
            if sha(file) != sha(bundled):
                raise ValueError("Bundled frontend differs from current source")
            source_files[file.name] = sha(file)
    forbidden = [
        str(file.relative_to(PAYLOAD))
        for file in PAYLOAD.rglob("*")
        if file.is_file()
        and (file.suffix.lower() in (".dpapi", ".sqlite", ".db") or file.name == "config.json")
    ]
    if forbidden:
        raise ValueError("Unexpected user/configuration files in QA payload: " + str(forbidden))
    notices = PAYLOAD / "notices"
    licenses = notices / "licenses"
    licenses.mkdir(parents=True)
    license_status = inventory(ROOT)
    collected = []
    for name in PACKAGES:
        dist = importlib.metadata.distribution(name)
        if name in PYWINRT_COMPONENTS and dist.version != "3.2.1":
            raise ValueError("Wrong PyWinRT version")
        for entry in dist.files or []:
            if Path(entry).name.lower().startswith(("license", "copying", "notice", "authors")):
                source = Path(dist.locate_file(entry))
                if not source.is_file():
                    raise FileNotFoundError(str(source))
                target = licenses / name / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                collected.append(
                    {
                        "component": name,
                        "version": dist.version,
                        "file": target.relative_to(PAYLOAD).as_posix(),
                        "sha256": sha(target),
                    }
                )
    pinned, source_manifest = checked_sources(ROOT)
    for name in PYWINRT_COMPONENTS:
        target = licenses / name / "LICENSE.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pinned["pywinrt"], target)
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
    shutil.copyfile(source_manifest, licenses / "SOURCES.json")
    # Preserve the already verified Tcl notice even when this GUI does not bundle Tcl/Tk.
    shutil.copyfile(pinned["tcl"], licenses / "tcl-8.6.12-license.terms")
    shutil.copyfile(ROOT / "docs/THIRD_PARTY_NOTICES.md", notices / "THIRD_PARTY_NOTICES.md")
    write(notices / "UI_LICENSE_STATUS.json", license_status)
    (notices / "QA_DISTRIBUTION_STATUS.txt").write_text(
        "LOCAL QA CANDIDATE ONLY. NOT FORMAL DISTRIBUTION.\n"
        "Known missing complete terms: proxy_tools 0.1.0 and Microsoft.Web.WebView2 SDK.\n"
        "Available original terms are collected beside this file. The generic notices may also describe legacy components.\n"
        "Do not publish or distribute this candidate to testers as a released product.\n",
        encoding="utf-8",
    )
    write(EXPORT / "SOURCE_SHA256.json", source_snapshot(ROOT))
    record = {
        "created": datetime.now(UTC).astimezone(ZoneInfo("Australia/Sydney")).isoformat(),
        "candidate": "v1.2-ui-qa-portable",
        "full_application_cli": full_app,
        "issue": "Frozen TLS initialization: preserve Python SSL companion rejection policy resource",
        "startup_protocol": "native initialization + mapped local document + DOM/bridge/backend/UI Ready",
        "mode": "synthetic_only_mock_external_services",
        "bridge": "real Python Bridge.invoke + actual WebView2 frontend",
        "gui_or_vm_run": False,
        "frozen_backend_check": "passed" if full_app else "not_required",
        "frozen_assignment_check": "passed" if full_app else "not_required",
        "frozen_credential_check": "passed" if full_app else "not_required",
        "frozen_tls_check": "passed" if full_app else "not_required",
        "ssl_runtime_resources": ssl_manifest,
        "visual_acceptance": "not_performed",
        "static_payload_status": "passed",
        "required_modules": required_modules,
        "required_runtime_files": required_files,
        "frontend_source_sha256": source_files,
        "exe_sha256": sha(program),
        "license_status": license_status["status"],
        "license_blockers": license_status["blockers"],
        "collected_package_license_files": collected,
        "optional_dependency_warnings": "See QA_BUILD.log and build-work/QAExport/warn-QAExport.txt; optional PDF crypto/image and non-Windows backends are not certified.",
    }
    write(PAYLOAD / "QA_BUILD_INFO.json", record)
    (PAYLOAD / "Launch-QA.cmd").write_text(
        '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n"%~dp0CanvasDeadlineAgent-UI-QA.exe" --mock %*\r\n'
        'set "CDA_QA_EXIT=%ERRORLEVEL%"\r\nif not "%CDA_QA_EXIT%"=="0" pause\r\nexit /b %CDA_QA_EXIT%\r\n',
        encoding="ascii",
    )
    (PAYLOAD / "Check-Runtime.cmd").write_text(
        '@echo off\r\n"%~dp0CanvasDeadlineAgent-UI-QA.exe" --preflight-only\r\npause\r\n', encoding="ascii"
    )
    (PAYLOAD / "Check-Backend.cmd").write_text(
        '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
        '"%~dp0CanvasDeadlineAgent-UI-QA.exe" --backend-check --data-dir "%LOCALAPPDATA%\\CanvasDeadlineAgent-v1.2-UI-QA"\r\n'
        'set "CDA_QA_EXIT=%ERRORLEVEL%"\r\npause\r\nexit /b %CDA_QA_EXIT%\r\n',
        encoding="ascii",
    )
    if full_app:
        (PAYLOAD / "Launch-Live-Integration.cmd").write_text(
            '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
            '"%~dp0CanvasDeadlineAgent-UI-QA.exe" --live --data-dir "%LOCALAPPDATA%\\CanvasDeadlineAgent-v1.2-Integration"\r\n'
            'set "CDA_QA_EXIT=%ERRORLEVEL%"\r\nif not "%CDA_QA_EXIT%"=="0" pause\r\nexit /b %CDA_QA_EXIT%\r\n',
            encoding="ascii",
        )
    (PAYLOAD / "Launch-Mapping-Probe.cmd").write_text(
        '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n"%~dp0CanvasDeadlineAgent-UI-QA.exe" --mock --mapping-probe %*\r\n'
        'set "CDA_QA_EXIT=%ERRORLEVEL%"\r\nif not "%CDA_QA_EXIT%"=="0" pause\r\nexit /b %CDA_QA_EXIT%\r\n',
        encoding="ascii",
    )
    instructions = r"""Canvas Deadline Agent v1.2 - Functional audit / 本地测试候选

已实际运行本冻结 EXE 的无窗口后端初始化检查；没有 Windows GUI/视觉验收结论。不要把浏览器 Mock 当成 Python 运行结果。

A. 离线 HTML：双击 UI-Preview.html。它使用当前真实前端，但数据桥接是明确标识的 Browser Mock Adapter。
   无需 Python、Token 或互联网；刷新即重置。可切换主题/语言，浏览各页，演示本地完成/忽略/恢复。

B. Windows QA（用户另行授权并亲自操作时）：只用现有 CanvasDeadlineAgent-Smoke，不克隆或重建环境。
   把 CanvasDeadlineAgent-UI-QA 整个目录复制到客体可写位置，保留 _internal 全部内容，不能只复制 EXE。
   双击 Launch-QA.cmd，或在该目录执行：CanvasDeadlineAgent-UI-QA.exe --mock
   真实 Python/SQLite 与 WebView2 连接；外部 Canvas/PushPlus/AI 请求和自动监控在 QA 模式禁止。
   默认合成数据：%LOCALAPPDATA%\CanvasDeadlineAgent-v1.2-UI-QA；重启保留主题、语言和本地状态。
   自定义数据：CanvasDeadlineAgent-UI-QA.exe --mock --data-dir C:\CDA-V12-QA-Data
   自定义目录必须全新空目录或本便携版标记的合成 QA 目录；拒绝非空未标记目录。
   它不读取生产版默认用户目录、不导入真实配置，不包含凭据。请勿手动填入真实 Token。
   Check-Runtime.cmd 只检查前置条件，不启动 GUI。需客体已有兼容 .NET Framework 和 WebView2 Runtime 120+。
   缺少 Runtime 时明确打印错误并退出，不自动下载/安装；请保留合成目录内 startup-error 文件。

   P0 诊断：每次启动日志保存在该 QA 数据目录 diagnostics\<run-id>\startup.jsonl。
   startup-status.json 必须为 ready 且包含全部原生导航、DOM、Bridge、backend_state 与 ui_ready 阶段。
   pywebview_loaded 或创建窗口都不是启动成功。failure.html 是独立错误页；原生 WebView2 无法显示时显示 WinForms 错误面板。
   resources.json 记录冻结资源绝对路径、大小和 SHA-256；runtime-page\index.html 是实际加载的完整前端文档。
   实际 URL 为 https://cda-ui.invalid/index.html，通过本地虚拟主机映射读取；无本地 HTTP 服务和联网请求。
   若仍失败，请保留该次 diagnostics 目录及 startup-error 文件；不需要重装 Windows、恢复快照或关闭防护。
   日志不记录异常原文、页面内容、请求参数、Canvas/PushPlus Token 或 AI Key。

   本轮后端专项：先运行 Check-Backend.cmd，不创建窗口，只调用 GUI 相同的配置加载与 Bridge State 初始化。
   backend-check-result.json 必须 status=passed；它只有 backend_state_ready，不伪造 DOM 或 ui_ready。
   再运行 Launch-QA.cmd，检查 mode=application、status=ready 和全部七个阶段。无需重复已通过的映射探针。
   保持 VM 断网、Defender 开启。无需重装、恢复快照、改 hosts 或安全设置。
   检查已有合成配置前，先将原字节保存在 config-backups\config-<SHA256>.json.bak。
   旧版缺失的兼容字段只在内存补默认值；原配置、数据库与凭据不清理、不重置。
   配置错误在 startup.jsonl 记录 configuration_error 的 stage、code、reason、fields，不记录值。
   未知字段名脱敏。若失败，请保留日志与备份，只修复指出的配置问题，不删除用户目录。
   cda-startup-v1 诊断消息与 pywebview 官方数组 RPC 在唯一入口分流，业务仍走 pywebview.api.invoke。
   初始化适配器先在同一 CoreWebView2 上安装映射，再调用 pywebview 原有回调发起唯一一次初始导航。
   navigation_result 保存 IsSuccess、WebErrorStatus、Source、NavigationId、HttpStatusCode 和 core_id。

   Assignment State Mutation Busy 复测：只运行 Launch-QA.cmd，打开合成作业，确认忽略后待办减少；
   重新打开程序，显示已忽略；恢复追踪，再标记本地完成。Canvas 原始状态必须保持不变。
   真正冲突的 Busy 会给出 operation/reason/blocking_operation；不会移除数据库或跨进程锁。
   request_timeout 表示结果尚未确认，不等于写入失败。不得重复发送，稍后刷新或重启核实已提交状态。
   本轮仅增加调用顺序、去重和错误处理，不改配色、字体或布局。

C. SHA-256：PAYLOAD_SHA256.json 和 SHA256SUMS.txt 给出完整载荷；可在 PowerShell 用 Get-FileHash -Algorithm SHA256 核对。
   UI_PREVIEW_PROVENANCE.json 记录离线预览和真实前端源码哈希。

D. 限制：缺少 proxy_tools 0.1.0 与 Microsoft WebView2 SDK 完整许可原文；其余可用许可已复制。
   只供本地 QA，不是正式分发包，不发布 GitHub，不称 Private Beta 放行；详见 notices/UI_LICENSE_STATUS.json。
   真实 WebView2 启动、桥接、原生安全事件、DPI、键盘和最终视觉效果仍待现有 VM 内的人工验收。
"""
    if full_app:
        instructions += r"""

E. 完整功能集成候选：EXE 包含正式业务 CLI（--scheduled / --guardian / --remove-task），无窗口后台入口不依赖 GUI。
   双击 EXE 或 Launch-QA.cmd 默认均为明确的合成 QA 模式，禁止真实凭据和系统副作用。
   Launch-Live-Integration.cmd 仅供另获授权后的客体手动真实接口验收：独立使用
   %LOCALAPPDATA%\CanvasDeadlineAgent-v1.2-Integration，初次为空；不会自动启用监控或迁移 v1.1。
   本次运行冻结 EXE 的后端、SQLite、DPAPI 和仅回环 HTTPS 自检，无 GUI、外部请求或计划任务副作用。
   当前 UI 外观沿用用户已认可版本；本新候选仍须原生功能复测，不据 headless 结果宣布验收。
   详细功能映射、Bridge 权限和手动验收见 integration-docs 目录。

F. 凭据专项：Launch-QA.cmd / --mock 为合成 QA，明确显示 qa_credentials_disabled；禁止输入真实密钥。
   需要正常配置凭据时，由用户在 Smoke VM 手动运行 Launch-Live-Integration.cmd，使用独立 Integration 数据目录。
   它不会自动连接 Canvas、发送微信、调用 AI 或注册计划任务；测试连接/发送/启用操作需用户明确点击。
   不要将已标记的 QA 目录用作真实模式目录。首次验证请先使用虚构字符串保存/替换/删除，不点击连接测试。
   Canvas、PushPlus 和 AI 均用当前 Windows 用户 DPAPI 加密；JS 只读取状态，保存后输入框清空。
   AI 密钥按 Provider 和完整 HTTPS Endpoint 隔离；切换到新 Provider 需单独保存它的密钥。
   旧 ai.dpapi 保留但不自动归属任何 Provider，界面提示重新绑定；不删除旧文件或重置数据。
   OpenAI/DeepSeek 要求对应官方 Endpoint；自定义兼容服务必须选择 Custom。
   冻结 EXE 已在独立合成目录通过 --credential-check，无窗口；这不等于客体 GUI/真实服务验收。
   完整审计与本次手动步骤见 ISO 根目录 audit-reports；保留原 QA 数据与诊断证据。

G. SSL 初始化修复：保留构建 Python 自带的 codex-rejected-cas.pem 证书拒绝策略原文。
   该文件位于 _internal 根目录；不是 ssl/cert.pem，也不替代 certifi/cacert.pem。
   ssl-runtime-resources.json 记录来源、大小和SHA-256；缺失或变化时构建/完整性核验失败。
   不修改SSLContext、系统证书库、CA环境变量或证书验证；verify=True与主机名校验保持开启。
   新冻结EXE已通过本地HTTPS、真实Bridge身份/同步、PushPlus/AI与无效证书拒绝测试。
   此证据不等于真实Canvas或新包VM验收；若TLS仍失败，startup.jsonl记录安全异常链及资源路径。
"""
        document_directory = PAYLOAD / "integration-docs"
        document_directory.mkdir()
        for name in ("FUNCTIONAL_INTEGRATION_MAP.md", "BRIDGE_API.md", "INTEGRATION_VM_ACCEPTANCE.md"):
            shutil.copyfile(ROOT / "docs" / name, document_directory / name)
    (PAYLOAD / "README-QA.txt").write_text(instructions, encoding="utf-8")
    (EXPORT / "START-HERE.txt").write_text(instructions, encoding="utf-8")
    manifest = {
        file.relative_to(PAYLOAD).as_posix(): sha(file)
        for file in sorted(PAYLOAD.rglob("*"))
        if file.is_file()
    }
    write(PAYLOAD / "PAYLOAD_SHA256.json", manifest)
    (PAYLOAD / "SHA256SUMS.txt").write_text(
        "\n".join(f"{value}  {name}" for name, value in manifest.items()) + "\n", encoding="utf-8"
    )
    staging = EXPORT / "iso-content"
    staging.mkdir()
    shutil.copytree(PAYLOAD, staging / PAYLOAD.name)
    for name in (
        "UI-Preview.html",
        "UI_PREVIEW_PROVENANCE.json",
        "UI_PREVIEW_TEST.json",
        "START-HERE.txt",
        "SOURCE_SHA256.json",
    ):
        shutil.copyfile(EXPORT / name, staging / name)
    staged = {
        file.relative_to(staging).as_posix(): sha(file)
        for file in sorted(staging.rglob("*"))
        if file.is_file()
    }
    write(EXPORT / "ISO_CONTENT_SHA256.json", staged)
    write(
        EXPORT / "QA_STATIC_VERIFICATION.json",
        record | {"payload_files": len(manifest), "staged_files": len(staged)},
    )
    print(
        json.dumps(
            {
                "status": "static_checks_passed_gui_not_run",
                "payload": str(PAYLOAD),
                "files": len(manifest),
                "exe_sha256": record["exe_sha256"],
                "license_blockers": license_status["blockers"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--full-app", action="store_true")
    args = parser.parse_args()
    finalize(args.export_dir, full_app=args.full_app)
