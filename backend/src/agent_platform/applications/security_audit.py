"""R-13: minimal security audit wiring for forged/escalating request faces.

03 §7.3 freezes the rule: a 422 by itself is **not** a security audit. This
module is the single place that turns a rejected management-plane request (Run
API, Agent API, execution preview) into one durable audit row. It reuses the
existing audit service and the trusted authentication context and records, by
design, only:

* the write time (the audit table's ``created_at``),
* the trusted tenant/actor/business/workspace — never anything read from the
  request body,
* the matched route template and a server-generated/canonical request id,
* the stable error category, and
* sanitized, stable field paths.

It never receives the request body, the parsed values, the exception object or
any header value, so it structurally cannot persist a secret; callers pass
already-sanitized strings. Audit failures are logged as exception metadata
only (never the request material) and never change the HTTP answer.
"""

import logging
import re
from uuid import uuid4

from asyncpg import PostgresError
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from agent_platform.core_platform.platform_services.persistence.store import audit

logger = logging.getLogger(__name__)

# The stable audit action shared by every face below (P3-IT-04 queries it).
REQUEST_REJECTION_ACTION = "security.request_rejected"

# Internal management surfaces where forged capability/policy fields and
# cross-scope probes matter (03 §7.3): the Agent management tree and the Run
# face. Everything else keeps the plain 422 without an audit row.
_AUDITED_PATH_PREFIXES = ("/api/v1/agents", "/api/v1/runs")

# Field paths and error categories are bounded and character-filtered because
# a rejected field *name* is still caller-controlled text.
_SAFE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_\-.:]{1,64}$")
_SAFE_ERROR_TYPE = re.compile(r"^[a-z_]{1,64}$")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
_MAX_FIELD_PATHS = 20
_MAX_PATH_LENGTH = 128

# Stable categories (never interpolated with user content).
CATEGORY_FORGED_OR_INVALID_BODY = "forged_or_invalid_request_body"
CATEGORY_AGENT_SCOPE_NOT_FOUND = "agent_scope_not_found"


def is_audited_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _AUDITED_PATH_PREFIXES)


def _route_template(request: Request) -> str:
    """The matched route template, never the concrete URL (values excluded)."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/api/v1"):
        return template[:_MAX_PATH_LENGTH]
    # A path that reaches this fallback did not match a known template; the
    # prefix allow-list already bounded it, and a UUID in it is not a secret,
    # but keep it short and character-filtered anyway.
    fallback = re.sub(r"[^A-Za-z0-9_/.\-]", "#", request.url.path)[:_MAX_PATH_LENGTH]
    return fallback


def _request_id(request: Request) -> str:
    """Reuse a well-formed ``X-Request-ID``; otherwise mint one server-side."""
    inbound = request.headers.get("x-request-id", "")
    return inbound if _SAFE_REQUEST_ID.fullmatch(inbound) else uuid4().hex


def sanitized_body_paths(errors: list[dict]) -> list[str]:
    """Body field paths from pydantic error entries, names only, never values.

    Each ``loc`` tail is a key path (string keys can be attacker-chosen names
    such as ``declared`` or arbitrary junk), so every segment passes a
    character/length filter and anything unusual collapses to ``#``.
    """
    paths: list[str] = []
    for error in errors:
        loc = error.get("loc") or ()
        if not loc or loc[0] != "body":
            continue
        segments: list[str] = []
        for part in loc[1:]:
            if isinstance(part, int):
                segments.append(f"[{part}]")
            elif isinstance(part, str) and _SAFE_PATH_SEGMENT.fullmatch(part):
                segments.append(part)
            else:
                segments.append("#")
        path = ".".join(("body", *segments))[:_MAX_PATH_LENGTH]
        if path not in paths:
            paths.append(path)
        if len(paths) >= _MAX_FIELD_PATHS:
            break
    return paths


def sanitized_error_types(errors: list[dict]) -> list[str]:
    return sorted(
        {
            str(error.get("type"))
            for error in errors
            if _SAFE_ERROR_TYPE.fullmatch(str(error.get("type") or ""))
        }
    )[:_MAX_FIELD_PATHS]


async def record_request_rejection(
    request: Request,
    *,
    category: str,
    field_paths: list[str],
    error_types: list[str] | None = None,
) -> None:
    """Persist one sanitized audit row for a rejected audited request.

    The trusted subject is whatever the authentication dependency already
    resolved onto ``request.state`` (captured by ``identity.access.principal``);
    an unauthenticated request never reaches validation-error territory at all,
    and if the capture is missing the row honestly records ``anonymous``.
    """
    services = getattr(request.app.state, "runtime", None)
    groups = getattr(services, "groups", None)
    runtime_services = getattr(groups, "runtime", None)
    engine = getattr(runtime_services, "engine", None)
    if engine is None:
        return
    principal = getattr(request.state, "principal", None)
    tenant = getattr(principal, "tenant", None) or getattr(
        getattr(request.app.state, "settings", None), "tenant_id", "unknown"
    )
    actor = getattr(principal, "actor", None) or "anonymous"
    try:
        async with engine.begin() as conn:
            await audit(
                conn,
                tenant,
                actor,
                REQUEST_REJECTION_ACTION,
                _route_template(request),
                category=category,
                request_id=_request_id(request),
                field_paths=list(field_paths)[:_MAX_FIELD_PATHS],
                error_types=list(error_types or [])[:_MAX_FIELD_PATHS],
            )
    except (SQLAlchemyError, PostgresError, OSError, TimeoutError):
        # The rejection answer must stay truthful while the audit outage is
        # visible in the log. Exception metadata only — the request body and
        # values were never in scope here.
        logger.exception("failed to audit rejected request: %s", category)
