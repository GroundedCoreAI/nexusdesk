"""Phase 1: UI-managed model egress hosts (public HTTPS only)."""

import asyncio

import pytest

from agent_platform.core_platform.platform_services.model_gateway import host_allowlist
from agent_platform.core_platform.platform_services.model_gateway.catalog import Catalog
from agent_platform.core_platform.platform_services.model_gateway.host_allowlist import (
    HostAllowlistStore,
    normalize_public_host,
    resolve_public,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

_PUBLIC_IP = "93.184.216.34"


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        model_gateway_allowed_hosts=["api.openai.com"],
        **overrides,
    )


def _spec(host: str) -> dict:
    return {"protocol": "openai_compatible", "base_url": f"https://{host}/v1"}


class _FakeHosts:
    """Catalog-facing store double; resolution is configurable per test."""

    resolver = staticmethod(lambda host: (_PUBLIC_IP,))

    def __init__(self, managed=(), *, enabled=True, ips=(_PUBLIC_IP,)) -> None:
        self.managed = frozenset(managed)
        self._enabled = enabled
        self.ips = tuple(ips)
        self.resolved: list[str] = []

    def enabled(self) -> bool:
        return self._enabled

    async def effective(self, tenant: str) -> frozenset[str]:
        return self.managed

    async def ensure_resolution(self, host: str) -> tuple[str, ...]:
        self.resolved.append(host)
        return await resolve_public(host, resolver=lambda _: self.ips)


# --------------------------------------------------------------------------- #
# Normalization                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("www.duckcoding.ai", "www.duckcoding.ai"),
        ("  WWW.DuckCoding.AI.  ", "www.duckcoding.ai"),
        ("https://www.duckcoding.ai", "www.duckcoding.ai"),
        ("https://www.duckcoding.ai/v1/chat", "www.duckcoding.ai"),
    ],
)
def test_normalize_public_host_accepts_public_https_names(raw: str, expected: str) -> None:
    assert normalize_public_host(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "http://www.duckcoding.ai",
        "https://user:pw@www.duckcoding.ai",
        "https://www.duckcoding.ai/v1?x=1",
        "https://www.duckcoding.ai/v1#frag",
        "*",
        "www.*.ai",
        "localhost",
        "intranet",
        "https://[::1]",
    ],
)
def test_normalize_public_host_rejects_non_public_shapes(raw: str) -> None:
    with pytest.raises(DomainError) as caught:
        normalize_public_host(raw)
    assert caught.value.code in {"model_host_invalid", "model_host_not_public"}


@pytest.mark.parametrize(
    "raw", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "metadata.google.internal"]
)
def test_normalize_public_host_rejects_private_and_metadata(raw: str) -> None:
    with pytest.raises(DomainError) as caught:
        normalize_public_host(raw)
    assert caught.value.code == "model_host_not_public"


# --------------------------------------------------------------------------- #
# Resolution                                                                  #
# --------------------------------------------------------------------------- #


def test_resolve_public_accepts_public_addresses() -> None:
    assert asyncio.run(resolve_public("example.com", resolver=lambda _: (_PUBLIC_IP,))) == (
        _PUBLIC_IP,
    )


def test_resolve_public_rejects_private_resolution() -> None:
    with pytest.raises(DomainError) as caught:
        asyncio.run(resolve_public("example.com", resolver=lambda _: ("192.168.1.5",)))
    assert caught.value.code == "model_host_not_public"


def test_resolve_public_rejects_empty_or_failed_resolution() -> None:
    with pytest.raises(DomainError) as caught:
        asyncio.run(resolve_public("example.com", resolver=lambda _: ()))
    assert caught.value.code == "model_host_unresolved"

    def _fail(_: str):
        raise OSError("dns down")

    with pytest.raises(DomainError) as caught:
        asyncio.run(resolve_public("example.com", resolver=_fail))
    assert caught.value.code == "model_host_unresolved"


# --------------------------------------------------------------------------- #
# Effective allowlist                                                         #
# --------------------------------------------------------------------------- #


def test_env_host_stays_allowed_without_resolution() -> None:
    hosts = _FakeHosts(enabled=False)
    catalog = Catalog(None, _settings(), hosts=hosts)

    asyncio.run(catalog.validate_effective_address("t", _spec("api.openai.com")))
    assert hosts.resolved == []


