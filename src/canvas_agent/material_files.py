"""Bounded, read-only material parsing and explicit local grants. Never executes material."""

import hashlib
import io
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

from defusedxml import ElementTree

MAX_FILE = 10_000_000
MAX_TEXT = 200_000
MAX_MEMBERS = 100
MAX_EXPANDED = 20_000_000
TEXT_TYPES = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".csv",
    ".html",
    ".css",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".sql",
    ".r",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".ipynb",
    ".tex",
}
SUPPORTED = TEXT_TYPES | {".pdf", ".docx", ".zip"}


class MaterialError(ValueError):
    def __init__(self, code, host=""):
        self.code, self.host = code, host
        super().__init__(code)


def safe_name(name):
    value = re.sub(r"[^\w. -]", "_", Path(str(name).replace("\\", "/")).name, flags=re.UNICODE).strip(" .")[
        :120
    ]
    if not value or value.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        value = "material_" + value
    return value


def _zip_members(archive):
    members = archive.infolist()
    if len(members) > MAX_MEMBERS or sum(m.file_size for m in members) > MAX_EXPANDED:
        raise MaterialError("archive_limits")
    seen = set()
    for member in members:
        name = member.filename.replace("\\", "/")
        parts = PurePosixPath(name)
        if (
            parts.is_absolute()
            or ".." in parts.parts
            or ":" in name
            or "\x00" in name
            or stat.S_ISLNK(member.external_attr >> 16)
            or member.flag_bits & 1
            or member.file_size > MAX_FILE
            or member.file_size / max(member.compress_size, 1) > 200
            or name.casefold() in seen
        ):
            raise MaterialError("unsafe_archive")
        seen.add(name.casefold())
    return members


def parse_material(name, data):
    if len(data) > MAX_FILE:
        raise MaterialError("file_too_large")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        raise MaterialError("unsupported_file_type")
    text, entries, status = "", [], "ok"
    try:
        if suffix in TEXT_TYPES:
            if b"\x00" in data:
                raise MaterialError("binary_text_file")
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("cp1252")
        elif suffix == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise MaterialError("file_type_mismatch")
            from pypdf import PdfReader, apply_configuration

            # Context-local and explicit: never discover/run a PATH decoder, even if installed.
            with apply_configuration(jbig2dec_binary=None, disable_legacy_handling=True):
                reader = PdfReader(io.BytesIO(data), strict=True)
                if reader.is_encrypted or len(reader.pages) > 200:
                    raise MaterialError("pdf_limits_or_encrypted")
                chunks = []
                for page in reader.pages:
                    chunks.append((page.extract_text() or "")[:20000])
                    if sum(map(len, chunks)) > MAX_TEXT:
                        status = "truncated"
                        break
                text = "\n".join(chunks)
            if not text.strip():
                status = "scanned_or_unextractable_pdf"
        else:
            if not data.startswith(b"PK"):
                raise MaterialError("file_type_mismatch")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = _zip_members(archive)
                if suffix == ".docx":
                    if any("vbaproject" in m.filename.casefold() for m in members):
                        raise MaterialError("macro_document_not_supported")
                    document = archive.read("word/document.xml")
                    if len(document) > 5_000_000:
                        raise MaterialError("document_limits")
                    root = ElementTree.fromstring(document)
                    text = "\n".join("".join(p.itertext()) for p in root.iter() if p.tag.endswith("}p"))
                else:
                    for member in members:
                        if member.is_dir():
                            continue
                        item = {"name": member.filename, "bytes": member.file_size, "status": "indexed_only"}
                        if Path(member.filename).suffix.lower() in TEXT_TYPES:
                            parsed = parse_material(member.filename, archive.read(member))
                            item.update(status=parsed["status"], text=parsed["text"])
                        entries.append(item)
                    text = "\n\n".join(f"FILE: {e['name']}\n{e.get('text', '[not parsed]')}" for e in entries)
    except MaterialError:
        raise
    except Exception:
        raise MaterialError("unreadable_material") from None
    if len(text) > MAX_TEXT:
        status = "truncated"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return {
        "name": safe_name(name),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "status": status,
        "text": text[:MAX_TEXT],
        "entries": entries,
    }


