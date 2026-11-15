"""Relative-path and link policy for Execution Workdirs (Phase 4, 08 T5).

Pure functions implementing rules 1 and 3-5 of 03 §4.5 as decision logic; the
filesystem mechanics live in ``execution_workdir.py`` and the durable scope in
``workspace_manager.py``. The policy accepts only platform-generated relative
paths: there is deliberately no API here that takes a client-supplied host
path (02 FR-6/AC-7), and every rejection happens before any resource is
touched (fail closed).
"""

import hashlib
import re
import stat
from collections.abc import Sequence
from typing import Final

# Layout budget: the contract column (ExecutionRequest.execution_workdir) caps
# at 200 chars, so the policy refuses anything that could not round-trip there.
MAX_PATH_LENGTH: Final = 200
MAX_DEPTH: Final = 8
MAX_COMPONENT_LENGTH: Final = 128

# Platform-generated names are lowercase: tenant digests (hex) and Run UUIDs.
# A component must start and end alphanumeric (no "." / ".." / trailing-dot or
# trailing-separator tricks) and percent signs are banned entirely because an
# encoded separator or dot is the documented bypass attempt (rule 1).
_COMPONENT_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")

DIR_MODE: Final = 0o700
FILE_MODE: Final = 0o600

# Ownership/mode bits the execution root must present at startup verification
# (03 §4.5: owner, type, permissions; a symlinked root is rejected elsewhere).
REQUIRED_DIR_MODE: Final = 0o700


class WorkspacePathError(ValueError):
    """A relative path violated policy rule 1 and was rejected untouched."""


def is_safe_relative_path(value: str) -> bool:
    """Decision half of :func:`normalize_relative_path` for callers that branch."""
    try:
        normalize_relative_path(value)
    except WorkspacePathError:
        return False
    return True


def normalize_relative_path(value: str) -> tuple[str, ...]:
    """Validate and split one platform relative path into components (rule 1).

    Rejects absolute paths, NUL, backslashes, drive letters, empty/repeated
    separators, trailing separators, ``.``/``..`` segments, any percent-encoded
    bypass attempt, uppercase or otherwise foreign characters, excessive total
    or per-component length, and excessive depth. Returns the component tuple
    on success; raises :class:`WorkspacePathError` before touching anything.
    """
    if not isinstance(value, str):
        raise WorkspacePathError("workdir paths must be strings")
    if len(value) > MAX_PATH_LENGTH:
        raise WorkspacePathError("workdir path exceeds the length bound")
    if "\x00" in value or "\\" in value:
        raise WorkspacePathError("workdir path contains a forbidden character")
    if value.startswith(("/", "//")) or ":" in value:
        raise WorkspacePathError("workdir path must be platform-relative")
    if "%" in value:
        raise WorkspacePathError("workdir path contains an encoded separator attempt")
    if value == "" or value.endswith("/"):
        raise WorkspacePathError("workdir path must be a normalized relative path")
    components = value.split("/")
    if len(components) > MAX_DEPTH:
        raise WorkspacePathError("workdir path exceeds the depth bound")
    for component in components:
        if component in ("", ".", ".."):
            raise WorkspacePathError("workdir path contains a non-normalized segment")
        if len(component) > MAX_COMPONENT_LENGTH:
            raise WorkspacePathError("workdir path component exceeds the length bound")
        if not _COMPONENT_RE.fullmatch(component):
            raise WorkspacePathError("workdir path component uses forbidden characters")
    return tuple(components)


def is_link_like(mode: int) -> bool:
    """True for symlinks: the deny-by-default object class (rule 4)."""
    return bool(stat.S_ISLNK(mode))


def is_unsupported_object_type(mode: int) -> bool:
    """FIFOs, sockets and devices have no provable delete/read semantics."""
    return not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode))


def is_hardlink_of_unknown_owner(link_count: int) -> bool:
    """Hardlinks above one name deny cleanup unless ownership is provable (rule 4).

    One recorded link count means the only name to the inode is inside the
    audited Workdir; anything above that could share an external inode and the
    delete scope is no longer provable, so cleanup stops with an alert instead
    of touching it (02 FR-6 failure row).
    """
    return link_count > 1


def default_mount_probe(child_dev: int, parent_dev: int) -> bool:
    """st_dev comparison: crossing devices means a mount point sits inside.

    Injectable by design: quota/mount live experiments are Linux-side and
    pending_env (08 R-3), so tests substitute this probe while production
    keeps the device comparison, which fails closed in both directions.
    """
    return child_dev != parent_dev


def expected_layout_dirs() -> tuple[str, ...]:
    """The fixed ``workdir/temp/logs`` layout under one Run directory."""
    return ("workdir", "temp", "logs")


def tenant_digest(tenant_id: str) -> str:
    """Server-generated tenant directory name: sha256 hex prefix, not a display name.

    Display names are untrusted (03 §4.5); only this digest of the trusted
    tenant id is allowed to enter a path, and it always matches the component
    grammar above.
    """
    return hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]


def build_relative_path(tenant_id: str, run_id: str) -> str:
    """Compose the canonical ``<tenant-digest>/<run-uuid>`` relative path.

    The single generator of Workdir paths; callers pass trusted platform ids
    only, and the result is re-validated through :func:`normalize_relative_path`
    so a malformed UUID or hostile tenant string can never produce a usable
    path.
    """
    path = f"{tenant_digest(tenant_id)}/{run_id}"
    normalize_relative_path(path)
    return path


def path_is_within_recorded_scope(components: Sequence[str]) -> bool:
    """Cleanup scope guard (rule 5): only a Run directory at depth >= 2 is deletable.

    The root and tenant parent never qualify, so one Execution can never be
    pointed at a recursive delete above its own directory.
    """
    return len(components) >= 2