def test_managed_host_is_allowed_only_when_enabled() -> None:
    enabled = _FakeHosts({"www.duckcoding.ai"}, enabled=True)
    asyncio.run(
        Catalog(None, _settings(), hosts=enabled).validate_effective_address(
            "t", _spec("www.duckcoding.ai")
        )
    )
    assert enabled.resolved == ["www.duckcoding.ai"]

    disabled = _FakeHosts({"www.duckcoding.ai"}, enabled=False)
    with pytest.raises(DomainError) as caught:
        asyncio.run(
            Catalog(None, _settings(), hosts=disabled).validate_effective_address(
                "t", _spec("www.duckcoding.ai")
            )
        )
    assert caught.value.code == "model_address_not_allowed"
    assert disabled.resolved == []


def test_managed_host_must_resolve_public() -> None:
    hosts = _FakeHosts({"www.duckcoding.ai"}, ips=("10.0.0.7",))
    with pytest.raises(DomainError) as caught:
        asyncio.run(
            Catalog(None, _settings(), hosts=hosts).validate_effective_address(
                "t", _spec("www.duckcoding.ai")
            )
        )
    assert caught.value.code == "model_host_not_public"


def test_managed_host_does_not_bypass_shape_checks() -> None:
    hosts = _FakeHosts({"www.duckcoding.ai"})
    with pytest.raises(DomainError):
        asyncio.run(
            Catalog(None, _settings(), hosts=hosts).validate_effective_address(
                "t", {"protocol": "openai_compatible", "base_url": "http://www.duckcoding.ai/v1"}
            )
        )


# --------------------------------------------------------------------------- #
# Store (DB helpers monkeypatched; no Postgres needed)                        #
# --------------------------------------------------------------------------- #


class _Conn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None


class _Engine:
    def connect(self):
        return _Conn()

    def begin(self):
        return _Conn()


async def _public_resolution(host, *, resolver=None):
    return (_PUBLIC_IP,)


def test_store_rejects_mutation_when_disabled(monkeypatch) -> None:
    store = HostAllowlistStore(_Engine(), _settings(model_gateway_ui_allowed_hosts=False))

    with pytest.raises(DomainError) as caught:
        asyncio.run(store.add("t", "admin", "www.duckcoding.ai"))
    assert caught.value.code == "model_host_management_disabled"

    with pytest.raises(DomainError) as caught:
        asyncio.run(store.remove("t", "admin", "www.duckcoding.ai"))
    assert caught.value.code == "model_host_management_disabled"


def test_store_caches_managed_hosts_and_invalidates_on_write(monkeypatch) -> None:
    rows = [{"host": "a.example.com"}]
    calls: list[str] = []

    async def fake_many(conn, sql, **params):
        calls.append(sql)
        return rows

    async def fake_one(conn, sql, **params):
        rows.append({"host": params["h"]})
        return {"host": params["h"], "created_by": "admin", "created_at": None}

    async def fake_audit(*args, **kwargs):
        return None

    async def fake_execute(*args, **kwargs):
        return None

    monkeypatch.setattr(host_allowlist, "many", fake_many)
    monkeypatch.setattr(host_allowlist, "one", fake_one)
    monkeypatch.setattr(host_allowlist, "audit", fake_audit)
    monkeypatch.setattr(host_allowlist, "execute", fake_execute)
    monkeypatch.setattr(
        host_allowlist,
        "resolve_public",
        lambda host, resolver=None: asyncio.sleep(0, result=(_PUBLIC_IP,)),
    )
    store = HostAllowlistStore(_Engine(), _settings(model_gateway_ui_allowed_hosts=True), ttl=60)

    assert asyncio.run(store.effective("t")) == frozenset({"a.example.com"})
    assert asyncio.run(store.effective("t")) == frozenset({"a.example.com"})
    assert len(calls) == 1

    asyncio.run(store.add("t", "admin", "b.example.com"))
    assert asyncio.run(store.effective("t")) == frozenset({"a.example.com", "b.example.com"})
    assert len(calls) == 2


def test_store_remove_missing_host_is_not_found(monkeypatch) -> None:
    async def fake_one(*args, **kwargs):
        return None

    monkeypatch.setattr(host_allowlist, "one", fake_one)
    monkeypatch.setattr(host_allowlist, "resolve_public", _public_resolution)
    store = HostAllowlistStore(_Engine(), _settings(model_gateway_ui_allowed_hosts=True))

    with pytest.raises(DomainError) as caught:
        asyncio.run(store.remove("t", "admin", "missing.example.com"))
    assert caught.value.code == "model_host_not_found"
