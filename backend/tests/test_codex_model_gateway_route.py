"""Q3/Q5: Codex ModelGateway route resolution and the legacy compatibility lane.

These are pure unit tests: the DB engine and the published profile snapshot are
fakes, so no Postgres is needed. The address check still runs through the real
``Catalog.validate_address`` so ``model_gateway_allowed_hosts`` is not re-created
here. Conventions (recording host, resource policy, private CODEX_HOME) follow
``test_agent_execution_stage_a_engine_home.py``.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.core_platform.agent_execution.adapters.codex.adapter import CodexCliAdapter
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexStageGate,
)
from agent_platform.core_platform.agent_execution.adapters.codex.home_config import (
    CodexEngineHomeConfig,
)
from agent_platform.core_platform.agent_execution.contracts import (
    ConfigurationError,
    ExecutionErrorCode,
    ExecutionRequest,
)
from agent_platform.core_platform.agent_execution.contracts.config import (
    normalize_execution_config,
)
from agent_platform.core_platform.agent_execution.contracts.snapshots import (
    _TYPED_CODEX_FIELDS,
    ExecutionSnapshotError,
    assert_snapshot_payload_clean,
    build_execution_config_snapshot,
    serialize_snapshot,
)
from agent_platform.core_platform.agent_execution.host.host_models import ResourcePolicy
from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
    _safe_legacy_code,
)
from agent_platform.core_platform.agent_execution.workspace.execution_workdir import (
    PRIVATE_ENGINE_HOME_NAME,
)
from agent_platform.core_platform.platform_services.model_gateway.catalog import Catalog
from agent_platform.core_platform.platform_services.model_gateway.codex_route import (
    CodexProviderPlan,
    CodexProviderResolver,
    CodexRouteError,
)
from agent_platform.core_platform.platform_services.model_gateway.contracts import Connection
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

_TENANT = "tenant-q3"
_AGENT = uuid4()
_PROFILE_ID = uuid4()
_CREDENTIAL_REF = uuid4()
_DEPLOYMENT_CREDENTIAL_REF = uuid4()
_PUBLISHED_CREDENTIAL_REF = uuid4()
_CODEX_ENGINE = {"engine_id": "codex", "protocol_id": "cli_exec", "adapter_version": "v1"}

# Deliberately NOT DeepSeek: proves the Gateway lane has no provider hardcoding.
_MODEL = "qwen-plus"
_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_PROVIDER = "dashscope"

_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=67_108_864,
    max_processes=16,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=65_536,
)
_GATE = CodexStageGate(
    cli_enabled=True,
    stage_a_verified=True,
    allowed_versions=("0.169.0",),
    trusted_tenants=(_TENANT,),
)
# Legacy deployment home: the four global Settings keep their DeepSeek defaults,
# so a Gateway-lane assertion can prove they were NOT used for a bound Agent.
_LEGACY_HOME = CodexEngineHomeConfig(
    model="deepseek-flash",
    model_provider="deepseek",
    base_url="https://api.deepseek.com/v1",
    env_key="OPENAI_API_KEY",
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        model_gateway_allowed_hosts=[_PROVIDER + ".aliyuncs.com", "api.openai.com"],
        codex_path_env="/opt/codex/node/bin:/usr/bin",
        codex_credential_ref=_DEPLOYMENT_CREDENTIAL_REF,
    )


class _FakeConnection:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _FakeEngine:
    """Only ``connect()`` is needed; no SQLAlchemy engine or Postgres."""

    def connect(self) -> _FakeConnection:
        return _FakeConnection()


class _FakeCatalog(Catalog):
    """Real address governance, stubbed published-snapshot resolution."""

    def __init__(self, snapshot: dict, settings: Settings) -> None:
        super().__init__(_FakeEngine(), settings)
        self.snapshot = snapshot
        self.resolve_calls: list[tuple] = []
        self.address_calls: list[dict] = []

    async def resolve(self, tenant, identifier, version, connection=None):
        self.resolve_calls.append((tenant, identifier, version, connection))
        return self.snapshot

    def validate_address(self, spec):
        self.address_calls.append(dict(spec))
        return super().validate_address(spec)


def _snapshot(
    *,
    operation: str = "chat",
    tool_calling: bool = True,
    connection_overrides: dict | None = None,
    model: str = _MODEL,
    base_url: str = _BASE_URL,
) -> dict:
    connection = {
        "name": _PROVIDER,
        "protocol": "openai_compatible",
        "base_url": base_url,
        "credential_ref": None,
        "execution_credential_ref": str(_CREDENTIAL_REF),
        "codex_base_url": None,
        "codex_wire_api": None,
        "codex_model_provider": None,
    }
    if connection_overrides:
        connection.update(connection_overrides)
    return {
        "spec": {"operation": operation},
        "routes": [
            {
                "model_id": str(uuid4()),
                "model": {
                    "model_name": model,
                    "tool_calling": tool_calling,
                    "operations": ["chat"],
                },
                "connection_id": str(uuid4()),
                "connection": connection,
            }
        ],
    }


def _resolver(snapshot: dict, settings: Settings | None = None):
    settings = settings or _settings()
    catalog = _FakeCatalog(snapshot, settings)
    return CodexProviderResolver(_FakeEngine(), settings, catalog), catalog


class _RecordingHost:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start(self, spec, **kwargs):
        self.calls.append({"spec": spec, **kwargs})
        return SimpleNamespace(managed_id=uuid4())


def _request(relative: str, *, workspace_id: str | None = "workspace-q3") -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=uuid4(),
        engine_id="codex",
        protocol_id="cli_exec",
        adapter_version="v1",
        tenant_id=_TENANT,
        agent_id=_AGENT,
        input="inspect the resolved provider route",
        workspace_id=workspace_id,
        execution_workdir=relative,
    )


def _adapter(
    host: _RecordingHost,
    root: Path,
    *,
    config: CodexConfig,
    provider_resolver=None,
    path_env: str | None = None,
    credential_ref: UUID | None = None,
) -> CodexCliAdapter:
    return CodexCliAdapter(
        host,
        config=config,
        gate=_GATE,
        workdir_root=root,
        resource_policy=_POLICY,
        engine_home_config=_LEGACY_HOME,
        credential_broker=object(),
        provider_resolver=provider_resolver,
        path_env=path_env,
        credential_ref=credential_ref,
    )


def _start(adapter: CodexCliAdapter, root: Path, *, workspace_id: str | None) -> dict:
    request = _request(f"aa11/{uuid4()}", workspace_id=workspace_id)
    (root / request.execution_workdir).mkdir(parents=True, mode=0o700)
    asyncio.run(adapter.start(request))
    return {"request": request, "call": adapter._host.calls[0]}


# --------------------------------------------------------------------------- #
# 1. Route-derived config.toml (no DeepSeek hardcoding)                        #
# --------------------------------------------------------------------------- #


def test_resolution_renders_config_toml_from_the_route():
    resolver, catalog = _resolver(_snapshot())
    plan = asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 3, "workspace-q3"))

    assert isinstance(plan, CodexProviderPlan)
    assert plan.home_config.model == _MODEL
    assert plan.home_config.model_provider == _PROVIDER
    assert plan.home_config.base_url == _BASE_URL
    assert plan.home_config.wire_api == "responses"
    assert plan.home_config.env_key == "OPENAI_API_KEY"
    assert plan.credential_ref == _CREDENTIAL_REF

    rendered = plan.home_config.to_toml()
    assert f'model = "{_MODEL}"' in rendered
    assert f'model_provider = "{_PROVIDER}"' in rendered
    assert f'base_url = "{_BASE_URL}"' in rendered
    assert 'wire_api = "responses"' in rendered
    assert 'env_key = "OPENAI_API_KEY"' in rendered
    assert "deepseek" not in rendered.lower()
    assert "CANARY" not in rendered

    # The real allowlist governs the resolved address; a connection was taken
    # from the injected engine and handed to Catalog.resolve().
    assert catalog.resolve_calls == [(_TENANT, _PROFILE_ID, 3, catalog.resolve_calls[0][3])]
    assert catalog.address_calls
    assert catalog.address_calls[0]["base_url"] == _BASE_URL
    assert catalog.address_calls[0]["protocol"] == "openai_compatible"


def test_resolution_accepts_an_explicit_connection_without_a_new_engine():
    class _NoConnectEngine:
        def connect(self):
            raise AssertionError("an explicit connection must not open a new one")

    resolver, _ = _resolver(_snapshot())
    resolver._engine = _NoConnectEngine()
    plan = asyncio.run(
        resolver.resolve(_TENANT, _PROFILE_ID, 1, "workspace-q3", connection=object())
    )
    assert plan.home_config.model == _MODEL


def test_provider_id_is_sanitized_from_the_connection_name():
    snap = _snapshot(connection_overrides={"name": "9 Qwen/Plus!"})
    resolver, _ = _resolver(snap)
    plan = asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 1))
    # A sanitized leading-digit name is prefixed with "p" and stays a valid id.
    provider = plan.home_config.model_provider
    assert provider.startswith("p")
    assert provider == "p9-qwen-plus-"
    assert f"[model_providers.{provider}]" in plan.home_config.to_toml()


# --------------------------------------------------------------------------- #
# 2. Per-connection transport overrides                                       #
# --------------------------------------------------------------------------- #


def test_codex_transport_overrides_are_honoured():
    snap = _snapshot(
        connection_overrides={
            "codex_base_url": "https://api.openai.com/v1",
            "codex_wire_api": "responses",
            "codex_model_provider": "openai",
        }
    )
    resolver, catalog = _resolver(snap)
    plan = asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 2))

    assert plan.home_config.base_url == "https://api.openai.com/v1"
    assert plan.home_config.wire_api == "responses"
    assert plan.home_config.model_provider == "openai"
    assert 'wire_api = "responses"' in plan.home_config.to_toml()
    assert 'base_url = "https://api.openai.com/v1"' in plan.home_config.to_toml()
    assert catalog.address_calls[0]["base_url"] == "https://api.openai.com/v1"


def test_chat_wire_api_is_rejected_by_resolution():
    """Codex 0.169+ removed ``chat``; it must not reach a published profile."""

    snap = _snapshot(connection_overrides={"codex_wire_api": "chat"})
    resolver, _ = _resolver(snap)
    with pytest.raises(CodexRouteError) as caught:
        asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 1))
    assert caught.value.code == "codex_wire_api_unsupported"


def test_resolver_rejects_a_non_bare_https_override():
    for bad in (
        "http://api.openai.com/v1",
        "https://api.openai.com/v1?model=x",
        "https://user:pw@api.openai.com/v1",
        "https://api.openai.com/v1#frag",
    ):
        snap = _snapshot(connection_overrides={"codex_base_url": bad})
        resolver, _ = _resolver(snap)
        with pytest.raises(CodexRouteError) as caught:
            asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 1))
        assert caught.value.code == "codex_host_not_allowed"


def test_connection_contract_validates_codex_transport_metadata():
    assert Connection(name="qwen").model_dump(mode="json")["codex_wire_api"] is None
    good = Connection(
        name="qwen",
        codex_base_url=_BASE_URL,
        codex_wire_api="responses",
        codex_model_provider=_PROVIDER,
        execution_credential_ref=_CREDENTIAL_REF,
    )
    assert good.execution_credential_ref == _CREDENTIAL_REF
    assert good.codex_model_provider == _PROVIDER
    for field, value in (
        ("codex_base_url", "http://x.example/v1"),
        ("codex_base_url", "https://x.example/v1?a=1"),
        ("codex_model_provider", "9bad"),
        ("codex_model_provider", "bad name"),
        ("codex_wire_api", "grpc"),
        ("codex_wire_api", "chat"),
        ("execution_credential_ref", "not-a-uuid"),
    ):
        with pytest.raises(ValidationError):
            Connection(name="qwen", **{field: value})


# --------------------------------------------------------------------------- #
# 3. Host allowlist / capability gates                                         #
# --------------------------------------------------------------------------- #


def test_host_outside_the_allowlist_is_rejected():
    snap = _snapshot(base_url="https://untrusted.example/v1")
    resolver, catalog = _resolver(snap)
    with pytest.raises(CodexRouteError) as caught:
        asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 1))
    assert caught.value.code == "codex_host_not_allowed"
    assert catalog.address_calls, "validate_address must still be consulted"
    # No secret material or address detail is echoed into the error.
    assert str(caught.value) == "codex_host_not_allowed"


def test_non_chat_profile_is_rejected():
    resolver, _ = _resolver(_snapshot(operation="embed"))
    with pytest.raises(CodexRouteError) as caught:
        asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 1))
    assert caught.value.code == "codex_profile_not_chat"


def test_route_without_tool_calling_is_rejected():
    resolver, _ = _resolver(_snapshot(tool_calling=False))
    with pytest.raises(CodexRouteError) as caught:
        asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 1))
    assert caught.value.code == "codex_profile_tool_calling"


def test_missing_tool_calling_flag_on_a_secondary_route_is_rejected():
    snap = _snapshot()
    snap["routes"].append({"model": {"model_name": "fallback"}})
    resolver, _ = _resolver(snap)
    with pytest.raises(CodexRouteError) as caught:
        asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 1))
    assert caught.value.code == "codex_route_missing"


def test_missing_routes_and_unresolvable_profile_are_rejected():
    resolver, _ = _resolver({"spec": {"operation": "chat"}, "routes": []})
    with pytest.raises(CodexRouteError) as caught:
        asyncio.run(resolver.resolve(_TENANT, _PROFILE_ID, 1))
    assert caught.value.code == "codex_route_missing"

    from agent_platform.core_platform.platform_services.persistence.store import DomainError

    class _MissingCatalog(_FakeCatalog):
        async def resolve(self, tenant, identifier, version, connection=None):
            raise DomainError("model_profile_version_not_found")

    missing = CodexProviderResolver(_FakeEngine(), _settings(), _MissingCatalog({}, _settings()))
    with pytest.raises(CodexRouteError) as caught:
        asyncio.run(missing.resolve(_TENANT, _PROFILE_ID, 99))
    assert caught.value.code == "codex_route_missing"


# --------------------------------------------------------------------------- #
# 4. Contract pairing + snapshot typed-field validation                        #
# --------------------------------------------------------------------------- #


def test_codex_config_requires_the_profile_pair_to_be_present_together():
    for kwargs in (
        {"model_profile_id": _PROFILE_ID},
        {"model_profile_version": 3},
    ):
        with pytest.raises(ValidationError, match="set together"):
            CodexConfig(version="0.169.0", **kwargs)  # type: ignore[arg-type]
    # The version lower bound is enforced by the field itself before the pair
    # validator runs.
    with pytest.raises(ValidationError):
        CodexConfig(version="0.169.0", model_profile_id=_PROFILE_ID, model_profile_version=0)
    paired = CodexConfig(version="0.169.0", model_profile_id=_PROFILE_ID, model_profile_version=3)
    assert paired.model_profile_id == _PROFILE_ID
    assert paired.model_profile_version == 3
    # The pair survives the AgentConfig projection used on publish.
    projected = normalize_execution_config(
        {
            "engine": _CODEX_ENGINE,
            "codex": {
                "version": "0.169.0",
                "model_profile_id": str(_PROFILE_ID),
                "model_profile_version": 3,
            },
        }
    )
    assert projected.codex.model_profile_id == _PROFILE_ID
    assert projected.codex.model_profile_version == 3


def test_snapshot_typed_fields_accept_the_pair_and_reject_tampering():
    assert {"model_profile_id", "model_profile_version"} <= _TYPED_CODEX_FIELDS

    def build(config):
        return serialize_snapshot(
            build_execution_config_snapshot(
                execution_id=uuid4(),
                config=config,
                agent_id=None,
                agent_version=None,
                provider_id="codex",
                provider_version="v1",
            )
        )

    legacy = normalize_execution_config({"engine": _CODEX_ENGINE, "codex": {"version": "0.169.0"}})
    legacy_payload = build(legacy)
    assert '"model_profile_id":null' in legacy_payload
    assert '"model_profile_version":null' in legacy_payload

    paired = normalize_execution_config(
        {
            "engine": _CODEX_ENGINE,
            "codex": {
                "version": "0.169.0",
                "model_profile_id": str(_PROFILE_ID),
                "model_profile_version": 3,
            },
        }
    )
    payload = build(paired)
    assert f'"model_profile_id":"{_PROFILE_ID}"' in payload
    assert '"model_profile_version":3' in payload
    body = json.loads(payload)
    # Both the serializer-root path and the stored-column prefix path accept it.
    assert_snapshot_payload_clean(body)
    assert_snapshot_payload_clean(body, ("execution_config_snapshot",))

    for bad in (True, 0, -1, "3", "CANARY_VALUE"):
        body["config"]["codex"]["model_profile_version"] = bad
        with pytest.raises(ExecutionSnapshotError):
            assert_snapshot_payload_clean(body, ("execution_config_snapshot",))
    body["config"]["codex"]["model_profile_version"] = 3
    for bad in ("sk-not-a-reference", "not-a-uuid", "/etc/passwd", 12):
        body["config"]["codex"]["model_profile_id"] = bad
        with pytest.raises(ExecutionSnapshotError):
            assert_snapshot_payload_clean(body, ("execution_config_snapshot",))
    body["config"]["codex"]["model_profile_id"] = str(uuid4())
    assert_snapshot_payload_clean(body, ("execution_config_snapshot",))


def test_empty_credential_ref_env_is_treated_as_absent(monkeypatch):
    monkeypatch.setenv("AGENT_CODEX_CREDENTIAL_REF", "")
    assert Settings(_env_file=None).codex_credential_ref is None
    monkeypatch.setenv("AGENT_CODEX_CREDENTIAL_REF", str(_CREDENTIAL_REF))
    assert Settings(_env_file=None).codex_credential_ref == _CREDENTIAL_REF


def test_all_codex_settings_stay_out_of_the_runtime_fingerprint():
    excluded = runtime_composition._runtime_fingerprint_exclude_fields()
    assert all(name in excluded for name in Settings.model_fields if name.startswith("codex_"))


# --------------------------------------------------------------------------- #
# 5. Legacy lane + adapter integration                                         #
# --------------------------------------------------------------------------- #


def test_legacy_lane_uses_published_credential_and_deployment_path(tmp_path: Path):
    """No profile pair => Settings home + codex.credential_ref + deployment PATH."""
    host = _RecordingHost()
    adapter = _adapter(
        host,
        tmp_path,
        config=CodexConfig(
            version="0.169.0",
            credential_ref=str(_PUBLISHED_CREDENTIAL_REF),
            path_env="/published/bin:/usr/bin",
        ),
        path_env="/opt/codex/node/bin:/usr/bin",
    )
    result = _start(adapter, tmp_path, workspace_id="workspace-q3")

    call, spec = result["call"], result["call"]["spec"]
    assert call["credential_ref"] == _PUBLISHED_CREDENTIAL_REF
    # Q5: deployment PATH wins over the published snapshot value.
    assert spec.environment["PATH"] == "/opt/codex/node/bin:/usr/bin"
    assert spec.credential_env_key == _LEGACY_HOME.env_key
    home = tmp_path / result["request"].execution_workdir / PRIVATE_ENGINE_HOME_NAME
    assert (home / "config.toml").read_text() == _LEGACY_HOME.to_toml()
    assert "qwen" not in (home / "config.toml").read_text()


def test_credential_ref_overrides_the_published_one_and_populates_audience(tmp_path: Path):
    host = _RecordingHost()
    adapter = _adapter(
        host,
        tmp_path,
        config=CodexConfig(version="0.169.0", credential_ref=str(_PUBLISHED_CREDENTIAL_REF)),
        credential_ref=_DEPLOYMENT_CREDENTIAL_REF,
        path_env="/opt/codex/node/bin:/usr/bin",
    )
    call = _start(adapter, tmp_path, workspace_id="workspace-q3")["call"]
    assert call["credential_ref"] == _DEPLOYMENT_CREDENTIAL_REF
    assert call["broker_audience"] == {
        "engine_id": "codex",
        "protocol_id": "cli_exec",
        "workspace_id": "workspace-q3",
    }
    assert call["spec"].environment["PATH"] == "/opt/codex/node/bin:/usr/bin"


def test_adapter_gateway_lane_uses_the_resolved_plan(tmp_path: Path):
    host = _RecordingHost()
    settings = _settings()
    resolver, catalog = _resolver(_snapshot(), settings)
    adapter = _adapter(
        host,
        tmp_path,
        config=CodexConfig(
            version="0.169.0",
            credential_ref=str(_PUBLISHED_CREDENTIAL_REF),
            model_profile_id=_PROFILE_ID,
            model_profile_version=3,
        ),
        provider_resolver=resolver,
        credential_ref=_DEPLOYMENT_CREDENTIAL_REF,
        path_env=settings.codex_path_env,
    )
    result = _start(adapter, tmp_path, workspace_id="workspace-q3")

    call, spec = result["call"], result["call"]["spec"]
    home = tmp_path / result["request"].execution_workdir / PRIVATE_ENGINE_HOME_NAME
    rendered = (home / "config.toml").read_text()
    assert f'model = "{_MODEL}"' in rendered
    assert f'model_provider = "{_PROVIDER}"' in rendered
    assert f'base_url = "{_BASE_URL}"' in rendered
    assert 'wire_api = "responses"' in rendered
    assert 'env_key = "OPENAI_API_KEY"' in rendered
    assert "deepseek" not in rendered.lower()
    assert spec.credential_env_key == "OPENAI_API_KEY"
    # The connection's reference wins over both the published and deployment refs.
    assert call["credential_ref"] == _CREDENTIAL_REF
    assert spec.environment["PATH"] == settings.codex_path_env
    assert catalog.resolve_calls[0][:3] == (_TENANT, _PROFILE_ID, 3)


def test_adapter_classifies_a_resolver_failure_instead_of_execution_error(tmp_path: Path):
    class _FailingResolver:
        async def resolve(self, tenant_id, profile_id, version, workspace_id):
            raise CodexRouteError("codex_host_not_allowed")

    host = _RecordingHost()
    adapter = _adapter(
        host,
        tmp_path,
        config=CodexConfig(
            version="0.169.0",
            model_profile_id=_PROFILE_ID,
            model_profile_version=1,
        ),
        provider_resolver=_FailingResolver(),
        path_env="/opt/codex/node/bin:/usr/bin",
    )
    request = _request(f"aa11/{uuid4()}")
    (tmp_path / request.execution_workdir).mkdir(parents=True, mode=0o700)
    with pytest.raises(ConfigurationError) as caught:
        asyncio.run(adapter.start(request))
    assert caught.value.error.code is ExecutionErrorCode.INVALID_REQUEST
    # _safe_legacy_code now yields a classified code, never the opaque fallback.
    assert _safe_legacy_code(caught.value) == "invalid_request"
    assert host.calls == []


def test_composition_threads_the_resolver_and_deployment_settings(monkeypatch):
    settings = _settings()
    resolver, _ = _resolver(_snapshot(), settings)
    (_, cli_factory), _ = runtime_composition._codex_adapters(
        settings, _RecordingHost(), None, resolver
    )
    context = SimpleNamespace(owner=None, lease_epoch=None, execution_id=uuid4(), history=[])
    published = SimpleNamespace(codex=CodexConfig(version="0.169.0"))
    monkeypatch.setattr(runtime_composition, "capture_execution_context", lambda: context)
    monkeypatch.setattr(
        runtime_composition, "execution_config_from_context", lambda _context: published
    )
    adapter = cli_factory()
    assert adapter._provider_resolver is resolver
    assert adapter._path_env == settings.codex_path_env
    assert adapter._credential_ref == settings.codex_credential_ref
    assert not hasattr(adapter, "_deployment_credential_ref")