def _no_reparse(path):
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part.stat(), "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024
        ):
            raise MaterialError("linked_path_not_authorized")


class LocalAccess:
    def __init__(self):
        self.paths = ()

    def grant(self, paths):
        selected = []
        for value in paths:
            path = Path(value).absolute()
            _no_reparse(path)
            path = path.resolve(strict=True)
            if path.is_dir() and (path == Path(path.anchor) or len(path.parts) < 3):
                raise MaterialError("broad_directory_not_allowed")
            selected.append(path)
        self.paths = tuple(selected)

    def revoke(self):
        self.paths = ()

    def authorized(self, path):
        path = Path(path).absolute()
        _no_reparse(path)
        path = path.resolve(strict=True)
        if not any(path == grant or grant.is_dir() and grant in path.parents for grant in self.paths):
            raise MaterialError("local_access_not_authorized")
        return path

    def read(self, path):
        path = self.authorized(path)
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise MaterialError("file_too_large_or_unavailable")
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE + 1)
        return parse_material(path.name, data) | {"path": str(path)}

    def inventory(self):
        found = []
        for grant in self.paths:
            candidates = []
            if grant.is_file():
                candidates = [grant]
            else:
                for directory, dirs, names in os.walk(grant, followlinks=False):
                    safe_dirs = []
                    for name in dirs:
                        if name in {".git", ".venv", "node_modules", "__pycache__"}:
                            continue
                        try:
                            self.authorized(Path(directory) / name)
                            safe_dirs.append(name)
                        except (OSError, MaterialError):
                            continue
                    dirs[:] = safe_dirs
                    candidates.extend(Path(directory) / name for name in names)
                    if len(candidates) > 10000:
                        raise MaterialError("workspace_inventory_limit")
            for path in candidates:
                if any(p in {".git", ".venv", "node_modules", "__pycache__"} for p in path.parts):
                    continue
                if path.is_file() and path.suffix.lower() in SUPPORTED and not path.name.startswith(".env"):
                    found.append(self.read(path))
                    if len(found) > MAX_MEMBERS:
                        raise MaterialError("workspace_file_limit")
        return found


def download_material(api, file_id, destination, approved_hosts=()):
    metadata, _ = api.get(f"files/{int(file_id)}")
    if not isinstance(metadata, dict) or int(metadata.get("id", 0)) != int(file_id):
        raise MaterialError("invalid_file_metadata")
    if metadata.get("locked_for_user") or metadata.get("size", 0) > MAX_FILE:
        raise MaterialError("file_locked_or_too_large")
    name = safe_name(metadata.get("filename", metadata.get("display_name", "material")))
    if Path(name).suffix.lower() not in SUPPORTED:
        raise MaterialError("unsupported_file_type")
    url = metadata.get("url", "")
    origin = urlsplit(api.base).netloc
    allowed = {origin, *approved_hosts}
    for _ in range(4):
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or (parts.netloc not in allowed and parts.hostname not in approved_hosts)
            or parts.port not in (None, 443)
            or parts.username
            or parts.password
        ):
            raise MaterialError("download_host_not_authorized", parts.hostname or "")
        headers = {"Authorization": f"Bearer {api.token}"} if parts.netloc == origin else {}
        response = api.session.get(url, headers=headers, timeout=(8, 25), allow_redirects=False, stream=True)
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status_code != 200:
                raise MaterialError("download_failed")
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_FILE:
                    raise MaterialError("file_too_large")
            parsed = parse_material(name, bytes(data))
            destination = Path(destination)
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / f"{int(file_id)}-{name}"
            if target.exists():
                if target.read_bytes() != bytes(data):
                    raise MaterialError("file_name_conflict")
            else:
                with target.open("xb") as stream:
                    stream.write(data)
            return parsed | {
                "path": str(target),
                "source_url": f"{api.base}/files/{int(file_id)}",
                "file_id": int(file_id),
            }
        finally:
            response.close()
    raise MaterialError("download_redirect_limit")
