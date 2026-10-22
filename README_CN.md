# Canvas Deadline Agent

独立 Windows 学生作业提醒工具，Python/SQLite 后端与离线 WebView2 UI。支持 Warm Sage／Soft Pink、中英文、只读 Canvas 同步、本地完成／忽略／恢复、可选 Windows/PushPlus 提醒及 AI BYOK。

v1.2.0-beta.1 仅为本地发布候选，尚未获准公开发布。非 Canvas、Instructure 或悉尼大学官方产品，没有学校支持或认证声明。

Windows 11 x64、.NET Framework 4.8、WebView2 Runtime 120+；无需自行安装 Python。程序不自动下载 WebView2。完整说明见 INSTALL.md。

首次打开是真实空配置，不是 QA 演示。到设置→Canvas 填写个人学生API Token并安全保存，再测试身份、同步。没有 Token 时不显示演示作业。目前没有独立多步首次运行向导；使用现有空状态和设置入口，不把向导标为已完成。

AI和后台监控默认关闭，测试微信和付费AI均需主动操作。数据覆盖依赖个人权限，Quiz接口可能被课程关闭。不保证获取所有作业或替代人工核对截止日期。本地完成不等于Canvas提交，官方记录为准；UNKNOWN不能当成功。PushPlus依赖第三方，接口接受不等于微信送达。

应用授权方向为 source-available 草案：个人学生非商业学习免费，商业、学校机构及企业用途拟要求另行许可。LICENSE尚未最终确认，不是MIT/Apache等OSI开源授权；需确认权属并法律审查。第三方依赖仍遵守原许可。安全、许可、原生安装和实际服务验收阻断见 KNOWN_LIMITATIONS.md。
