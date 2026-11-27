"""Skill package ingestion: untrusted archive in, verified manifest out.

A Skill package is a zip that somebody else authored. Nothing in this module
executes, imports, or writes to disk -- the archive is decoded in memory, every
entry is checked against a fixed policy, and the result is an immutable
manifest the caller stores beside the object. Keeping ingestion free of side
effects is what lets the same code serve a direct upload today and a
whitelisted remote download later.

The policy is deliberately aspirational rather than clever: reject anything
that is not a plain regular file with a normalised relative path, and refuse
the whole package when any single entry fails. Partial acceptance would mean
shipping an archive whose contents differ from its manifest.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml

PACKAGE_SCHEMA = "skill-package/v1"

# Hard ceilings. ``MAX_UNCOMPRESSED_BYTES`` is intentionally the tighter of the
# two: it matches the sandbox workdir quota, so a package that passes ingestion
# can still be unpacked inside a run without hitting the limit mid-execution.
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ENTRIES = 200

# Ratio guarding only kicks in above this size; small files compress absurdly
# well by nature and would otherwise trip the check on legitimate prose.
RATIO_GUARD_FLOOR = 1024 * 1024
MAX_COMPRESSION_RATIO = 100

SKILL_DOCUMENT = "SKILL.md"

# Extensions we never accept, even inside a package. Scripts are *not* here:
# they are the point of an executable package, they just get flagged.
FORBIDDEN_SUFFIXES: frozenset[str] = frozenset(
    {
        ".exe",
        ".dll",
        ".dylib",
        ".so",
        ".msi",
        ".com",
        ".scr",
        ".bat",
        ".cmd",
        ".ps1",
        ".vbs",
        ".jar",
        ".class",
        ".pyc",
        ".pyd",
    }
)

NESTED_ARCHIVE_SUFFIXES: frozenset[str] = frozenset(
    {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".whl"}
)

SCRIPT_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".lua"}
)

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class PackageRejected(Exception):
    """A package that cannot be stored. ``code`` is stable and machine facing."""

    def __init__(self, code: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class PackageFile:
    path: str
    size: int
    sha256: str
    executable: bool

    def payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "executable": self.executable,
        }


@dataclass(frozen=True)
class InspectedPackage:
    """Everything the platform needs to know about an archive it just read."""

    digest: str
    size_bytes: int
    files: tuple[PackageFile, ...]
    skill_name: str
    skill_description: str
    frontmatter: dict[str, Any]
    body: str
    entrypoint: str | None
    has_scripts: bool

    @property
    def file_count(self) -> int:
        return len(self.files)

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": PACKAGE_SCHEMA,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "files": [item.payload() for item in self.files],
            "entrypoint": self.entrypoint,
            "has_scripts": self.has_scripts,
            "skill": {
                "name": self.skill_name,
                "description": self.skill_description,
                "license": _text(self.frontmatter.get("license")),
                "allowed_tools": _string_list(self.frontmatter.get("allowed-tools")),
            },
        }


def inspect_package(content: bytes) -> InspectedPackage:
    """Validate an archive and describe it. Raises :class:`PackageRejected`."""

    if not content:
        raise PackageRejected("skill_package_empty", 422)
    if len(content) > MAX_ARCHIVE_BYTES:
        raise PackageRejected("skill_package_too_large", 413)
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise PackageRejected("skill_package_unsupported", 415)

    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise PackageRejected("skill_package_unsupported", 415) from None

    with archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if not entries:
            raise PackageRejected("skill_package_empty", 422)
        if len(entries) > MAX_ENTRIES:
            raise PackageRejected("skill_package_too_many_files", 413)

        normalised = [(info, _normalise_name(info.filename)) for info in entries]
        strip = _common_prefix([name for _, name in normalised])

        files: list[PackageFile] = []
        bodies: dict[str, bytes] = {}
        total = 0
        for info, name in normalised:
            path = name[len(strip) :] if strip else name
            if not path:
                continue
            _reject_special(info, path)
            if info.file_size > MAX_FILE_BYTES:
                raise PackageRejected("skill_package_file_too_large", 413)
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise PackageRejected("skill_package_too_large", 413)
            if (
                info.file_size > RATIO_GUARD_FLOOR
                and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO
            ):
                raise PackageRejected("skill_package_compression_ratio", 413)

            data = _read_entry(archive, info)
            # The central directory can lie about sizes; trust the bytes.
            if len(data) != info.file_size:
                raise PackageRejected("skill_package_corrupt", 422)
            bodies[path] = data
            files.append(
                PackageFile(
                    path=path,
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    executable=_suffix(path) in SCRIPT_SUFFIXES,
                )
            )

        document = bodies.get(SKILL_DOCUMENT)
        if document is None:
            raise PackageRejected("skill_package_missing_manifest", 422)

        frontmatter, body = _split_document(document)
        name = _text(frontmatter.get("name")) or _stem(strip or files[0].path)
        description = _text(frontmatter.get("description")) or _first_line(body)
        entrypoint = _entrypoint(frontmatter, files)
        has_scripts = any(item.executable for item in files)

        return InspectedPackage(
            digest=digest,
            size_bytes=len(content),
            files=tuple(files),
            skill_name=name,
            skill_description=description,
            frontmatter=frontmatter,
            body=body,
            entrypoint=entrypoint,
            has_scripts=has_scripts,
        )


def _normalise_name(raw: str) -> str:
    """Return a safe relative posix path or reject the entry."""

    if not raw or "\x00" in raw:
        raise PackageRejected("skill_package_invalid_path", 422)
    if "\\" in raw:
        raise PackageRejected("skill_package_invalid_path", 422)
    if raw.startswith("/") or _DRIVE_PREFIX.match(raw):
        raise PackageRejected("skill_package_path_traversal", 422)
    parts = [part for part in raw.split("/") if part]
    if not parts:
        raise PackageRejected("skill_package_invalid_path", 422)
    for part in parts:
        if part in (".", ".."):
            raise PackageRejected("skill_package_path_traversal", 422)
    return str(PurePosixPath(*parts))


def _reject_special(info: zipfile.ZipInfo, path: str) -> None:
    mode = info.external_attr >> 16
    if mode & 0o170000 == 0o120000:
        raise PackageRejected("skill_package_symlink", 422)
    suffix = _suffix(path)
    if suffix in FORBIDDEN_SUFFIXES:
        raise PackageRejected("skill_package_executable_payload", 422)
    if suffix in NESTED_ARCHIVE_SUFFIXES:
        raise PackageRejected("skill_package_nested_archive", 422)


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    try:
        return archive.read(info)
    except (RuntimeError, zipfile.BadZipFile) as exc:
        # Encrypted or malformed entries land here; neither is acceptable.
        raise PackageRejected("skill_package_corrupt", 422) from exc


def _common_prefix(paths: list[str]) -> str:
    """Strip a single wrapping directory, the usual shape of a zipped folder.

    Only applied when every entry sits under the same top level *and* the
    document is not already at the root, so a package that happens to name its
    folder ``SKILL.md`` is not silently mangled.
    """

    if not paths or SKILL_DOCUMENT in paths:
        return ""
    firsts = {path.split("/", 1)[0] for path in paths}
    if len(firsts) != 1:
        return ""
    prefix = firsts.pop()
    if any("/" not in path for path in paths):
        return ""
    return prefix + "/"


def _split_document(document: bytes) -> tuple[dict[str, Any], str]:
    """Parse the optional YAML frontmatter and return (meta, markdown body)."""

    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError:
        raise PackageRejected("skill_package_manifest_encoding", 422) from None
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text.strip()

    lines = text.splitlines()
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            closing = index
            break
    if closing is None:
        return {}, text.strip()

    raw = "\n".join(lines[1:closing])
    try:
        parsed = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError:
        raise PackageRejected("skill_package_manifest_invalid", 422) from None
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise PackageRejected("skill_package_manifest_invalid", 422)
    return parsed, "\n".join(lines[closing + 1 :]).strip()


def _entrypoint(frontmatter: dict[str, Any], files: tuple[PackageFile, ...]) -> str | None:
    declared = _text(frontmatter.get("entrypoint"))
    if not declared:
        metadata = frontmatter.get("metadata")
        if isinstance(metadata, dict):
            declared = _text(metadata.get("entrypoint"))
    if declared:
        cleaned = _normalise_name(declared)
        known = {item.path for item in files}
        return cleaned if cleaned in known else None
    if any(item.path == "scripts/main.py" for item in files):
        return "scripts/main.py"
    return None


def _suffix(path: str) -> str:
    lowered = path.lower()
    dot = lowered.rfind(".")
    if dot <= lowered.rfind("/"):
        return ""
    return lowered[dot:]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_line(body: str) -> str:
    for line in body.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:200]
    return ""


def _stem(path: str) -> str:
    top = path.split("/", 1)[0]
    stem = PurePosixPath(top).stem.replace("_", " ").replace("-", " ").strip()
    if not stem or stem.lower() == "skill":
        return "Imported Skill"
    return stem


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


__all__ = [
    "FORBIDDEN_SUFFIXES",
    "MAX_ARCHIVE_BYTES",
    "MAX_ENTRIES",
    "MAX_UNCOMPRESSED_BYTES",
    "PACKAGE_SCHEMA",
    "InspectedPackage",
    "PackageFile",
    "PackageRejected",
    "inspect_package",
]
