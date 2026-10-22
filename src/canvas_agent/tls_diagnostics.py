"""TLS-only safe metadata: paths/codes/frames, never request data or exception messages."""

import hashlib
import os
import ssl
import sys
import traceback
from pathlib import Path

import certifi


def local_path(value):
    if value is None:
        return None
    value = str(value)
    if len(value) > 4096 or "://" in value or any(ord(c) < 32 for c in value):
        return "<nonlocal_or_invalid_path>"
    return value


def snapshot():
    paths = ssl.get_default_verify_paths()._asdict()
    policy = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
    bundle = Path(certifi.where())

    def file_record(path):
        return {
            "path": local_path(path),
            "exists": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else None,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        }

    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "openssl": ssl.OPENSSL_VERSION,
        "ssl_module": local_path(ssl.__file__),
        "create_default_context_inputs": {"cafile": None, "capath": None, "cadata": None},
        "default_verify_paths": {key: local_path(value) for key, value in paths.items()},
        "certifi": file_record(bundle),
        "ssl_companion_policy": file_record(policy),
        "environment_set": {
            key: key in os.environ
            for key in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
        },
    }


def exception_chain(error):
    rows, seen = [], set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        rows.append(
            {
                "type": type(error).__name__,
                "errno": getattr(error, "errno", None),
                "winerror": getattr(error, "winerror", None),
                "filename": local_path(getattr(error, "filename", None)),
                "filename2": local_path(getattr(error, "filename2", None)),
                "frames": [
                    {"file": Path(f.filename).name, "function": f.name, "line": f.lineno}
                    for f in traceback.extract_tb(error.__traceback__)
                ],
            }
        )
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return rows
