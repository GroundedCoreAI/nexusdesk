"""Handle-based Execution Workdir operations (Phase 4, 08 T5, 03 §4.5).

Every filesystem operation runs component-wise from a verified root handle
with no-follow and exclusive semantics; the "realpath check, then string
open" pattern is deliberately unavailable here (rule 2). Public entry points
take directory fds and policy-validated component tuples, never a
client-supplied path string (rule 1, AC-7). Deletion refuses to follow links,
denies hardlinks/mount points whose ownership cannot be proven, stops on
races, and rechecks ownership before any destructive call is issued (rules
4-5). Failures raise :class:`WorkdirOperationError` with a stable code from
the ``workdir_*`` reason set; codes travel to ``execution_workdirs.last_error_code``
without raw paths or exception text.

This is a synchronous, thread-safe low-level surface (POSIX only); the async
durable lifecycle lives in ``workspace_manager.py``, which runs these calls
off the event loop.
"""

import errno
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import workspace_policy as policy

# Stable error codes (mirrored by the workspace_provider Literal; a pin test
# keeps the two lists equal). None of them carries path or exception text.
WORKDIR_ROOT_INVALID = "workdir_root_invalid"
WORKDIR_PATH_REJECTED = "workdir_path_rejected"
WORKDIR_LINK_DENIED = "workdir_link_denied"
WORKDIR_HARDLINK_DENIED = "workdir_hardlink_denied"
WORKDIR_MOUNT_DENIED = "workdir_mount_denied"
WORKDIR_OWNER_MISMATCH = "workdir_owner_mismatch"
WORKDIR_RACE = "workdir_race"
WORKDIR_UNSUPPORTED_OBJECT = "workdir_unsupported_object"
WORKDIR_SCOPE_MISMATCH = "workdir_scope_mismatch"
WORKDIR_FS_FAILED = "workdir_fs_failed"

_DIR_OPEN = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class WorkdirOperationError(RuntimeError):
    """A fail-closed workdir violation: nothing outside scope was touched.

    ``detail`` is an internal diagnostic label (component name only), never a
    host path or exception text; only ``code`` may reach durable records.
    """

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class WorkdirHandles:
    """Open handles for one Run directory and its containing tenant directory."""

    relative_path: str
    parent_fd: int
    run_fd: int

    def close(self) -> None:
        for fd in (self.run_fd, self.parent_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def _verify_open_dir(fd: int, expected_uid: int | None, code: str, detail: str) -> os.stat_result:
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode):  # pragma: no cover - O_DIRECTORY guards this
        raise WorkdirOperationError(code, detail)
    if st.st_uid != (os.geteuid() if expected_uid is None else expected_uid):
        raise WorkdirOperationError(WORKDIR_OWNER_MISMATCH, detail)
    return st


def _open_dir_no_follow(parent_fd: int, name: str, *, missing_code: str = WORKDIR_RACE) -> int:
    """Open one component with O_NOFOLLOW: a symlink is never traversed.

    Darwin reports ``ENOTDIR`` (and Linux ``ELOOP``) for a symlink under
    ``O_DIRECTORY|O_NOFOLLOW``, so the classification consults ``lstat`` of
    the name itself instead of trusting one errno convention.
    """
    try:
        fd = os.open(name, _DIR_OPEN, dir_fd=parent_fd)
    except FileNotFoundError:
        raise WorkdirOperationError(missing_code, name) from None
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            try:
                target_is_link = stat.S_ISLNK(os.lstat(name, dir_fd=parent_fd).st_mode)
            except OSError:
                target_is_link = exc.errno == errno.ELOOP
            if target_is_link:
                raise WorkdirOperationError(WORKDIR_LINK_DENIED, name) from None
            raise WorkdirOperationError(WORKDIR_UNSUPPORTED_OBJECT, name) from None
        raise WorkdirOperationError(WORKDIR_FS_FAILED, name) from None
    return fd


