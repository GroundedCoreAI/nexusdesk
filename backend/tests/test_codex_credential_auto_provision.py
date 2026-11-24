"""Saving a gateway channel auto-provisions its Codex execution credential."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from test_ticket_migrations import migrate, query
from test_ticket_migrations import migration_database as _migration_database

from agent_platform.core_platform.platform_services.model_gateway.catalog import Catalog
from agent_platform.core_platform.platform_services.model_gateway.contracts import Connection
from agent_platform.core_platform.platform_services.model_gateway.host_allowlist import (
    HostAllowlistStore,
)
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

pytestmark = pytest.mark.postgres
migration_database = _migration_database

TENANT = "local"
BASE_URL = "https://api.openai.com/v1"


def _settings(key_file: Path, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        model_credential_key_file=key_file,
        execution_credential_key_file=key_file,
        model_gateway_allowed_hosts=["api.openai.com"],
        **overrides,
    )


def _make_catalog(url: str, key_file: Path, execution_key_file: Path | None = None) -> Catalog:
    # create_engine(Settings()) reads AGENT_DATABASE_URL; point it at the
    # disposable migration database for the duration of the test process.
    os.environ["AGENT_DATABASE_URL"] = url.replace("postgresql://", "postgresql+asyncpg://")
    settings = _settings(key_file)
    engine = create_engine(settings)
    hosts = HostAllowlistStore(engine, settings)
    return Catalog(
        engine,
        settings,
        hosts=hosts,
        auto_codex_credentials=execution_key_file if execution_key_file is not None else key_file,
    )


def _connection(name: str, api_key: str, **extra) -> Connection:
    return Connection(
        name=name,
        protocol="openai_compatible",
        base_url=BASE_URL,
        api_key=api_key,
        **extra,
    )


def _credential_count(url: str, cert_ref: str) -> int:
    return query(
        url,
        "SELECT count(*) FROM execution_credentials WHERE tenant_id=$1 AND credential_ref=$2",
        TENANT,
        UUID(cert_ref),
    )[0][0]


def test_save_channel_creates_codex_credential_and_fills_reference(
    migration_database, tmp_path
):
    url = migration_database
    migrate(url, "head")
    key_file = tmp_path / "keys"
    key_file.mkdir()
    (key_file / "master.key").write_bytes(Fernet.generate_key())
    (key_file / "execution.key").write_bytes(Fernet.generate_key())
    catalog = _make_catalog(url, key_file / "master.key")

    async def run():
        saved = await catalog.save(TENANT, "admin", "connections", _connection("custom", "sk-1"))
        return saved

    saved = asyncio.run(run())
    ref = saved["spec"]["execution_credential_ref"]
    assert ref and UUID(ref)
    assert _credential_count(url, ref) == 1
    row = query(
        url,
        "SELECT credential_type,status,allowed_engines,allowed_workspaces "
        "FROM execution_credentials WHERE tenant_id=$1 AND credential_ref=$2 AND version=1",
        TENANT,
        UUID(ref),
    )[0]
    assert row[0] == "api_key" and row[1] == "active"
    assert json.loads(row[2]) == ["codex"]
    assert json.loads(row[3]) == ["default"]


def test_resave_with_new_key_rotates_in_place_and_keeps_ref(migration_database, tmp_path):
    url = migration_database
    migrate(url, "head")
    key_file = tmp_path / "keys"
    key_file.mkdir()
    (key_file / "master.key").write_bytes(Fernet.generate_key())
    (key_file / "execution.key").write_bytes(Fernet.generate_key())
    catalog = _make_catalog(url, key_file / "master.key")

    async def run():
        first = await catalog.save(TENANT, "admin", "connections", _connection("custom", "sk-1"))
        ref = first["spec"]["execution_credential_ref"]
        second = await catalog.save(
            TENANT,
            "admin",
            "connections",
            _connection("custom", "sk-2", execution_credential_ref=ref),
            first["id"],
            first["revision"],
        )
        return first, second, ref

    _first, second, ref = asyncio.run(run())
    assert second["spec"]["execution_credential_ref"] == ref
    versions = query(
        url,
        "SELECT version,status FROM execution_credentials WHERE credential_ref=$1 ORDER BY version",
        UUID(ref),
    )
    assert [v[0] for v in versions] == [1, 2]
    assert [v[1] for v in versions] == ["superseded", "active"]


def test_save_without_key_preserves_existing_reference(migration_database, tmp_path):
    url = migration_database
    migrate(url, "head")
    key_file = tmp_path / "keys"
    key_file.mkdir()
    (key_file / "master.key").write_bytes(Fernet.generate_key())
    (key_file / "execution.key").write_bytes(Fernet.generate_key())
    catalog = _make_catalog(url, key_file / "master.key")

    async def run():
        first = await catalog.save(TENANT, "admin", "connections", _connection("custom", "sk-1"))
        ref = first["spec"]["execution_credential_ref"]
        # Without api_key, the reentry guard requires an unchanged base_url.
        second = await catalog.save(
            TENANT,
            "admin",
            "connections",
            Connection(name="custom", protocol="openai_compatible", base_url=BASE_URL),
            first["id"],
            first["revision"],
        )
        return ref, second

    ref, second = asyncio.run(run())
    assert second["spec"]["execution_credential_ref"] == ref


def test_demo_channel_does_not_provision_credential(migration_database, tmp_path):
    url = migration_database
    migrate(url, "head")
    key_file = tmp_path / "keys"
    key_file.mkdir()
    (key_file / "master.key").write_bytes(Fernet.generate_key())
    (key_file / "execution.key").write_bytes(Fernet.generate_key())
    catalog = _make_catalog(url, key_file / "master.key")

    async def run():
        return await catalog.save(
            TENANT,
            "admin",
            "connections",
            Connection(name="demo", protocol="demo", base_url=""),
        )

    saved = asyncio.run(run())
    assert saved["spec"].get("execution_credential_ref") is None
    assert query(url, "SELECT count(*) FROM execution_credentials")[0][0] == 0


def test_missing_execution_key_keeps_channel_save_working(migration_database, tmp_path):
    """Unprovisioned CLI lane must not break ordinary gateway channel saves."""
    url = migration_database
    migrate(url, "head")
    key_file = tmp_path / "keys"
    key_file.mkdir()
    (key_file / "master.key").write_bytes(Fernet.generate_key())
    missing_execution_key = key_file / "execution.key"
    assert not missing_execution_key.exists()
    catalog = _make_catalog(url, key_file / "master.key", missing_execution_key)

    saved = asyncio.run(
        catalog.save(TENANT, "admin", "connections", _connection("custom", "sk-1"))
    )
    assert saved["spec"].get("execution_credential_ref") is None
    assert query(url, "SELECT count(*) FROM execution_credentials")[0][0] == 0
