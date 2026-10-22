# v1.2 本地数据迁移

默认数据目录改为 `%LOCALAPPDATA%\CanvasDeadlineAgent-v1.2`，安装器使用新的 AppId、程序目录和开始菜单组。v1.1 源码、二进制和用户目录不打开迁移、不覆盖。

SQLite `user_version=2` 新增 `local_tracking(account, task_key, state, reason, note, fingerprint, updated)`。account 使用验证后的 Canvas 实例与用户 ID 散列，task_key 含课程与作业 ID；换 Token 但同一账号不丢失选择。切换账号仅清空活动缓存与通知账本，保留不同命名空间的本地标记。

schema 1 首次迁移使用 SQLite backup API 创建 `pre-v12-时间戳.sqlite`（包含已提交 WAL 页面），之后用事务创建新表并更新版本。设置新增 `theme`；读取旧 JSON 时仅在内存填默认值，不改原文件。Canvas 状态不被本地操作改写。

推荐旧版先在高级设置导出不含凭据的本地备份 ZIP。新版“设置 → 导入 v1.1 本地备份”只接受 config.json 与 state.sqlite；先校验大小、结构、数据库完整性与版本，在临时副本中迁移，再创建 before-import-* 恢复目录。文件替换异常时恢复旧数据库与配置。导入不包含 DPAPI 凭据或下载附件，导入后 monitoring=False，须用户重新绑定并复核计划。

合成测试覆盖重启、再同步、恢复、跨用户／实例、失败导入原件不变和成功导入备份。导入期间禁止另开同一数据目录的程序。配置/数据库异常应先保留恢复目录，避免手动清理原数据。
