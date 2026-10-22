"""Human-readable AI status without provider response bodies or exception strings."""

REASONS = {
    "summary_type": ("Missing or invalid summary text.", "摘要字段缺失或类型不正确。"),
    "summary_length": ("Summary must contain 50-150 characters.", "摘要必须为 50–150 个字符。"),
    "importance_enum": ("Importance must be High, Medium or Low.", "重要性必须为 High、Medium 或 Low。"),
    "todos_type": ("Todos must be a list of text items.", "待办必须为文本列表。"),
    "dates_type": ("Dates must be a list of text items.", "日期必须为文本列表。"),
    "output_truncated": ("The provider truncated the output.", "模型输出被截断。"),
    "content_type": ("Provider content is not text.", "模型内容不是文本。"),
    "content_too_large": ("Provider content exceeds the size limit.", "模型内容超过大小上限。"),
    "response_too_large": ("Provider response exceeds the size limit.", "服务响应超过大小上限。"),
    "json_object_required": ("A JSON object is required.", "返回值必须是 JSON 对象。"),
    "invalid_json": ("Provider returned invalid JSON.", "模型返回了无效 JSON。"),
    "transport_or_envelope": ("Network or response structure failed.", "网络或响应结构异常。"),
    "manual_retry_required": ("No automatic retry was made.", "没有自动重试。"),
    "another_ai_request": ("Another AI request is in progress.", "已有 AI 请求正在处理。"),
}
STATUS = {
    "provider_endpoint_mismatch": (
        "AI provider and endpoint do not match. Review the saved settings.",
        "AI 服务与地址不匹配，请检查已保存设置。",
    ),
    "invalid_response": ("Summary validation failed.", "摘要校验未通过。"),
    "failed_fallback": ("AI request failed; Canvas data is retained.", "AI 请求失败；Canvas 数据保留。"),
    "retry_later": ("Provider is busy; retry manually later.", "服务繁忙，请稍后手动重试。"),
    "request_in_progress": (
        "A previous request is active or has an uncertain outcome.",
        "上次请求仍在执行，或结果尚未确定。",
    ),
    "daily_budget_exhausted": ("Summary request budget reached for today.", "今日摘要请求预算已用完。"),
    "disabled": ("AI is disabled.", "AI 未启用。"),
    "busy": ("Another AI request is in progress.", "已有 AI 请求正在处理。"),
    "not_generated": ("No summary has been generated.", "尚未生成摘要。"),
    "deferred_request_limit": (
        "No summary for this content; use Generate to request one.",
        "当前内容尚无摘要；可点击生成。",
    ),
    "empty_announcement": ("The announcement has no text.", "公告没有正文。"),
    "input_too_large": ("Text exceeds the limit; review the original.", "文本超过上限，请查看原文。"),
    "provider_unavailable": ("The AI provider is unavailable.", "AI 服务暂不可用。"),
    "stale_context": ("The account changed; the old result was discarded.", "账号已变化，旧结果已丢弃。"),
    "missing_consent_or_key": ("Save AI consent and a key first.", "请先保存 AI 同意项和密钥。"),
}


def format_result(result, language="en"):
    index = int(language == "zh")
    status = result.get("status", "unknown")
    if status == "ok":
        lines = [result.get("label", "AI — verify manually / 请人工核对"), result.get("summary", "")]
        if result.get("importance"):
            lines.append(result["importance"])
        lines.extend("- " + str(x) for x in result.get("todos", []))
        lines.extend("- " + (x["text"] if isinstance(x, dict) else str(x)) for x in result.get("dates", []))
        return "\n\n".join(lines)
    lines = [STATUS.get(status, ("AI is unavailable.", "AI 暂不可用。"))[index]]
    reason = result.get("reason")
    if reason in REASONS:
        lines.append(REASONS[reason][index])
    lines.append(
        (
            "Saved Canvas data and official deadlines are unchanged.",
            "已保存的 Canvas 数据和官方截止时间不受影响。",
        )[index]
    )
    if result.get("cached") or result.get("request_made"):
        lines.append(
            (
                "No automatic resubmission. Force regenerate is a new paid request.",
                "不会自动重复请求；“重新生成”会发起新的计费请求。",
            )[index]
        )
    return "\n\n".join(lines)
