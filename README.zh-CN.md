# Canvas Deadline Agent

**🌐 Language / 语言： [🇬🇧 English](README.md) | [🇨🇳 简体中文](README.zh-CN.md)**

---

我真不想提心吊胆天天登 Canvas 了！

## 📥 Download / 下载

**Windows Beta v1.2.0-beta.1**

[📥 Download KSKBL for Windows / 下载 Windows 版本](https://github.com/Breathe4me/KSKBL/releases/tag/v1.2.0-beta.1)

Open **Assets**, then download the `Setup.exe` installer.

展开 **Assets**，下载 `Setup.exe` 安装程序。

> Beta software. Some Canvas quizzes may not be available through the API.
> 测试版本，部分 Canvas 测验可能无法同步。

# Canvas Deadline Agent

**我真不想提心吊胆天天登canvas了**

Canvas Deadline Agent 是一款面向 Canvas LMS 用户的 Windows 桌面小工具。它可以整理已同步的课程作业、显示距离截止还有多久，并提供本地任务管理和可选的微信提醒。

适合同时上多门课、不想每天逐个打开课程页面找作业的学生。

**当前版本：** v1.2.0-beta.1 · Windows 测试版

> 这是独立开发的第三方软件，不是 Canvas 或任何大学的官方产品。软件不会替你正式提交作业，也不能保证读取所有 Quiz。

## 主要功能

| 在哪里 | 能做什么 |
|---|---|
| **今日概览** | 看看最近有哪些作业快截止了 |
| **所有作业** | 把不同课程的作业集中在一个地方 |
| **提交记录** | 区分 Canvas 已提交和自己标记的本地完成 |
| **微信提醒** | 配置 PushPlus，让微信接收截止提醒 |
| **设置** | 管理 Canvas 连接、同步及其他功能 |

打开「所有作业」，找到作业后点击「查看详情」，可以查看已读取的要求和相关信息。

作业右侧的「···」菜单可以用来忽略、恢复或标记本地完成。

**注意：本地完成不等于学校 Canvas 已经收到你的作业。**

## 下载和安装

1. 打开本仓库的 **Releases** 页面。
2. 选择最新的 Beta 版本。
3. 在 **Assets** 中下载以 `-Setup.exe` 结尾的安装包。
4. 在 Windows 的「下载」文件夹中找到安装包，双击运行。
5. 按照安装程序提示完成安装。
6. 打开 Windows 开始菜单，搜索 **Canvas Deadline Agent**。

目前主要针对 Windows 11 x64 测试。

运行软件需要 Microsoft Edge WebView2 Runtime，以及 Microsoft Visual C++ x64 Runtime 14.44.35211.0 或更新版本（含 MFC）。可从微软官方网站安装这些组件。

不需要自己安装 Python。

## 如何连接 Canvas？

Canvas 是学校管理课程、作业和测验的平台。

1. 打开 Canvas Deadline Agent。
2. 点击左侧 **「设置」**。
3. 找到 Canvas 连接相关设置。
4. 按照学校批准的授权方式完成连接。
5. 连接成功后点击 **「验证账号」**。
6. 点击 **「立即同步」**。
7. 返回 **「所有作业」** 查看同步结果。

**关于 Canvas API Token：**

当前部分测试构建支持手动配置访问凭据，但这种方式不代表适用于所有学校或普通学生。正式面向用户的接入必须遵守 Canvas 及学校的授权规则。

请不要把 Canvas 密码或 Token 发送给其他人。如果学校没有批准相应的连接方式，请等待正式支持。

## 如何开启微信提醒？

微信提醒由第三方服务 PushPlus 提供，不需要此功能也可以正常使用软件。

1. 打开 [PushPlus 官网](https://www.pushplus.plus/) 并登录。
2. 进入 [一对一消息页面](https://www.pushplus.plus/push1.html)。
3. 在「用户 Token」区域点击「一键复制」。
4. 返回 Canvas Deadline Agent，点击左侧 **「微信提醒」**。
5. 将 Token 粘贴到 PushPlus 配置位置。
6. 根据软件页面提示保存并启用提醒。
7. 确认 PushPlus 微信接收渠道已经设置好，并测试消息是否送达。

PushPlus 可能要求完成账户实名认证才能发送消息。

**提醒能否送达取决于电脑运行状态、网络、PushPlus 服务以及软件的提醒配置。**

## 可选 AI 功能

软件提供可选的 AI 辅助功能。

你可以使用自己拥有的 API Key 接入支持的 AI 服务，辅助理解作业信息、整理要求等。

AI 不是必需功能，也不会自动代替你向 Canvas 提交作业。部分模型服务可能产生费用。

## 使用时需要注意

- 某些学校会限制 Quiz API，因此有些测验可能无法同步。
- 如果显示「部分范围不可用」，不代表没有作业。
- 软件中的「本地完成」只是个人标记，不等于正式提交。
- 关闭电脑后，后台提醒不保证继续运行。
- 重要考试及作业的最终信息，以学校 Canvas 官网为准。

## 隐私与安全

Canvas Deadline Agent 在 Windows 电脑上本地运行，并使用 Windows 安全机制保护相关凭据。

启用 PushPlus 或第三方 AI 时，相关内容可能被发送到对应服务商。请不要在公开截图、GitHub Issues 或聊天中泄露 Canvas Token、PushPlus Token 和 AI API Key。

## 项目状态

Canvas Deadline Agent 目前处于 Beta 测试阶段。

如果发现问题，可以通过本仓库的 Issues 反馈，但请勿公开个人信息或密钥。

这是独立开发的第三方学习工具，与 Instructure、Canvas LMS 或任何大学不存在官方隶属或合作关系。
