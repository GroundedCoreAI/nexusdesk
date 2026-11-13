"""Phase 4 workspace tests: path policy, safe handles, durable Workdir lifecycle.

Covers 08 T5 (P4-UT-10/12/13/14 on this APFS host, measurable per 08 R-3) and
T6 (P4-UT-11 plus the postgres P4-IT-13/14/15 sections on the dedicated
pgvector container via TEST_DATABASE_URL). Live mount-point experiments remain
pending_env and are exercised here only through the substituted probe.
"""

import asyncio
import os
import stat
import typing
import uuid
from pathlib import Path

import asyncpg
import pytest
from pydantic import ValidationError
from test_ticket_migrations import migrate

from agent_platform.core_platform.agent_execution.workspace import (
    execution_workdir as ops,
)
from agent_platform.core_platform.agent_execution.workspace import (
    workspace_policy as policy,
)
from agent_platform.core_platform.agent_execution.workspace.execution_workdir import (
    WorkdirOperationError,
)
from agent_platform.core_platform.agent_execution.workspace.workspace_manager import (
    ExecutionWorkspaceManager,
    WorkspaceStateError,
)
from agent_platform.core_platform.agent_execution.workspace.workspace_provider import (
    TERMINAL_WORKDIR_STATES,
    WORKDIR_STATE_TRANSITIONS,
    WorkdirErrorCode,
    WorkdirRecord,
    WorkspaceProvider,
)

# ---------------------------------------------------------------------------
# T5: relative-path normalization and rejection (P4-UT-10)
# ---------------------------------------------------------------------------

RUN = str(uuid.uuid4())
DIGEST = "0123456789abcdef"


@pytest.mark.parametrize(
    "value",
    [
        f"{DIGEST}/{RUN}",
        "a/b",
        "a.b/c_d-e/f",
        "x" * 99 + "/" + "y" * 100,  # exactly at the total bound
        "a/" * 7 + "b",  # exactly MAX_DEPTH
    ],
)
def test_policy_accepts_platform_generated_relative_paths(value):
    assert policy.normalize_relative_path(value) == tuple(value.split("/"))
    assert policy.is_safe_relative_path(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/",
        "//a",
        "/etc/passwd",
        "C:/Windows",
        "\\\\server\\share",
        ".",
        "..",
        "a/..",
        "../a",
        "a/../b",
        "a/./b",
        "./a",
        "a/",
        "a//b",
        "a/b/",
        "a\x00b",
        "a\\b",
        "%2e%2e%2fetc",
        "a/%2f/etc",
        "a/%2F",
        "a/%2e",
        "AA11/" + RUN,  # uppercase: digests and UUIDs are lowercase
        "-lead/a",
        ".hidden/a",
        "trail-./a",
        "x" * 201,
        DIGEST + "/" + "y" * 129,
        "a/" * 8 + "b",  # MAX_DEPTH + 1
        "а/б",  # non-ASCII lookalikes never round-trip platform ids
        "a\nb",
        "a b",
        "~/a",
        "a/~/b",
    ],
)
def test_policy_rejects_every_untrusted_path_shape(value):
    with pytest.raises(policy.WorkspacePathError):
        policy.normalize_relative_path(value)
    assert not policy.is_safe_relative_path(value)


def test_tenant_digest_and_generated_path_are_never_raw_display_names():
    hostile = "Tenant Display/../Name"
    digest = policy.tenant_digest(hostile)
    assert len(digest) == 16
    assert digest == policy.tenant_digest(hostile)
    path = policy.build_relative_path(hostile, RUN)
    assert "Tenant" not in path
    assert policy.normalize_relative_path(path) == (digest, RUN)


def test_policy_decision_helpers():
    assert not policy.path_is_within_recorded_scope((RUN,))
    assert policy.path_is_within_recorded_scope((DIGEST, RUN))
    assert policy.is_hardlink_of_unknown_owner(2)
    assert not policy.is_hardlink_of_unknown_owner(1)
    assert policy.default_mount_probe(1, 2)
    assert not policy.default_mount_probe(1, 1)
    assert policy.expected_layout_dirs() == ("workdir", "temp", "logs")


# ---------------------------------------------------------------------------
# T5: handle-based operations on the real (APFS) filesystem
# ---------------------------------------------------------------------------


