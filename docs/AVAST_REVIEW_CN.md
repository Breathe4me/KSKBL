# rc2 Avast 调查、修复与验证报告

日期：2026-10-20（Australia/Sydney）。版本：**1.0.0rc2，安全结论 Pending，禁止正式发布**。

## 根因与证据边界

已确认的程序调用原因：rc1 的 Windows 通知模块 `WindowsChannel.send()` 每发一条桌面通知，就调用
`subprocess.run()` 创建隐藏的 Windows PowerShell 进程，参数为：

```text
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
  -NoProfile -NonInteractive -EncodedCommand [通知脚本载荷已省略]
creationflags = CREATE_NO_WINDOW
```

该调用位于旧 `notifications.py` 第 44–49 行。载荷是构造 Toast 的 WinRT 脚本，包含通知文本，因此没有
记录或导出原始命令载荷。用户报告的 G 盘 EXE 与开发版 rc1 EXE 的 SHA256 均为：

`95846bf6f5f74525dd43e420004a76ce70f290a33577e09f2a1c37f4d2f5e3ac`。

因此可以确认这是同一已知构建中的实际 PowerShell 调用路径，不能把问题只归因于 Task Scheduler。
旧调度模块另调用 `whoami.exe` 和 `schtasks.exe /Create /Query /Delete`，没有调用 PowerShell。

**未能确认的部分：** Avast 两次 `IDP.HELU.PSE94` 的精确检测规则、原始告警时间、历史父进程 PID 和完整
命令事件尚未取证。可读的 BehaviorShield/FileSystemShield 报告没有相关检测条目；detections/scans 等日志
被拒绝读取，未尝试绕过自保护。Task Scheduler Operational 日志未启用，Sysmon/Security 事件不可用。
autosandbox 只提供运行痕迹（含 15:39:12 的 Canvas 运行记录），不是检测结论，不能当作原告警时间。

没有证据证明它是 Avast 误报。首次 EXE 检测本身也不能由以上源码路径单独解释。

## 全部调用面审计

| 流程 | rc1 实现 | rc2 实现 |
| --- | --- | --- |
| GUI 启动、向导与列表 | Tk/SQLite，本身不发起 PowerShell | 保持；实际打包 GUI 启动通过 |
| Canvas Test Connection | 只读 HTTPS GET | 保持；真实尝试因 SSLError 未完成 |
| Check Now / 强提醒 / 逾期 / 公告 / 周报 | 确定性引擎；桌面通知间接进入 PowerShell | 引擎与规则保留，桌面通知转进程内 WinRT |
| 开启监控、保存/修改计划 | whoami + schtasks 子进程 | pywin32 `Schedule.Service` COM |
| 查询与移除任务、卸载清理 | schtasks 子进程 | COM GetTask/DeleteTask，仅操作本软件命名任务 |
| GUI 关闭后检查 | Task Scheduler 直接运行本软件 --scheduled | 同样直接运行 EXE，不使用脚本解释器 |
| 打开 Canvas 原链接 | Python webbrowser 交给系统默认浏览器 | 保留，仅由用户操作触发 |
| PushPlus / AI | requests HTTP，无脚本执行 | 保留，测试期间均未调用 |
| 开发脚本 | build.ps1 调用 PyInstaller/Inno，secret_scan.py 调用 Git | 仅开发/CI，非安装后普通运行流程 |
| 安装/卸载 | Inno lowest；隐藏启动本软件 --remove-task | 保留直接 EXE 清理，无命令解释器 |

未发现运行时代码使用 os.system、shell=True、ExecutionPolicy Bypass、runas、远程脚本或请求管理员权限。
rc1 的隐藏窗口和 EncodedCommand 是明确存在的行为，已从通知模块移除。没有把解释器改名、增加混淆或规避扫描。
UPX 保持关闭。调度模块剩余 `subprocess.list2cmdline` 只做 Windows 参数转义，不创建进程。

## 实际修改

- `notifications.py`：用 PyWinRT 的 `create_toast_notifier_with_id`、XmlDocument、ToastNotification 直接调用
  Windows；保留重要程度、正文和原始链接，检查 NotificationSetting，不提供 PowerShell 回退。
- `schedule.py`：pywin32 动态 Dispatch 本地 Schedule.Service，NewTask + RegisterTaskDefinition 创建/更新，
  GetTask 查询、DeleteTask 删除；删除临时 XML 文件、whoami/schtasks 进程创建。XML 合同与哈希任务名不变。
- `windows_native.py`：每个工作线程正确初始化 COM、在释放接口后结束 apartment；只输出稳定错误码/HRESULT。
  识别 IDispatch 包装在 EXCEPINFO 内的真实 HRESULT，避免将不存在的任务误报为清理失败。
- `process_diagnostics.py` / `app.py`：显式 `--trace-native` 仅记录 PID、时间、进程名和 Python 调用栈位置，
  不记录命令参数、脚本载荷、课程正文或密钥；新增本地 `--test-notification` 诊断入口。
