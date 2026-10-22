"""Windows DPAPI (current user), OS-held lock, and output sanitization."""

import ctypes
import hashlib
import html
import json
import os
import re
from ctypes import wintypes
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from .config import atomic_write, https_url, load


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.suppressed += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.suppressed = max(0, self.suppressed - 1)

    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)


def plain(value, limit=12000):
    p = _Text()
    p.feed(str(value)[:100000])
    return " ".join(html.unescape(" ".join(p.parts)).split())[:limit]


def plain_lines(value, limit=12000):
    """Strip markup while preserving report paragraphs and deliberate newlines."""

    class Lines(_Text):
        def handle_starttag(self, tag, attrs):
            super().handle_starttag(tag, attrs)
            if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
                self.parts.append("\n")

        def handle_endtag(self, tag):
            super().handle_endtag(tag)
            if tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
                self.parts.append("\n")

    parser = Lines()
    parser.feed(str(value)[: max(100000, limit)])
    text = html.unescape("".join(parser.parts)).replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:limit]


def redact(text, secrets=()):
    text = str(text)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"(?i)(bearer\s+|(?:token|api[_ -]?key|authorization)[\s\"']*[:=][\s\"']*)[^\s,\"'<>]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)
    return text


def safe_link(value, base):
    try:
        p, b = urlsplit(value), urlsplit(base)
        if p.scheme == "https" and p.netloc == b.netloc and not p.username and not p.query and not p.fragment:
            return value
    except ValueError:
        pass
    return ""


class Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, protect):
    if os.name != "nt":
        raise RuntimeError("Secret storage requires Windows DPAPI")
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    fn.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError("DPAPI operation failed; credentials belong to this Windows user")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(result.pbData)


class CredentialError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def ai_endpoint(config):
    endpoint = https_url(config["ai_url"])
    expected = {"OpenAI": "api.openai.com", "DeepSeek": "api.deepseek.com"}.get(config["ai_provider"])
    if expected and urlsplit(endpoint).hostname != expected:
        raise CredentialError("ai_endpoint_mismatch")
    return endpoint


def ai_key(vault, config):
    # Bind to the request's validated configuration snapshot, not a later config reload.
    reader = getattr(vault, "get_ai", None)
    return reader(config) if reader else vault.get("ai")


class Secrets:
    names = ("canvas", "pushplus", "ai")

    def __init__(self, root):
        self.root = Path(root)

    def get(self, name):
        if name not in self.names:
            raise ValueError("Unknown credential")
        if name == "ai":
            return self.get_ai(load(self.root / "config.json"))
        path = self.root / f"{name}.dpapi"
        return dpapi(path.read_bytes(), False).decode() if path.exists() else ""

    def set(self, name, value):
        if name not in self.names:
            raise ValueError("Unknown credential")
        path = self._ai_path(load(self.root / "config.json")) if name == "ai" else self.root / f"{name}.dpapi"
        self._write(path, value)

    def _ai_path(self, config):
        scope = hashlib.sha256(
            json.dumps([config["ai_provider"], ai_endpoint(config)], separators=(",", ":")).encode()
        ).hexdigest()
        return self.root / f"ai-{scope}.dpapi"

    def get_ai(self, config):
        path = self._ai_path(config)
        # An unscoped legacy key cannot safely be assigned to a provider. Preserve it without using it.
        return dpapi(path.read_bytes(), False).decode() if path.exists() else ""

    def set_ai(self, config, value):
        self._write(self._ai_path(config), value)

    def legacy_ai_requires_rebind(self, config):
        if not (self.root / "ai.dpapi").exists():
            return False
        try:
            return not self._ai_path(config).exists()
        except ValueError:
            return True

    def _write(self, path, value):
        try:
            if value:
                atomic_write(path, dpapi(value.encode(), True))
            else:
                path.unlink(missing_ok=True)
        except (OSError, UnicodeError):
            raise CredentialError("credential_storage_failed") from None

    def values(self):
        paths = [self.root / f"{name}.dpapi" for name in self.names]
        paths += [
            path
            for path in self.root.glob("ai-*.dpapi")
            if re.fullmatch(r"ai-[a-f0-9]{64}\.dpapi", path.name)
        ]
        result = []
        for path in paths:
            try:
                if path.is_file():
                    result.append(dpapi(path.read_bytes(), False).decode())
            except (OSError, UnicodeError):
                continue  # an unreadable optional key must not disable unrelated core notifications
        return result


class AlreadyRunning(RuntimeError):
    pass


class ProcessLock:
    """Kernel lock, released on process death; no stale-PID guessing."""

    def __init__(self, root):
        self.path = Path(root) / "monitor.lock"
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0)
        if self.path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self.file.close()
            raise AlreadyRunning("Another check/settings operation is running") from e
        return self

    def __exit__(self, *args):
        self.file.close()