@pytest.fixture
def root(tmp_path) -> Path:
    execution_root = tmp_path / "execution"
    execution_root.mkdir(mode=0o700)
    return execution_root


def _run_dir(root: Path, relative_path: str) -> Path:
    return root / relative_path


def _make_handles(root_fd: int, relative_path: str):
    handles = ops.create_workdir(root_fd, relative_path)
    ops.ensure_layout(handles.run_fd)
    return handles


def _plant_file(directory: Path, name: str, payload: bytes = b"x") -> Path:
    target = directory / name
    target.write_bytes(payload)
    return target


def test_execution_root_verification_rejects_symlink_and_loose_mode(tmp_path, root):
    os.close(ops.ensure_execution_root(root))

    symlinked = tmp_path / "via-symlink"
    symlinked.symlink_to(root, target_is_directory=True)
    with pytest.raises(WorkdirOperationError) as excinfo:
        ops.ensure_execution_root(symlinked)
    assert excinfo.value.code == ops.WORKDIR_ROOT_INVALID

    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    with pytest.raises(WorkdirOperationError) as excinfo:
        ops.ensure_execution_root(loose)
    assert excinfo.value.code == ops.WORKDIR_ROOT_INVALID

    missing_parent = tmp_path / "gone" / "execution"
    with pytest.raises(WorkdirOperationError) as excinfo:
        ops.ensure_execution_root(missing_parent)
    assert excinfo.value.code == ops.WORKDIR_ROOT_INVALID


def test_created_layout_is_0700_directories_under_a_0700_root(root):
    relative_path = policy.build_relative_path("tenant-a", RUN)
    root_fd = ops.ensure_execution_root(root)
    try:
        handles = _make_handles(root_fd, relative_path)
        handles.close()
        # Idempotent re-entry after a simulated crash converges, not duplicates.
        again = _make_handles(root_fd, relative_path)
        again.close()
    finally:
        os.close(root_fd)

    run_dir = _run_dir(root, relative_path)
    for directory in [
        root,
        run_dir.parent,
        run_dir,
        *[run_dir / name for name in policy.expected_layout_dirs()],
    ]:
        assert stat.S_IMODE(directory.stat().st_mode) == policy.DIR_MODE


