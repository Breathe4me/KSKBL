"""Preserve build-runtime SSL companion policy data without changing its trust decisions."""

import hashlib
import ssl
from pathlib import Path


def ssl_resources(module=ssl):
    constructor = getattr(module.SSLContext.__new__, "__code__", None)
    name = "codex-rejected-cas.pem"
    required = constructor is not None and name in constructor.co_consts
    entries = []
    if required:
        source = Path(module.__file__).resolve().with_name(name)
        data = source.read_bytes()  # fail the build, not the first user's HTTPS connection
        if not data.startswith(b"-----BEGIN TRUSTED CERTIFICATE-----"):
            raise ValueError("Unexpected SSL policy resource format")
        entries.append(
            {
                "source": str(source),
                "destination": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return {"schema": 1, "ssl_companion_required": required, "files": entries}


def ssl_datas():
    return [(row["source"], ".") for row in ssl_resources()["files"]]


def public_ssl_resources():
    manifest = ssl_resources()
    return {
        "schema": manifest["schema"],
        "ssl_companion_required": manifest["ssl_companion_required"],
        "files": [{key: value for key, value in row.items() if key != "source"} for row in manifest["files"]],
    }
