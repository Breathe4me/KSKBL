## 📥 Download / 下载

**Windows Beta v1.2.0-beta.1**

[📥 Download KSKBL for Windows / 下载 Windows 版本](https://github.com/Breathe4me/KSKBL/releases/tag/v1.2.0-beta.1)

Open **Assets**, then download the `Setup.exe` installer.

展开 **Assets**，下载 `Setup.exe` 安装程序。

> Beta software. Some Canvas quizzes may not be available through the API.
> 测试版本，部分 Canvas 测验可能无法同步。

# Canvas Deadline Agent

**我不想再提心吊胆错过due了**

Canvas Deadline Agent 是一款面向 Canvas LMS 用户的 Windows 桌面小工具。它可以整理已同步的课程作业、显示距离截止还有多久，并提供本地任务管理和可选的微信提醒。适合同时上多门课、不想每天逐个打开课程页面找作业的学生。

> **版本：** v1.2.0-beta.1（测试版） · Windows x64  
> **说明：** 这是独立开发的第三方项目，不是 Canvas / Instructure 或任何学校的官方软件。它不会替你向 Canvas 提交作业，也无法保证读取到每一项 Quiz 或截止任务。

## 可以做什么？

| 软件左侧菜单 | 功能 | 你可以怎么用 |
| --- | --- | --- |
| **今日概览** | 集中查看近期作业及截止倒计时 | 打开软件时先看这一页，了解最近要处理什么 |
| **所有作业** | 查看已同步的不同课程作业 | 找到作业后，点击右侧 **「查看详情」** 阅读更多信息 |
| **提交记录** | 区分 Canvas 返回的提交信息和本地完成标记 | 确认一项任务是学校系统显示已提交，还是仅被自己标记为完成 |
| **微信提醒** | 配置可选的 PushPlus 消息提醒 | 使用自己的 PushPlus Token，设置提醒后按实际运行条件接收消息 |
| **设置** | 管理 Canvas 连接、同步和其他可选功能 | 检查账号连接、点击 **「验证账号」** 或 **「立即同步」** |

另外，你可以通过作业卡片右边的 **「···」** 菜单，将任务标记为本地完成、忽略或恢复。**这些状态仅用于个人整理，不会在学校 Canvas 上帮你提交作业。**

## 下载与安装

### 1. 下载 Windows 安装包

1. 在本 GitHub 仓库中打开 **Releases**（发布版本）。
2. 选择最新的测试版，找到 **Assets**（下载附件）。
3. 普通用户请选择文件名以 **`-Setup.exe`** 结尾的安装包。
4. 下载完成后，在 Windows 的 **下载（Downloads）** 文件夹中找到它，双击并按照安装程序的提示完成安装。
5. 在 Windows **开始菜单**中搜索 **Canvas Deadline Agent** 并打开。

`Portable.zip` 是无需运行安装向导的便携版，适合熟悉 Windows 文件操作的用户；`Source.zip` 是源代码，不是普通用户的安装文件。

> 这是 Beta 版本，安装程序可能尚未签署代码签名证书。如果 Windows Defender 或 SmartScreen 提示拦截，**不要关闭安全保护强行安装**，请先核实下载来源和该版本的安全说明。

### 2. 检查电脑运行环境

目前主要针对 **Windows 11 x64** 测试。运行软件还需要：

- **Microsoft Edge WebView2 Runtime**：用于显示桌面界面。可从 [微软 WebView2 官方页面](https://developer.microsoft.com/en-us/microsoft-edge/webview2) 获取。
- **Microsoft Visual C++ x64 Runtime 14.44.35211.0 或更新版本（含 MFC）**：可从 [微软最新受支持的 VC++ 运行库页面](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) 获取。请安装 **x64** 版本。

**不需要单独安装 Python。** 如果程序一打开就退出或提示缺少 DLL，请先确认这两个运行环境已经安装，再重试。

## 第一次打开：连接 Canvas

Canvas 是学校发布作业和测验的系统。Canvas Deadline Agent 需要得到学校和账户允许的授权，才能同步你有权限查看的信息。

1. 打开软件左侧 **「设置」**。
2. 找到 Canvas 连接相关设置，确认学校的 Canvas 网站地址。网址是你平时在浏览器中登录 Canvas 使用的地址，而不是某一门课程的具体页面。
3. **按照学校批准的 Canvas 授权方式完成连接。** 成功保存连接后，点击 **「验证账号」**。
4. 验证成功后，点击 **「立即同步」**。
5. 打开左侧 **「所有作业」**，查看同步结果。

**关于 Canvas API Token：** 当前部分测试构建支持手动凭据配置，但这**不等于所有普通学生都可以自行生成 Access Token 并粘贴到第三方应用中**。Instructure 的现行 API 指南要求第三方应用使用获批准的授权方式（如 OAuth）；学校也可能限制 API 访问。**不要把 Canvas 密码或 Token 发送给开发者，也不要为了连接本应用绕过学校规定。** 如果公开版本尚未提供你所在学校认可的授权流程，请先不要配置手动 Token，等待正式支持或咨询学校管理员。

官方说明：[Canvas API Token 管理](https://community.instructure.com/en/kb/articles/662901-how-do-i-manage-api-access-tokens-in-my-user-account) · [Canvas OAuth2](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth)

### 同步后看到「部分范围不可用」怎么办？

例如某些课程可能显示 `quiz_list_disabled`。这通常表示该课程的 Quiz 列表没有成功获取，**不是“这门课没有 Quiz”**。课程权限、不同 Quiz 类型和学校设置都可能影响同步范围。考试和重要截止日期请继续以学校 Canvas 官网为准。

## 微信提醒：连接 PushPlus（可选）

不需要使用微信提醒，也可以正常查看作业。想在微信收到消息，需要先准备一个 **PushPlus Token**；它是消息服务用来识别你的凭据，不是 Canvas 的 Token。

1. 打开 PushPlus 官网：**https://www.pushplus.plus/**，按页面提示登录，并完成服务所要求的账户验证。
2. 进入 PushPlus **「一对一消息」** 页面：**https://www.pushplus.plus/push1.html**。
3. 在页面顶部 **「用户 Token」** 部分，点击 **「一键复制」**。
4. 回到 Canvas Deadline Agent，点击左侧 **「微信提醒」**。
5. 在页面中的 PushPlus Token 配置位置粘贴刚才复制的内容，并按页面提示保存、启用提醒。
6. 按应用提供的测试方式检查能否收到消息；同时确认你已经按 PushPlus 官网指引关联对应的微信接收渠道。

**没有收到消息？** 先检查 PushPlus 账户是否满足发送条件、Token 是否有效、微信渠道是否已正确关联，以及电脑是否按设定时间运行。PushPlus 官网提示，未完成实名要求的账户可能无法调用发送接口。发送请求成功也不一定表示消息最终送达。

> **安全提示：** PushPlus Token 和 Canvas Token 一样需要保密。不要把含 Token 的设置页截图发到公开 Issues 中。

## 日常怎么用？

**每天打开：** 先看 **「今日概览」**，了解最接近截止的任务。  
**想找某项作业：** 点击 **「所有作业」** → 找到课程和标题 → **「查看详情」**。  
**暂时不想看到某项任务：** 点击作业右侧的 **「···」** → 使用忽略功能，之后可以恢复。  
**自己已经完成：** 使用本地完成标记；正式提交仍必须去 Canvas 操作。  
**想核对是否提交：** 看 **「提交记录」**，并以 Canvas 官网的提交状态为最终依据。  
**要更新列表：** 前往 **「设置」** → 点击 **「立即同步」**。

## 可选 AI 功能

软件提供可选的 **BYOK（自备 API Key）** AI 辅助功能。只有你主动配置并使用支持的 AI 服务时才需要相关密钥；第三方模型服务可能产生费用。AI 可以辅助理解课程信息或整理工作，但输出应由你自行检查，并遵守学校的学术诚信政策。软件不会自动代替你向 Canvas 提交作业。

## 常见问题

**看不到某门课的作业？** 先在 **「设置」** 中检查账号并点击 **「立即同步」**。如果同步提示权限不可用或缓存过期，请到 Canvas 官网核实，不能把空列表当成没有任务。

**在软件里点了“本地完成”，老师能看到吗？** 不能。这只是软件里的个人标记。提交作业需要使用 Canvas 官方提交入口。

**关机之后微信还能提醒吗？** 不能保证。本地后台检查依赖 Windows 运行状态、网络、系统任务配置和 PushPlus 服务。请不要把软件作为唯一的截止提醒渠道。

**必须配置 PushPlus 或 AI 吗？** 不需要。你可以只使用作业查看和整理功能。

**适用于所有学校吗？** 仅适用于使用 Canvas LMS、且允许相应授权与数据读取的环境；学校权限和功能覆盖可能不同。

## 隐私与安全

- 应用在 Windows 本地运行；相关凭据设计使用 Windows 的安全存储机制。
- 读取的 Canvas 数据受你的账号权限和学校配置限制。
- 启用 PushPlus、AI 等第三方服务时，相关请求或消息内容可能会发送给对应服务商，请自行阅读其隐私条款。
- 不要在公开仓库、截图或错误报告中包含密码、Access Token、API Key、个人课程内容等敏感信息。

## 项目状态与反馈

当前为 **Beta 测试版**。某些 Quiz、截止日期或提交信息可能因为 Canvas API 限制而缺失或延迟。**它是辅助工具，不是学校 Canvas 的替代品。**

一般问题和功能建议可以使用仓库的 **Issues**（如仓库已开放）；安全问题不要在公开 Issue 中披露密钥或可利用细节。

**许可证：** 项目计划采用个人非商业使用友好的 source-available 模式，但最终许可条款仍以仓库正式发布的 `LICENSE` 为准。**源代码公开不自动意味着允许任意复制、修改或商业再分发。**

---

*Canvas Deadline Agent is an independent project and is not affiliated with or endorsed by Instructure, Canvas LMS, or any university.*