def test_platform_files_are_created_at_0600_no_follow(root):
    relative_path = policy.build_relative_path("tenant-a", RUN)
    root_fd = ops.ensure_execution_root(root)
    external = _plant_file(root.parent, "external-target", b"do not touch")
    handles = _make_handles(root_fd, relative_path)
    logs_fd = os.open("logs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=handles.run_fd)
    try:
        fd = ops.create_platform_file(logs_fd, "engine.out")
        os.write(fd, b"hello")
        os.close(fd)
        second = ops.create_platform_file(logs_fd, "engine.out")
        os.write(second, b" more")
        os.close(second)

        os.symlink(str(external), "trap", dir_fd=logs_fd)
        with pytest.raises(WorkdirOperationError) as excinfo:
            ops.create_platform_file(logs_fd, "trap")
        assert excinfo.value.code == ops.WORKDIR_LINK_DENIED
    finally:
        os.close(logs_fd)
        handles.close()
        os.close(root_fd)

    created = _run_dir(root, relative_path) / "logs" / "engine.out"
    assert stat.S_IMODE(created.stat().st_mode) == policy.FILE_MODE
    assert created.read_bytes() == b"hello more"
    assert external.read_bytes() == b"do not touch"


def test_component_replace_sentinel_denies_symlinked_intermediate(tmp_path, root):
    external = tmp_path / "external"
    external.mkdir()
    _plant_file(external, "precious", b"keep")
    relative_path = policy.build_relative_path("tenant-a", RUN)
    run_path = _run_dir(root, relative_path)
    run_path.mkdir(parents=True)

    # Check-then-replace: the tenant directory is swapped for a symlink that
    # points elsewhere; every entry point must deny instead of traversing.
    tenant_dir = run_path.parent
    saved = tenant_dir.rename(tmp_path / "tenant-real")
    tenant_dir.symlink_to(saved, target_is_directory=True)

    root_fd = ops.ensure_execution_root(root)
    try:
        with pytest.raises(WorkdirOperationError) as excinfo:
            ops.create_workdir(root_fd, relative_path)
        assert excinfo.value.code == ops.WORKDIR_LINK_DENIED
        with pytest.raises(WorkdirOperationError) as excinfo:
            ops.remove_workdir(root_fd, relative_path)
        assert excinfo.value.code == ops.WORKDIR_LINK_DENIED
    finally:
        os.close(root_fd)
    # Zero external modification: the replaced chain still holds its content.
    assert (external / "precious").read_bytes() == b"keep"


def test_hardlink_denies_cleanup_but_never_touches_the_external_inode(tmp_path, root):
    external = _plant_file(tmp_path, "external-secret", b"payload")
    relative_path = policy.build_relative_path("tenant-a", RUN)
    root_fd = ops.ensure_execution_root(root)
    handles = _make_handles(root_fd, relative_path)
    workdir_fd = os.open(
        "workdir", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=handles.run_fd
    )
    try:
        os.link(str(external), "shared", dst_dir_fd=workdir_fd)
    finally:
        os.close(workdir_fd)

    usage = ops.account_usage(handles.run_fd)
    assert usage.total_bytes == len(b"payload")
    assert usage.file_count == 1

    handles.close()
    with pytest.raises(WorkdirOperationError) as excinfo:
        ops.remove_workdir(root_fd, relative_path)
    assert excinfo.value.code == ops.WORKDIR_HARDLINK_DENIED
    assert external.read_bytes() == b"payload"  # external data intact
    assert _run_dir(root, relative_path).exists()

    # Remove the unprovable entry, then retry converges (idempotent cleanup).
    os.unlink(_run_dir(root, relative_path) / "workdir" / "shared")
    assert ops.remove_workdir(root_fd, relative_path) is True
    assert not _run_dir(root, relative_path).exists()
    assert external.read_bytes() == b"payload"
    os.close(root_fd)


def test_symlink_inside_workdir_is_removed_without_touching_target(tmp_path, root):
    external = _plant_file(tmp_path, "external-file", b"stay")
    relative_path = policy.build_relative_path("tenant-a", RUN)
    root_fd = ops.ensure_execution_root(root)
    handles = _make_handles(root_fd, relative_path)
    os.symlink(str(external), "pointer", dir_fd=handles.run_fd)
    handles.close()

    assert ops.remove_workdir(root_fd, relative_path) is True
    assert external.read_bytes() == b"stay"
    os.close(root_fd)


def test_mount_denial_via_substituted_probe_aborts_before_deleting(root):
    relative_path = policy.build_relative_path("tenant-a", RUN)
    root_fd = ops.ensure_execution_root(root)
    handles = _make_handles(root_fd, relative_path)
    workdir_path = _run_dir(root, relative_path) / "workdir"
    _plant_file(workdir_path, "a-file", b"1")
    handles.close()

    def always_mount(child_dev: int, parent_dev: int) -> bool:  # substituted probe
        return True

    with pytest.raises(WorkdirOperationError) as excinfo:
        ops.remove_workdir(root_fd, relative_path, mount_probe=always_mount)
    assert excinfo.value.code == ops.WORKDIR_MOUNT_DENIED
    # Nothing deleted: the scope above the mount point is unprovable.
    assert (workdir_path / "a-file").read_bytes() == b"1"

    reopened = ops.open_workdir(root_fd, relative_path)
    try:
        with pytest.raises(WorkdirOperationError) as excinfo:
            ops.account_usage(reopened.run_fd, mount_probe=always_mount)
        assert excinfo.value.code == ops.WORKDIR_MOUNT_DENIED
    finally:
        reopened.close()
        os.close(root_fd)


def test_removal_stops_on_deletion_race(root, monkeypatch):
    relative_path = policy.build_relative_path("tenant-a", RUN)
    root_fd = ops.ensure_execution_root(root)
    handles = _make_handles(root_fd, relative_path)
    _plant_file(_run_dir(root, relative_path) / "temp", "gone-soon", b"1")
    handles.close()

    real_unlink = os.unlink
    fired = {"count": 0}

    def racing_unlink(path, *args, **kwargs):
        fired["count"] += 1
        real_unlink(path, *args, **kwargs)
        raise FileNotFoundError  # the name vanished between check and use

    monkeypatch.setattr(os, "unlink", racing_unlink)
    with pytest.raises(WorkdirOperationError) as excinfo:
        ops.remove_workdir(root_fd, relative_path)
    assert excinfo.value.code == ops.WORKDIR_RACE
    assert fired["count"] == 1  # stopped at the first race, never blind-retried
    os.close(root_fd)


def test_removal_refuses_outside_recorded_scope_and_foreign_owner(root):
    root_fd = ops.ensure_execution_root(root)
    try:
        with pytest.raises(WorkdirOperationError) as excinfo:
            ops.remove_workdir(root_fd, "single-component")
        assert excinfo.value.code == ops.WORKDIR_SCOPE_MISMATCH

        with pytest.raises(WorkdirOperationError) as excinfo:
            ops.remove_workdir(root_fd, "../escape")
        assert excinfo.value.code == ops.WORKDIR_PATH_REJECTED

        relative_path = policy.build_relative_path("tenant-a", RUN)
        handles = _make_handles(root_fd, relative_path)
        handles.close()
        with pytest.raises(WorkdirOperationError) as excinfo:
            ops.remove_workdir(root_fd, relative_path, expected_uid=os.geteuid() + 1)
        assert excinfo.value.code == ops.WORKDIR_OWNER_MISMATCH
        # Ownership was unverifiable before any destructive call: tree intact.
        assert (_run_dir(root, relative_path) / "logs").is_dir()
    finally:
        os.close(root_fd)


def test_remove_reports_already_absent_honestly(root):
    root_fd = ops.ensure_execution_root(root)
    try:
        relative_path = policy.build_relative_path("tenant-a", RUN)
        assert ops.remove_workdir(root_fd, relative_path) is False
    finally:
        os.close(root_fd)


# ---------------------------------------------------------------------------
# T6: contract pins (P4-UT-11 face)
# ---------------------------------------------------------------------------


def test_workdir_status_machine_is_monotone_and_honest():
    assert set(WORKDIR_STATE_TRANSITIONS) == {
        "preparing",
        "ready",
        "active",
        "retained",
        "cleaning",
        "deleted",
        "cleanup_failed",
    }
    assert TERMINAL_WORKDIR_STATES == frozenset({"deleted"})
    # Deleted is final; a cleanup failure is never folded into success.
    assert WORKDIR_STATE_TRANSITIONS["deleted"] == frozenset()
    assert "deleted" not in WORKDIR_STATE_TRANSITIONS["cleanup_failed"]
    # Any live state can fail honestly into cleanup_failed.
    for state in ("preparing", "ready", "active", "retained", "cleaning"):
        assert "cleanup_failed" in WORKDIR_STATE_TRANSITIONS[state]
    # No backward moves into the live states from the tail of the machine.
    for state in ("retained", "cleaning", "deleted", "cleanup_failed"):
        assert not {"preparing", "ready", "active"} & WORKDIR_STATE_TRANSITIONS[state]


def test_workdir_error_codes_match_the_low_level_constant_set():
    literal_codes = set(typing.get_args(WorkdirErrorCode))
    constant_codes = {
        value
        for name, value in vars(ops).items()
        if name.startswith("WORKDIR_") and isinstance(value, str)
    }
    assert constant_codes <= literal_codes
    # The manager adds exactly two codes the filesystem layer cannot produce.
    assert literal_codes - constant_codes == {
        "workdir_state_invalid",
        "workdir_persistence_conflict",
    }


def test_record_is_strict_and_internal():
    with pytest.raises(ValidationError):
        WorkdirRecord(
            workdir_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            tenant_id="t",
            business_id="b",
            workspace_id="w",
            relative_path="aa11/" + RUN,
            status="ready",
            quota_bytes=1,
            size_bytes=0,
            file_count=0,
            created_at_posix=0.0,
            unexpected_field=True,
        )
    with pytest.raises(ValidationError):
        WorkdirRecord(
            workdir_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            tenant_id="t",
            business_id="b",
            workspace_id="w",
            relative_path="aa11/" + RUN,
            status="not_a_status",
            quota_bytes=1,
            size_bytes=0,
            file_count=0,
            created_at_posix=0.0,
        )

    import agent_platform.core_platform.agent_execution.contracts as public_contracts

    assert not hasattr(public_contracts, "WorkdirRecord")
    assert not hasattr(public_contracts, "WorkspaceProvider")


def test_manager_satisfies_the_provider_protocol_structurally():
    manager = ExecutionWorkspaceManager(
        engine=None,
        root=Path("data/execution"),
        quota_bytes=1024,
        retention_seconds=1,
        failed_retention_seconds=1,
    )
    assert isinstance(manager, WorkspaceProvider)


def test_provider_takes_no_path_arguments():
    # AC-7 type-level gate: the contract surface speaks only in platform ids.
    import inspect

    for name in ("prepare", "activate", "retain", "cleanup", "get"):
        signature = inspect.signature(getattr(WorkspaceProvider, name))
        parameters = signature.parameters
        assert "path" not in parameters
        assert "relative_path" not in parameters
        assert "root" not in parameters
    prepare = inspect.signature(WorkspaceProvider.prepare)
    assert {"run_id", "tenant_id", "business_id", "workspace_id"} <= set(prepare.parameters)


# ---------------------------------------------------------------------------
# T6: durable lifecycle on PostgreSQL (P4-IT-13/14/15)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    name = "phase4_workspace_" + uuid.uuid4().hex

    async def admin(statement):
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    target = urlunsplit(parts._replace(path="/" + name))
    migrate(target, "head")
    try:
        yield target
    finally:
        asyncio.run(admin(f'DROP DATABASE "{name}" WITH (FORCE)'))


def _drive_engine(url, flow, root):
    async def main():
        from agent_platform.core_platform.platform_services.persistence.database import (
            create_engine,
        )
        from agent_platform.core_platform.platform_services.platform_settings.settings import (
            Settings,
        )

        settings = Settings(
            _env_file=None,
            database_url=url.replace("postgresql://", "postgresql+asyncpg://"),
            tenant_id="phase4-workspace",
            embedded_worker=False,
        )
        engine = create_engine(settings)
        try:
            await flow(engine, root)
        finally:
            await engine.dispose()

    asyncio.run(main())


async def _make_run(engine, tenant: str) -> uuid.UUID:
    from agent_platform.applications.platform_runtime.runtime_hooks import (
        BusinessRuntimePersistenceHooks,
    )
    from agent_platform.core_platform.agent_runtime.repository import RunRepository
    from agent_platform.core_platform.agent_runtime.schemas import RunRequest

    repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    row = await repo.submit(
        tenant,
        RunRequest(conversation_id=f"conv-{uuid.uuid4()}", message="workspace test"),
        {"fingerprint": "phase4-workdir"},
        100,
        100,
        120,
    )
    return uuid.UUID(str(row["id"]))


def _manager(engine, root: Path, clock, **overrides):
    params = {
        "quota_bytes": 1_073_741_824,
        "retention_seconds": 3600,
        "failed_retention_seconds": 7200,
    }
    params.update(overrides)
    return ExecutionWorkspaceManager(engine, root=root, clock=clock, **params)


@pytest.mark.postgres
def test_prepare_activate_retain_cleanup_survive_a_manager_restart(workspace_database, tmp_path):
    root = tmp_path / "execution"
    root.mkdir(mode=0o700)
    tenant = "wd-restart"

    async def flow(engine, manager_root):
        manager = _manager(engine, manager_root, clock=lambda: 1_000.0)
        run_id = await _make_run(engine, tenant)

        record = await manager.prepare(
            run_id=run_id, tenant_id=tenant, business_id="b", workspace_id="w"
        )
        assert record.status == "ready"
        assert record.relative_path == policy.build_relative_path(tenant, str(run_id))
        assert record.quota_bytes == 1_073_741_824
        assert record.expires_at_posix is None
        run_dir = manager_root / record.relative_path
        for name in policy.expected_layout_dirs():
            assert (run_dir / name).is_dir()
            assert stat.S_IMODE((run_dir / name).stat().st_mode) == policy.DIR_MODE

        # Idempotent second prepare returns the same durable record.
        again = await manager.prepare(
            run_id=run_id, tenant_id=tenant, business_id="b", workspace_id="w"
        )
        assert again.workdir_id == record.workdir_id

        active = await manager.activate(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant
        )
        assert active.status == "active"

        _plant_file(run_dir / "workdir", "artifact", b"0123456789")
        retained = await manager.retain(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant, outcome="success"
        )
        assert retained.status == "retained"
        assert retained.expires_at_posix == pytest.approx(4_600.0)
        assert retained.size_bytes == 10
        assert retained.file_count == 1

        deleted = await manager.cleanup(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant
        )
        assert deleted.status == "deleted"
        assert not run_dir.exists()

        # Restart recovery: a brand-new manager instance sees the Tombstone
        # (AC-6) and repeated cleanup is a no-op that never touches the fs.
        restarted = _manager(engine, manager_root, clock=lambda: 1_000.0)
        current = await restarted.get(run_id=run_id, tenant_id=tenant)
        assert current is not None and current.status == "deleted"
        again_deleted = await restarted.cleanup(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant
        )
        assert again_deleted.status == "deleted"
        assert not run_dir.exists()

    _drive_engine(workspace_database, flow, root)


@pytest.mark.postgres
def test_retain_failed_window_and_state_rejection(workspace_database, tmp_path):
    root = tmp_path / "execution"
    root.mkdir(mode=0o700)
    tenant = "wd-failed-window"

    async def flow(engine, manager_root):
        manager = _manager(engine, manager_root, clock=lambda: 10.0)
        run_id = await _make_run(engine, tenant)
        record = await manager.prepare(
            run_id=run_id, tenant_id=tenant, business_id="b", workspace_id="w"
        )
        await manager.activate(workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant)
        retained = await manager.retain(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant, outcome="failed"
        )
        assert retained.expires_at_posix == pytest.approx(7_210.0)

        # retained cannot re-activate: the machine moves forward only.
        with pytest.raises(WorkspaceStateError) as excinfo:
            await manager.activate(workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant)
        assert excinfo.value.code == "workdir_state_invalid"

        with pytest.raises(WorkspaceStateError) as excinfo:
            await manager.cleanup(workdir_id=uuid.uuid4(), run_id=run_id, tenant_id=tenant)
        assert excinfo.value.code == "workdir_persistence_conflict"

    _drive_engine(workspace_database, flow, root)


@pytest.mark.postgres
def test_cleanup_failure_retains_record_and_never_repoints(workspace_database, tmp_path):
    root = tmp_path / "execution"
    root.mkdir(mode=0o700)
    tenant = "wd-cleanup-failure"

    async def flow(engine, manager_root):
        manager = _manager(engine, manager_root, clock=lambda: 5.0)
        run_id = await _make_run(engine, tenant)
        record = await manager.prepare(
            run_id=run_id, tenant_id=tenant, business_id="b", workspace_id="w"
        )
        await manager.activate(workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant)

        external = _plant_file(manager_root.parent, "external-victim", b"victim")
        workdir_fd = os.open(manager_root / record.relative_path / "workdir", os.O_RDONLY)
        try:
            os.link(str(external), "shared", dst_dir_fd=workdir_fd)
        finally:
            os.close(workdir_fd)

        await manager.retain(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant, outcome="failed"
        )
        with pytest.raises(WorkspaceStateError) as excinfo:
            await manager.cleanup(workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant)
        assert excinfo.value.code == ops.WORKDIR_HARDLINK_DENIED

        current = await manager.get(run_id=run_id, tenant_id=tenant)
        assert current is not None
        assert current.status == "cleanup_failed"
        assert current.last_error_code == "workdir_hardlink_denied"
        # Never repoints: the recorded path is untouched and the tree survives.
        assert current.relative_path == record.relative_path
        assert (manager_root / record.relative_path / "workdir" / "shared").exists()

        # The failed row is always a scan candidate; after removing the
        # unprovable entry the retry converges and the external data is intact.
        candidates = await manager.sweep_expired(now_posix=1.0, tenant_id=tenant)
        assert [c.workdir_id for c in candidates] == [record.workdir_id]
        os.unlink(manager_root / record.relative_path / "workdir" / "shared")
        deleted = await manager.cleanup(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant
        )
        assert deleted.status == "deleted"
        assert external.read_bytes() == b"victim"

    _drive_engine(workspace_database, flow, root)


@pytest.mark.postgres
def test_expired_retention_scan_selects_only_matured_rows(workspace_database, tmp_path):
    root = tmp_path / "execution"
    root.mkdir(mode=0o700)
    tenant = "wd-sweep"

    async def flow(engine, manager_root):
        now = {"t": 0.0}
        manager = _manager(engine, manager_root, clock=lambda: now["t"])
        first_run = await _make_run(engine, tenant)
        second_run = await _make_run(engine, tenant)

        first = await manager.prepare(
            run_id=first_run, tenant_id=tenant, business_id="b", workspace_id="w"
        )
        await manager.activate(workdir_id=first.workdir_id, run_id=first_run, tenant_id=tenant)
        await manager.retain(
            workdir_id=first.workdir_id,
            run_id=first_run,
            tenant_id=tenant,
            outcome="success",
        )  # expires at 3600
        second = await manager.prepare(
            run_id=second_run, tenant_id=tenant, business_id="b", workspace_id="w"
        )
        await manager.activate(workdir_id=second.workdir_id, run_id=second_run, tenant_id=tenant)
        now["t"] = 7_200.0
        await manager.retain(
            workdir_id=second.workdir_id,
            run_id=second_run,
            tenant_id=tenant,
            outcome="success",
        )  # expires at 10800

        immature = await manager.sweep_expired(now_posix=3_000.0, tenant_id=tenant)
        assert immature == []  # first matures at 3600, second at 10800

        partial = await manager.sweep_expired(now_posix=4_000.0, tenant_id=tenant)
        assert {c.workdir_id for c in partial} == {first.workdir_id}

        matured = await manager.sweep_expired(now_posix=11_000.0, tenant_id=tenant)
        assert {c.workdir_id for c in matured} == {first.workdir_id, second.workdir_id}

        # Drive the candidates through the idempotent cleanup path.
        for candidate in matured:
            deleted = await manager.cleanup(
                workdir_id=candidate.workdir_id,
                run_id=candidate.run_id,
                tenant_id=candidate.tenant_id,
            )
            assert deleted.status == "deleted"
        assert tuple(await manager.sweep_expired(now_posix=11_000.0, tenant_id=tenant)) == ()

    _drive_engine(workspace_database, flow, root)


@pytest.mark.postgres
def test_concurrent_cross_tenant_prepare_and_fk_gate(workspace_database, tmp_path):
    root = tmp_path / "execution"
    root.mkdir(mode=0o700)

    async def flow(engine, manager_root):
        manager = _manager(engine, manager_root, clock=lambda: 1.0)
        run_a = await _make_run(engine, "wd-tenant-a")
        run_b = await _make_run(engine, "wd-tenant-b")
        first, second = await asyncio.gather(
            manager.prepare(
                run_id=run_a, tenant_id="wd-tenant-a", business_id="b", workspace_id="w"
            ),
            manager.prepare(
                run_id=run_b, tenant_id="wd-tenant-b", business_id="b", workspace_id="w"
            ),
        )
        assert first.relative_path != second.relative_path
        assert (manager_root / first.relative_path).is_dir()
        assert (manager_root / second.relative_path).is_dir()

        # Concurrent double-prepare of the same Run converges on one record.
        pair = await asyncio.gather(
            manager.prepare(
                run_id=run_a, tenant_id="wd-tenant-a", business_id="b", workspace_id="w"
            ),
            manager.prepare(
                run_id=run_a, tenant_id="wd-tenant-a", business_id="b", workspace_id="w"
            ),
        )
        assert pair[0].workdir_id == pair[1].workdir_id == first.workdir_id

        # Trusted-target gate: an unknown run_id never reaches the filesystem.
        ghost = uuid.uuid4()
        with pytest.raises(WorkspaceStateError) as excinfo:
            await manager.prepare(
                run_id=ghost, tenant_id="wd-tenant-a", business_id="b", workspace_id="w"
            )
        assert excinfo.value.code == "workdir_persistence_conflict"
        assert not (manager_root / policy.tenant_digest("wd-tenant-a") / str(ghost)).exists()

    _drive_engine(workspace_database, flow, root)


@pytest.mark.postgres
def test_tampered_relative_path_is_refused_and_marked_failed(workspace_database, tmp_path):
    root = tmp_path / "execution"
    root.mkdir(mode=0o700)
    victim_tenant = "wd-tamper-victim"
    attacker_tenant = "wd-tamper"

    async def flow(engine, manager_root):
        db_url = workspace_database.replace("postgresql+asyncpg://", "postgresql://")
        manager = _manager(engine, manager_root, clock=lambda: 1.0)
        victim_run = await _make_run(engine, victim_tenant)
        attacker_run = await _make_run(engine, attacker_tenant)
        victim = await manager.prepare(
            run_id=victim_run,
            tenant_id=victim_tenant,
            business_id="b",
            workspace_id="w",
        )
        attacker = await manager.prepare(
            run_id=attacker_run,
            tenant_id=attacker_tenant,
            business_id="b",
            workspace_id="w",
        )

        # Simulate a repointed row by swapping the two durable paths (the
        # column is globally UNIQUE, mirroring "never repoints elsewhere").
        # The attacker record now names the victim's directory, and cleanup
        # must refuse without touching either tree.
        placeholder = f"ffffffffffffffff/{uuid.uuid4()}"
        victim_path = victim.relative_path
        attacker_path = attacker.relative_path

        async def swap():
            conn = await asyncpg.connect(db_url)
            try:
                await conn.execute(
                    "UPDATE execution_workdirs SET relative_path=$1 WHERE id=$2",
                    placeholder,
                    str(victim.workdir_id),
                )
                await conn.execute(
                    "UPDATE execution_workdirs SET relative_path=$1 WHERE id=$2",
                    victim_path,
                    str(attacker.workdir_id),
                )
                await conn.execute(
                    "UPDATE execution_workdirs SET relative_path=$1 WHERE id=$2",
                    attacker_path,
                    str(victim.workdir_id),
                )
            finally:
                await conn.close()

        await swap()

        await manager.activate(
            workdir_id=attacker.workdir_id, run_id=attacker_run, tenant_id=attacker_tenant
        )
        await manager.retain(
            workdir_id=attacker.workdir_id,
            run_id=attacker_run,
            tenant_id=attacker_tenant,
            outcome="failed",
        )
        with pytest.raises(WorkspaceStateError) as excinfo:
            await manager.cleanup(
                workdir_id=attacker.workdir_id, run_id=attacker_run, tenant_id=attacker_tenant
            )
        assert excinfo.value.code == "workdir_scope_mismatch"
        assert (manager_root / victim_path / "logs").is_dir()  # victim intact
        assert (manager_root / attacker_path / "logs").is_dir()  # own tree untouched
        current = await manager.get(run_id=attacker_run, tenant_id=attacker_tenant)
        assert current is not None and current.status == "cleanup_failed"
        assert current.last_error_code == "workdir_scope_mismatch"
        # Refuse, never repair-by-repoint: the stored (tampered) path stands
        # for the operator to see; the manager wrote only status/error fields.
        assert current.relative_path == victim_path

    _drive_engine(workspace_database, flow, root)


@pytest.mark.postgres
def test_prepare_fs_failure_records_cleanup_failed_then_recovers(workspace_database, tmp_path):
    broken_root = tmp_path / "execution"
    real = tmp_path / "real-execution"
    real.mkdir(mode=0o700)
    broken_root.symlink_to(real, target_is_directory=True)
    tenant = "wd-prepare-failure"

    async def flow(engine, manager_root):
        manager = _manager(engine, manager_root, clock=lambda: 2.0)
        run_id = await _make_run(engine, tenant)
        with pytest.raises(WorkspaceStateError) as excinfo:
            await manager.prepare(
                run_id=run_id, tenant_id=tenant, business_id="b", workspace_id="w"
            )
        assert excinfo.value.code == ops.WORKDIR_ROOT_INVALID
        record = await manager.get(run_id=run_id, tenant_id=tenant)
        assert record is not None
        assert record.status == "cleanup_failed"
        assert record.last_error_code == "workdir_root_invalid"

        # Operator repairs the root; the retry converges to deleted (nothing
        # existed to remove, which is honest, not fabricated).
        Path(manager_root).unlink()
        Path(manager_root).mkdir(mode=0o700)
        deleted = await manager.cleanup(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=tenant
        )
        assert deleted.status == "deleted"

    _drive_engine(workspace_database, flow, broken_root)
