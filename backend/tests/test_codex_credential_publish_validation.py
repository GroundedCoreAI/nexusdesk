"""Issue #165 L1: publish-time validation of the Codex credential chain.

A stale ``credential_ref`` used to publish cleanly and fail only at run time,
where the Broker denial collapsed to the sanitized ``execution_error``. These
are pure unit tests: the DB connection is a stub, so no Postgres is required.
"""

import asyncio
from uuid import UUID, uuid4

import pytest

from agent_platform.business_capabilities.agent_config.service import AgentService
from agent_platform.core_platform.agent_execution.contracts.config import (
    CodexConfig,
    EngineIdentity,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError

_TENANT = "tenant-publish"
_REF = uuid4()
_PROFILE_ID = uuid4()


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeConn:
    def __init__(self, row) -> None:
        self.row = row
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        return _FakeResult(self.row)


class _FakeCatalog:
    def __init__(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple] = []

    async def resolve(self, tenant, identifier, version, connection=None):
        self.calls.append((tenant, identifier, version, connection))
        return self.snapshot


def _gateway_snapshot(reference: UUID | None) -> dict:
    return {
        "routes": [
            {
                "connection": {
                    "execution_credential_ref": (
                        str(reference) if reference is not None else None
                    )
                }
            }
        ]
    }


def _row(**overrides) -> dict:
    base = {
        "credential_ref": _REF,
        "status": "active",
        "allowed_engines": ["codex"],
        "allowed_workspaces": ["workspace-1"],
    }
    base.update(overrides)
    return base


def _config(
    engine_id: str,
    reference: str | None,
    *,
    gateway_profile_id: str | None = None,
):
    codex: dict[str, object] | None = None
    react: dict[str, object] | None = None
    if engine_id == "codex":
        codex = {"version": "0.169.0", "credential_ref": reference}
        if gateway_profile_id is not None:
            codex.update(
                model_profile_id=gateway_profile_id,
                model_profile_version=1,
            )
    else:
        react = {
            "model_profile_id": str(uuid4()),
            "model_profile_version": 1,
            "max_model_rounds": 6,
        }
    return AgentService.parse_config(
        {
            "system_prompt": "acceptance probe",
            "engine": {
                "engine_id": engine_id,
                "protocol_id": "cli_exec" if engine_id == "codex" else "native",
                "adapter_version": "v1",
            },
            "codex": codex,
            "react": react,
        }
    )


def _service(model_catalog=None) -> AgentService:
    # The standalone registry is metadata-only; no adapter is resolved here.
    return AgentService(engine=None, tools=None, model_catalog=model_catalog)


def _validate(conn: _FakeConn, config) -> None:
    asyncio.run(_service().validate_codex_credential(_TENANT, config, conn))


def test_unknown_reference_is_rejected_before_publish() -> None:
    conn = _FakeConn(None)
    with pytest.raises(DomainError) as exc:
        _validate(conn, _config("codex", str(_REF)))
    assert exc.value.code == "codex_credential_invalid"
    assert exc.value.status == 409


@pytest.mark.parametrize(
    "row",
    [
        _row(status="revoked"),
        _row(status="superseded"),
        _row(allowed_engines=["react"]),
        _row(allowed_workspaces=[]),
    ],
)
def test_inactive_or_out_of_scope_reference_is_rejected(row: dict) -> None:
    conn = _FakeConn(row)
    with pytest.raises(DomainError) as exc:
        _validate(conn, _config("codex", str(_REF)))
    assert exc.value.code == "codex_credential_invalid"


def test_active_scoped_reference_is_accepted_and_canonicalized() -> None:
    conn = _FakeConn(_row())
    config = _config("codex", str(_REF).upper())
    _validate(conn, config)
    assert config.codex is not None
    assert config.codex.credential_ref == str(_REF)
    assert UUID(str(config.codex.credential_ref)) == _REF
    # Only lifecycle metadata is ever selected; the encrypted secret is not.
    sql, params = conn.calls[0]
    assert "encrypted_secret" not in sql
    assert params["ref"] == _REF
    assert params["t"] == _TENANT


def test_no_reference_is_rejected() -> None:
    conn = _FakeConn(_row())
    with pytest.raises(DomainError) as exc:
        _validate(conn, _config("codex", None))
    assert exc.value.code == "codex_credential_invalid"
    assert conn.calls == []


def test_non_uuid_reference_is_rejected_without_a_query() -> None:
    conn = _FakeConn(_row())
    with pytest.raises(DomainError) as exc:
        _validate(conn, _config("codex", "not-a-reference"))
    assert exc.value.code == "codex_credential_invalid"
    assert conn.calls == []


def test_react_engine_is_untouched() -> None:
    conn = _FakeConn(_row())
    _validate(conn, _config("react", str(_REF)))
    assert conn.calls == []


def test_engine_identity_shape_is_pinned() -> None:
    """Guard the exact codex triple used by the fixtures above."""
    identity = EngineIdentity(engine_id="codex", protocol_id="cli_exec", adapter_version="v1")
    assert identity.engine_id == "codex"
    assert isinstance(CodexConfig(version="0.169.0"), CodexConfig)


def test_gateway_profile_uses_the_connection_credential_reference() -> None:
    gateway_ref = uuid4()
    catalog = _FakeCatalog(_gateway_snapshot(gateway_ref))
    conn = _FakeConn(_row(credential_ref=gateway_ref))
    config = _config("codex", str(_REF), gateway_profile_id=str(_PROFILE_ID))

    asyncio.run(_service(catalog).validate_codex_credential(_TENANT, config, conn))

    assert catalog.calls[0][:3] == (_TENANT, _PROFILE_ID, 1)
    assert conn.calls[0][1]["ref"] == gateway_ref
    assert config.codex is not None
    assert config.codex.credential_ref == str(gateway_ref)


def test_gateway_profile_without_a_connection_reference_is_rejected() -> None:
    catalog = _FakeCatalog(_gateway_snapshot(None))
    conn = _FakeConn(_row())
    config = _config("codex", str(_REF), gateway_profile_id=str(_PROFILE_ID))

    with pytest.raises(DomainError) as exc:
        asyncio.run(_service(catalog).validate_codex_credential(_TENANT, config, conn))
    assert exc.value.code == "codex_credential_invalid"
    assert conn.calls == []


def test_missing_catalog_skips_gateway_profile_branch_for_credentials() -> None:
    conn = _FakeConn(_row())
    config = _config("codex", str(_REF), gateway_profile_id=str(_PROFILE_ID))

    _validate(conn, config)

    assert conn.calls[0][1]["ref"] == _REF
    assert config.codex is not None
    assert config.codex.credential_ref == str(_REF)


def test_validate_model_skips_codex_gateway_resolution_without_a_catalog() -> None:
    config = _config("codex", str(_REF), gateway_profile_id=str(_PROFILE_ID))

    asyncio.run(_service().validate_model(_TENANT, config, object()))

    assert config.codex is not None
    assert config.codex.model_profile_id == _PROFILE_ID