def _mkdir_verified(parent_fd: int, name: str, mode: int, expected_uid: int | None) -> int:
    """Create one directory component, then verify it through a no-follow open.

    ``FileExistsError`` is not trusted: the entry may be a symlink planted by a
    race, so the subsequent ``O_NOFOLLOW`` open is what decides, not the mkdir.
    """
    try:
        os.mkdir(name, mode, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except PermissionError:
        raise WorkdirOperationError(WORKDIR_FS_FAILED, name) from None
    fd = _open_dir_no_follow(parent_fd, name)
    _verify_open_dir(fd, expected_uid, WORKDIR_UNSUPPORTED_OBJECT, name)
    os.fchmod(fd, mode)  # defeat the process umask; the mode is the promise
    return fd


def ensure_execution_root(root: Path) -> int:
    """Create/verify the platform execution root and return its directory fd.

    Startup verification (03 §4.5): a symlinked root is rejected, the owner
    must be the effective platform user, and the mode must be exactly 0700.
    """
    try:
        os.mkdir(root, policy.DIR_MODE)
    except FileExistsError:
        pass
    except OSError:
        # A missing parent or an occupied name is decided by the verified
        # open below, which fails closed instead of trusting mkdir errors.
        pass
    try:
        fd = os.open(str(root), _DIR_OPEN)
    except FileNotFoundError:
        raise WorkdirOperationError(WORKDIR_ROOT_INVALID, "missing root") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise WorkdirOperationError(WORKDIR_ROOT_INVALID, "symlinked root") from None
        raise WorkdirOperationError(WORKDIR_ROOT_INVALID, "unopenable root") from None
    st = _verify_open_dir(fd, None, WORKDIR_ROOT_INVALID, "root")
    if stat.S_IMODE(st.st_mode) != policy.REQUIRED_DIR_MODE:
        raise WorkdirOperationError(WORKDIR_ROOT_INVALID, "root mode is not 0700")
    return fd


def create_workdir(
    root_fd: int, relative_path: str, *, expected_uid: int | None = None
) -> WorkdirHandles:
    """Create (or re-open) one Run directory tree for a validated relative path.

    Idempotent by construction: existing components are verified through
    no-follow opens rather than trusted, so a prior crash inside this function
    converges on the same state on retry, and a replaced component is denied
    instead of adopted.
    """
    try:
        components = policy.normalize_relative_path(relative_path)
    except policy.WorkspacePathError:
        raise WorkdirOperationError(WORKDIR_PATH_REJECTED, "rejected relative path") from None
    parent_fd = root_fd
    for component in components[:-1]:
        parent_fd = _mkdir_verified(parent_fd, component, policy.DIR_MODE, expected_uid)
    run_fd = _mkdir_verified(parent_fd, components[-1], policy.DIR_MODE, expected_uid)
    return WorkdirHandles(relative_path=relative_path, parent_fd=parent_fd, run_fd=run_fd)


def open_workdir(
    root_fd: int, relative_path: str, *, expected_uid: int | None = None
) -> WorkdirHandles:
    """Re-open an existing Run tree from the root handle; creates nothing."""
    try:
        components = policy.normalize_relative_path(relative_path)
    except policy.WorkspacePathError:
        raise WorkdirOperationError(WORKDIR_PATH_REJECTED, "rejected relative path") from None
    parent_fd = root_fd
    for component in components[:-1]:
        parent_fd = _open_dir_no_follow(parent_fd, component)
        _verify_open_dir(parent_fd, expected_uid, WORKDIR_UNSUPPORTED_OBJECT, component)
    run_fd = _open_dir_no_follow(parent_fd, components[-1])
    _verify_open_dir(run_fd, expected_uid, WORKDIR_UNSUPPORTED_OBJECT, components[-1])
    return WorkdirHandles(relative_path=relative_path, parent_fd=parent_fd, run_fd=run_fd)


def ensure_layout(run_fd: int, *, expected_uid: int | None = None) -> tuple[str, ...]:
    """Create the fixed ``workdir/temp/logs`` layout at 0700 under one Run dir."""
    for name in policy.expected_layout_dirs():
        os.close(_mkdir_verified(run_fd, name, policy.DIR_MODE, expected_uid))
    return policy.expected_layout_dirs()


def verify_workdir_identity(
    run_fd: int, relative_path: str, *, expected_uid: int | None = None
) -> None:
    """Ownership recheck (rule 3/5) before any destructive use of a Run dir."""
    try:
        components = policy.normalize_relative_path(relative_path)
    except policy.WorkspacePathError:
        raise WorkdirOperationError(WORKDIR_SCOPE_MISMATCH, "record path is not valid") from None
    if not policy.path_is_within_recorded_scope(components):
        raise WorkdirOperationError(
            WORKDIR_SCOPE_MISMATCH, "refusing to address root or tenant level"
        )
    st = _verify_open_dir(run_fd, expected_uid, WORKDIR_OWNER_MISMATCH, components[-1])
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise WorkdirOperationError(
            WORKDIR_OWNER_MISMATCH, "run directory is group/world accessible"
        )


def create_platform_file(dir_fd: int, name: str) -> int:
    """Open a platform-owned file inside a workdir handle at exactly 0600.

    No-follow: a pre-planted symlink under the name is denied rather than
    written through (rule 2/4). The caller owns the returned fd.
    """
    try:
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            policy.FILE_MODE,
            dir_fd=dir_fd,
        )
    except OSError as exc:
        try:
            target_is_link = stat.S_ISLNK(os.lstat(name, dir_fd=dir_fd).st_mode)
        except OSError:
            target_is_link = exc.errno == errno.ELOOP
        if target_is_link:
            raise WorkdirOperationError(WORKDIR_LINK_DENIED, name) from None
        raise WorkdirOperationError(WORKDIR_FS_FAILED, name) from None
    os.fchmod(fd, policy.FILE_MODE)
    return fd


