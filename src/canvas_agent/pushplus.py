"""Official PushPlus JSON contract. No response body or token enters an exception."""

import requests

from .transport import canvas_session as secure_session


class PushPlusError(RuntimeError):
    def __init__(self, code, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


class PushPlusChannel:
    def __init__(self, token, session=None):
        self.token, self.session = token, session or secure_session()

    def send(self, title, body, url, important=False):
        if not self.token:
            raise PushPlusError("pushplus_not_configured")
        try:
            response = self.session.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": self.token,
                    "title": title[:100],
                    "content": body + ("\n" + url if url else ""),
                    "template": "txt",
                    "channel": "wechat",
                },
                timeout=(8, 20),
                allow_redirects=False,
            )
        except (requests.Timeout, requests.ConnectionError):
            # The service may already have accepted this POST. Never replay automatically.
            raise RuntimeError("pushplus_result_uncertain") from None
        if response.status_code == 429:
            raise PushPlusError("pushplus_rate_limited", retryable=True)
        if response.status_code != 200:
            raise RuntimeError("pushplus_http_uncertain")
        try:
            result = response.json()
            code = result.get("code") if isinstance(result, dict) else None
        except ValueError:
            raise RuntimeError("pushplus_response_uncertain") from None
        if code != 200:
            reason = {
                900: "account_restricted",
                905: "identity_required",
                903: "invalid_token",
                888: "quota_or_credit",
                401: "unauthorized",
                403: "access_denied",
                500: "service_error",
            }.get(code, "request_rejected")
            raise PushPlusError("pushplus_" + reason, retryable=code == 500)
        return {"status": "accepted", "delivered": None}
