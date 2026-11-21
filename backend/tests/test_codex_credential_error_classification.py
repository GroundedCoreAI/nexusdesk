"""Issue #165: a Broker grant denial must not degrade to ``execution_error``.

The Codex CLI lane resolves its secret through the Execution Credential Broker.
A stale, revoked, rotated-out or out-of-scope ``credential_ref`` is refused by
``CredentialGrantDenied``, which inherits ``RuntimeError`` rather than
``AdapterExecutionError``. Historically ``_safe_legacy_code`` therefore returned
the sanitized legacy code ``execution_error`` and the acceptance console showed
an untranslated raw code, hiding the real configuration cause.

These tests pin the classification boundary without a database, a Runtime Host
or a running Codex binary.
"""

from agent_platform.core_platform.agent_execution.contracts import (
    ConfigurationError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
)
from agent_platform.core_platform.agent_execution.contracts.errors import (
    RUN_CODE_CREDENTIAL_UNAVAILABLE,
)
from agent_platform.core_platform.agent_execution.credentials.broker import (
    CredentialGrantDenied,
)
from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
    _safe_legacy_code,
)


def _configuration_error(code: ExecutionErrorCode) -> ConfigurationError:
    return ConfigurationError(ExecutionError(category=ExecutionErrorCategory.CONFIGURATION_ERROR, code=code))


def test_broker_denial_is_classified_as_credential_unavailable() -> None:
    """Every Broker denial reason maps to one stable, secret-free Run code."""
    for reason in (
        "credential_not_found",
        "credential_revoked",
        "credential_superseded",
        "engine_denied",
        "workspace_denied",
        "grant_replayed",
    ):
        exception = CredentialGrantDenied(reason)
        assert _safe_legacy_code(exception) == RUN_CODE_CREDENTIAL_UNAVAILABLE
        assert _safe_legacy_code(exception) != "execution_error"


def test_denial_reason_never_leaks_into_the_run_code() -> None:
    """The reason stays in the audit table; the Run payload stays opaque."""
    code = _safe_legacy_code(CredentialGrantDenied("credential_not_found"))
    assert "credential_not_found" not in code
    assert "secret" not in code
    assert code == "execution_credential_unavailable"


def test_gate_denials_keep_their_existing_classification() -> None:
    """Stage-A gate refusals must not be reclassified by the new branch."""
    assert (
        _safe_legacy_code(_configuration_error(ExecutionErrorCode.ADAPTER_DISABLED))
        == "adapter_disabled"
    )
    assert (
        _safe_legacy_code(_configuration_error(ExecutionErrorCode.PROTOCOL_DISABLED))
        == "protocol_disabled"
    )


def test_unrelated_exceptions_still_sanitize_to_execution_error() -> None:
    """The wide boundary remains fail-closed for genuine internal faults."""
    assert _safe_legacy_code(RuntimeError("provider error with customer data")) == "execution_error"
    assert _safe_legacy_code(ValueError("bad payload")) == "execution_error"