@dataclass(frozen=True)
class WorkdirUsage:
    total_bytes: int
    file_count: int


def account_usage(
    run_fd: int,
    *,
    mount_probe: Callable[[int, int], bool] = policy.default_mount_probe,
) -> WorkdirUsage:
    """Recursive disk accounting through no-follow handles (03 §4.5 rule 4).

    Symlinks, unsupported object types and mount points abort the accounting
    instead of silently skewing the quota picture (T12 consumes this for
    enforcement). Hardlinks are counted but not read, which cannot affect an
    external file.
    """
    return _account_recursive(run_fd, mount_probe)


def _account_recursive(dir_fd: int, mount_probe) -> WorkdirUsage:
    own_dev = os.fstat(dir_fd).st_dev
    total = 0
    count = 0
    for name in os.listdir(dir_fd):
        st = os.lstat(name, dir_fd=dir_fd)
        if stat.S_ISLNK(st.st_mode):
            raise WorkdirOperationError(WORKDIR_LINK_DENIED, name)
        if policy.is_unsupported_object_type(st.st_mode):
            raise WorkdirOperationError(WORKDIR_UNSUPPORTED_OBJECT, name)
        if stat.S_ISDIR(st.st_mode):
            if mount_probe(st.st_dev, own_dev):
                raise WorkdirOperationError(WORKDIR_MOUNT_DENIED, name)
            child_fd = _open_dir_no_follow(dir_fd, name)
            try:
                usage = _account_recursive(child_fd, mount_probe)
            finally:
                os.close(child_fd)
            total += usage.total_bytes
            count += usage.file_count
        else:
            total += st.st_size
            count += 1
    return WorkdirUsage(total_bytes=total, file_count=count)