- pyproject / requirements / PyInstaller spec / 第三方许可证收集：固定并打包 pywin32 与所需 PyWinRT 绑定。
- 测试：新增原生命令调用禁用检查、Toast XML、权限错误、COM 创建更新/删除、包装 HRESULT 和诊断脱敏回归。
- `release-status.json` 明确 formal_release_allowed=false；Tag workflow 读取该门禁，在 Pending 时不创建 Release。

普通用户权限、InteractiveToken、LeastPrivilege、IgnoreNew、一分钟本地门控、登录补查、考试周、周报、并发锁
与提醒规则均保留。没有改动 G 盘安装、原有用户计划任务、Mini PC、Proxmox 或 LXC 101。

## 实际验证

| 项目 | 结果与限制 |
| --- | --- |
| 自动测试 | **123 passed**，0 失败/错误；Ruff 通过。覆盖率 73.88%（显示 74%），不等于完整验收 |
| 后台线程原生调用 | 非管理员令牌下，COM 创建/更新/查询/删除与 WinRT 通知 API 接收成功；Python 进程启动审计 0 事件 |
| 打包 GUI | 实际退出 0，7 页，默认强提醒 48h、AI 默认关闭 |
| 打包原生通知 | 实际退出 0，API 接收成功；实际可见及点击确认仍 Pending |
| 关闭 GUI 后后台执行 | Task Scheduler 实际启动同一打包 EXE --scheduled，LastTaskResult=0；测试配置关闭联网监控，完整真实同步 Pending |
| 调度权限 | RunLevel=0、LogonType=3；注册/更新/移除均通过，仅使用新隔离任务 |
| 真实 Canvas | 经用户授权，使用现存 Windows 凭据仅尝试 GET。返回 network_or_timeout，进一步分类为 SSLError；无课程数据导出、无 AI/PushPlus 调用，未关闭证书验证 |
| 依赖漏洞审查 | 13 个固定运行依赖，本次查询无已知漏洞返回 |
| Avast EXE 文件扫描 | 最终 rc2 EXE，ashCmd 控制台退出 0，未报告威胁 |
| Avast 安装包文件扫描 | 最终 rc2 Setup，ashCmd 控制台退出 0，未报告威胁 |
| 安装后与卸载 | 独立 rc2 QA 产品/含空格目录；详见 reports/rc2-installed.json 的实测结果 |

Avast 扫描仅针对新 EXE 与安装包，使用现有扫描器 `/_ /a /c /t=A /p=4`：发现威胁即停止，未降低启发式、
未加排除项、未自动删除或修复；没有上传 VirusTotal 或提交外部样本。未更改 Avast 防护或既有例外。
扫描退出 0 不能作为行为防护无告警、软件绝对安全或厂商已确认误报的证明。

## 仍存在的进程证据与 Pending

全部观察样本中均未发现 PowerShell/pwsh。不能只保留最后一次干净样本：

- 17:02:42 AEDT（UTC 06:02:42）：第一版原生候选通知测试，父进程 CanvasDeadlineAgent PID 25208 下出现 cmd.exe PID 16236。
- 17:06:00 AEDT（UTC 06:06:00）：最终 EXE 通知测试，父进程 PID 16764 下出现 cmd.exe PID 27620；Python 启动审计 0 事件。
  同轮另观察到 SogouCloud/SGDownload 后代进程，但这些现象**不足以确定是哪一个原生模块创建了 CMD**，不得直接归咎输入法或 Avast。
- 17:07:53–17:07:58 AEDT：相同最终 EXE 的后续复测未观察到命令子进程，Python 启动审计仍为 0。

进程采样间隔 20ms；没有内核级完整历史事件，极短进程可能遗漏。异常 CMD 的准确命令和原生调用栈仍 Pending。
应用源码与 Python 调用路径已消除解释器启动，但不能宣称本机所有原生组件下零命令进程或告警已彻底解决。

尚需：Avast 受保护告警详情/Alert ID、原始检测事件与父子进程证据；异常 CMD 的原生调用栈；确认行为防护开启下
多轮完整真实 Canvas 检查无告警；解决真实环境 TLS 错误后重测；可见/可点击通知；Windows 10/11 干净环境复核。
可按 Avast 官方流程向厂商提交审查，但本次未提交文件或代用户宣称误报。

**发布结论：Pending / 不允许正式 GitHub Release。** 新安装包仅用于继续审查与受控验证，不覆盖旧版，不要求关闭防护或白名单解释器。

## 主要参考

- Microsoft Task Scheduler RegisterTaskDefinition 与安全上下文：
  https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertaskdefinition
  https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks
- PyWinRT 官方文档与实际安装包 .pyi 方法签名： https://pywinrt.readthedocs.io/en/latest/
- Avast 官方扫描器选项/退出码（该页面适用 Business；本机消费版 CLI 的帮助和实际返回也已核对）：
  https://businesshelp.avast.com/Content/Products/AfB_Antivirus/ConfiguringSettings/CommandLineUpdatesScans.htm
- Avast 官方审查入口说明： https://support.avast.com/article/258/
