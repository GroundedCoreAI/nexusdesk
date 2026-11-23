"""Unit tests for monitoring alembic discovery — no database required.

The migration collector used to build its config from a fixed ancestor of
``__file__``, which pointed into the venv once the package was installed as a
wheel. These tests pin the source-tree layout, the installed-wheel layout,
the ``unknown`` degradation when no config exists, and the conversion of an
alembic ``CommandError`` into ``CollectorError``.
"""

from pathlib import Path

import pytest
from alembic.util.exc import CommandError

from agent_platform.core_platform.platform_services.monitoring import collectors
from agent_platform.core_platform.platform_services.monitoring.registry import (
    Action,
    Check,
    CheckRegistry,
    CollectorContext,
    CollectorError,
    Registration,
)
from agent_platform.core_platform.platform_services.monitoring.service import MonitoringService


def _write_alembic(root: Path, *, script_location: str = "%(here)s/migrations") -> Path:
    """Create an alembic.ini plus its migrations directory under ``root``."""

    root.mkdir(parents=True, exist_ok=True)
    (root / "alembic.ini").write_text(
        f"[alembic]\nscript_location = {script_location}\nprepend_sys_path = .\n",
        encoding="utf-8",
    )
    migrations = root / "migrations"
    migrations.mkdir(exist_ok=True)
    return migrations


def test_source_layout_resolves_from_backend_root(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    migrations = _write_alembic(backend)
    module = backend / "src/agent_platform/core_platform/platform_services/monitoring/collectors.py"
    monkeypatch.setattr(collectors, "BACKEND_ROOT", backend)
    monkeypatch.setattr(collectors, "__file__", str(module))

    config = collectors._resolve_alembic_config()

    assert config.get_main_option("script_location") == str(migrations)


def test_installed_wheel_layout_resolves_from_ancestor(tmp_path, monkeypatch):
    app = tmp_path / "app"
    migrations = _write_alembic(app)
    venv_root = app / ".venv/lib/python3.12"
    module = (
        venv_root
        / "site-packages/agent_platform/core_platform/platform_services/monitoring/collectors.py"
    )
    # BACKEND_ROOT is a venv directory here: no alembic.ini of its own.
    monkeypatch.setattr(collectors, "BACKEND_ROOT", venv_root)
    monkeypatch.setattr(collectors, "__file__", str(module))

    candidates = collectors._alembic_config_candidates()
    config = collectors._resolve_alembic_config()

    assert candidates[0] == venv_root
    assert app in candidates
    assert config.get_main_option("script_location") == str(migrations)


def test_missing_config_degrades_to_collector_error(tmp_path, monkeypatch):
    backend = tmp_path / "empty-backend"
    backend.mkdir(parents=True)
    module = backend / "src/agent_platform/core_platform/platform_services/monitoring/collectors.py"
    monkeypatch.setattr(collectors, "BACKEND_ROOT", backend)
    monkeypatch.setattr(collectors, "__file__", str(module))

    with pytest.raises(CollectorError) as caught:
        collectors._alembic_heads()

    assert caught.value.code == "alembic_config_missing"


@pytest.mark.asyncio
async def test_pg_migration_converts_command_error(monkeypatch):
    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    async def _fake_one(conn, sql, **params):
        return {"version_num": "0001"}

    class _BrokenScriptDirectory:
        @staticmethod
        def from_config(config):
            raise CommandError("No 'script_location' key found in configuration.")

    ctx = CollectorContext(engine=_Engine(), settings=object(), tenant="t")
    monkeypatch.setattr(collectors, "one", _fake_one)
    monkeypatch.setattr(collectors, "_resolve_alembic_config", lambda: object())
    monkeypatch.setattr(collectors, "ScriptDirectory", _BrokenScriptDirectory)

    with pytest.raises(CollectorError) as caught:
        await collectors.pg_migration(ctx)

    assert caught.value.code == "alembic_config_missing"
    assert not isinstance(caught.value, CommandError)


@pytest.mark.asyncio
async def test_scan_closes_row_when_collector_raises(monkeypatch):
    """A CollectorError degrades to unknown and never aborts the scan loop."""

    async def _broken_collector(ctx):
        raise CollectorError("alembic_config_missing")

    def _unreachable_judge(sample, settings):
        raise AssertionError("judge must not run when collection failed")

    registry = CheckRegistry()
    registry.register(
        Registration(
            Check(
                id="pg_migration",
                group="middleware",
                kind="required",
                severity="P0",
                cadence="daily",
                action=Action("view", "/governance"),
            ),
            _broken_collector,
            _unreachable_judge,
        )
    )
    service = MonitoringService(engine=object(), settings=object(), registry=registry)
    closed: list = []

    async def _open_scan(tenant):
        return 1

    async def _load_snapshot():
        return {}

    async def _persist(outcomes):
        return None

    async def _transitions(outcomes, tenant):
        return None

    async def _close_scan(scan_id, outcomes, started):
        closed.append((scan_id, outcomes))

    monkeypatch.setattr(service, "_open_scan", _open_scan)
    monkeypatch.setattr(service, "_load_snapshot", _load_snapshot)
    monkeypatch.setattr(service, "_persist", _persist)
    monkeypatch.setattr(service, "_transitions", _transitions)
    monkeypatch.setattr(service, "_close_scan", _close_scan)

    result = await service.scan(force=True, tenant="t")

    assert result["checks"] == 1
    assert result["failed"] == 0  # unknown is not a NON_PASS status
    assert len(closed) == 1 and closed[0][0] == 1
    assert closed[0][1][0].status == "unknown"