def remove_workdir(
    root_fd: int,
    relative_path: str,
    *,
    expected_uid: int | None = None,
    mount_probe: Callable[[int, int], bool] = policy.default_mount_probe,
) -> bool:
    """Delete exactly the recorded Run directory tree; idempotent.

    Returns True when a tree was removed and False when it was already absent
    (crash-retry path). Anything outside the recorded directory can never be
    reached: the walk starts from the verified root handle, the scope guard
    refuses depths that would address the root or a tenant parent, every
    destructive call is made through an open directory fd with a name that was
    just verified, and an unprovable entry aborts the whole removal with a
    stable code instead of a partial "success".
    """
    try:
        components = policy.normalize_relative_path(relative_path)
    except policy.WorkspacePathError:
        raise WorkdirOperationError(WORKDIR_PATH_REJECTED, "rejected relative path") from None
    if not policy.path_is_within_recorded_scope(components):
        raise WorkdirOperationError(
            WORKDIR_SCOPE_MISMATCH, "refusing to address root or tenant level"
        )
    parent_fd = root_fd
    for component in components[:-1]:
        try:
            parent_fd = _open_dir_no_follow(parent_fd, component)
        except WorkdirOperationError as exc:
            if exc.code == WORKDIR_RACE:
                return False  # prefix never existed: prepare failed early, nothing to remove
            raise
        _verify_open_dir(parent_fd, expected_uid, WORKDIR_OWNER_MISMATCH, component)
    try:
        run_fd = _open_dir_no_follow(parent_fd, components[-1])
    except WorkdirOperationError as exc:
        if exc.code == WORKDIR_RACE:
            return False  # already absent: cleanup is idempotent
        raise
    try:
        _verify_open_dir(run_fd, expected_uid, WORKDIR_OWNER_MISMATCH, components[-1])
        _remove_tree(run_fd, expected_uid, mount_probe)
    finally:
        os.close(run_fd)
    try:
        os.rmdir(components[-1], dir_fd=parent_fd)
    except FileNotFoundError:
        raise WorkdirOperationError(WORKDIR_RACE, components[-1]) from None
    return True


def _remove_tree(dir_fd: int, expected_uid: int | None, mount_probe) -> None:
    """Depth-first no-follow removal of one directory's contents (rule 4/5)."""
    own_dev = os.fstat(dir_fd).st_dev
    if expected_uid is not None and os.fstat(dir_fd).st_uid != expected_uid:
        raise WorkdirOperationError(WORKDIR_OWNER_MISMATCH, "directory owner changed")
    for name in os.listdir(dir_fd):
        try:
            st = os.lstat(name, dir_fd=dir_fd)
        except FileNotFoundError:
            raise WorkdirOperationError(WORKDIR_RACE, name) from None
        if stat.S_ISLNK(st.st_mode):
            # Removing the link itself never touches the target; a link owned
            # by someone else means the scope is not provable, so stop.
            if st.st_uid != (os.geteuid() if expected_uid is None else expected_uid):
                raise WorkdirOperationError(WORKDIR_OWNER_MISMATCH, name)
            try:
                os.unlink(name, dir_fd=dir_fd)
            except FileNotFoundError:
                raise WorkdirOperationError(WORKDIR_RACE, name) from None
            continue
        if policy.is_unsupported_object_type(st.st_mode):
            raise WorkdirOperationError(WORKDIR_UNSUPPORTED_OBJECT, name)
        if stat.S_ISDIR(st.st_mode):
            if mount_probe(st.st_dev, own_dev):
                raise WorkdirOperationError(WORKDIR_MOUNT_DENIED, name)
            child_fd = _open_dir_no_follow(dir_fd, name)  # ELOOP -> link denied
            try:
                child_st = os.fstat(child_fd)
                if child_st.st_uid != (os.geteuid() if expected_uid is None else expected_uid):
                    raise WorkdirOperationError(WORKDIR_OWNER_MISMATCH, name)
                _remove_tree(child_fd, expected_uid, mount_probe)
            finally:
                os.close(child_fd)
            try:
                os.rmdir(name, dir_fd=dir_fd)
            except FileNotFoundError:
                raise WorkdirOperationError(WORKDIR_RACE, name) from None
            continue
        # Regular file: ownership and single-link scope are rechecked on this
        # very entry immediately before the unlink on the same fd+name.
        if st.st_uid != (os.geteuid() if expected_uid is None else expected_uid):
            raise WorkdirOperationError(WORKDIR_OWNER_MISMATCH, name)
        if policy.is_hardlink_of_unknown_owner(st.st_nlink):
            raise WorkdirOperationError(WORKDIR_HARDLINK_DENIED, name)
        try:
            os.unlink(name, dir_fd=dir_fd)
        except FileNotFoundError:
            raise WorkdirOperationError(WORKDIR_RACE, name) from None
