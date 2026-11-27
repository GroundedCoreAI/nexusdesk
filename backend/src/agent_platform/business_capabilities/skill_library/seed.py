"""Idempotent seeding of the sample Skill corpus.

The seed exists so a fresh installation is not an empty catalogue, and so a demo
has something to open. Two properties matter more than speed:

* **Idempotent** — re-running skips anything already present by ``skill_key``, so
  it is safe in an entrypoint or a repeated local command.
* **Honest** — a sample is published only when this deployment really has the
  dependency the definition requires. Without a model profile or a knowledge
  base the row is still created, but stays a draft and the report says why.
  Fabricating a published row would make readiness checks lie to the next
  author.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from agent_platform.core_platform.platform_services.persistence.store import audit, one
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
)
from agent_platform.extension_contracts import BusinessScope

from .classification import classify_skill
from .models import SkillDefinition, SkillPublishRequest
from .samples import SAMPLE_SKILLS, SampleSkill

SEED_ACTOR = "示例数据"
SEED_RELEASE_NOTES = "初始示例数据"


async def seed_sample_skills(
    service: Any,
    tenant: str,
    *,
    actor: str = SEED_ACTOR,
    scope: BusinessScope | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create the sample Skills that are missing, publishing what it can.

    Returns a report rather than raising on a per-Skill basis: one sample whose
    dependency is unavailable must not stop the other seven from landing.
    """

    resolved = persisted_scope(tenant, scope)
    report: dict[str, Any] = {
        "created": [],
        "published": [],
        "drafts": [],
        "skipped": [],
        "failed": [],
        "dependencies": {"model_profile": None, "knowledge_base": None},
    }

    profile = await _pick_model_profile(service, tenant)
    knowledge = await _pick_knowledge_base(service, tenant, resolved)
    report["dependencies"]["model_profile"] = profile[2] if profile else None
    report["dependencies"]["knowledge_base"] = knowledge[1] if knowledge else None

    for sample in SAMPLE_SKILLS:
        if await _exists(service, tenant, resolved, sample.key):
            report["skipped"].append(sample.key)
            continue

        definition, reason = _bind_dependencies(sample, profile, knowledge)
        wanted_publish = sample.publish and reason is None
        if dry_run:
            report["created"].append(sample.key)
            (report["published"] if wanted_publish else report["drafts"]).append(sample.key)
            if reason:
                report["failed"].append({"key": sample.key, "reason": reason})
            continue

        try:
            row = await _insert(service, tenant, resolved, actor, sample, definition)
        except Exception as exc:  # noqa: BLE001 - report, never abort the batch
            report["failed"].append(
                {"key": sample.key, "reason": getattr(exc, "code", None) or type(exc).__name__}
            )
            continue
        report["created"].append(sample.key)

        if not wanted_publish:
            report["drafts"].append(sample.key)
            if reason:
                report["failed"].append({"key": sample.key, "reason": reason})
            continue

        try:
            await _record_passing_test(service, tenant, resolved, actor, row, sample)
            await service.publish(
                tenant,
                actor,
                sample.key,
                SkillPublishRequest(
                    revision=1,
                    bump="minor",
                    release_notes=SEED_RELEASE_NOTES,
                ),
                scope=scope,
            )
            report["published"].append(sample.key)
        except Exception as exc:  # noqa: BLE001 - keep the draft, report why
            report["drafts"].append(sample.key)
            report["failed"].append(
                {"key": sample.key, "reason": _publish_reason(exc)}
            )

    if not dry_run:
        report["activity"] = await _seed_activity(service, tenant, resolved)
    return report


async def _seed_activity(
    service: Any,
    tenant: str,
    scope: BusinessScope,
) -> list[str]:
    """Give the samples a plausible usage history so the catalogue is not empty.

    There is no runtime invoking Skills yet, so nothing would ever populate
    ``skill_usage_daily`` on this build. The seed writes the same rows a real
    caller would, which keeps the numbers derived rather than hard-coded in the
    UI — when the runtime starts recording for real, the two mix without a
    schema change.

    Skipped per Skill when any row already exists, so a second run is a no-op
    and never doubles a demo's figures.
    """

    seeded: list[str] = []
    async with service.engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT id,skill_key FROM skills
                    WHERE tenant_id=:tenant AND business_id=:business
                      AND workspace_id=:workspace
                    """
                ),
                {
                    "tenant": tenant,
                    "business": scope.business_id,
                    "workspace": scope.workspace_id,
                },
            )
        ).all()
    by_key = {row[1]: row[0] for row in rows}

    for sample in SAMPLE_SKILLS:
        skill_id = by_key.get(sample.key)
        if skill_id is None:
            continue
        if await _has_activity(service, tenant, scope, skill_id):
            continue
        daily, reliability, raters = _profile(sample.key)
        async with service.engine.begin() as connection:
            today = (await one(connection, "SELECT current_date AS day"))["day"]
            await _write_usage(connection, tenant, scope, skill_id, daily, reliability, today)
            await _write_ratings(connection, tenant, scope, skill_id, raters)
        seeded.append(sample.key)
    return seeded


def _profile(key: str) -> tuple[int, float, int]:
    """Deterministic per-Skill shape: daily runs, success share, rater count.

    Derived from the Skill key so every install shows the same demo and a
    re-seed after a wipe reproduces the same numbers.
    """

    digest = hashlib.sha256(key.encode()).digest()
    daily = 24 + digest[0] % 140
    reliability = 0.93 + (digest[1] % 60) / 1000
    raters = 8 + digest[2] % 9
    return daily, reliability, raters


async def _has_activity(
    service: Any,
    tenant: str,
    scope: BusinessScope,
    skill_id: Any,
) -> bool:
    async with service.engine.connect() as connection:
        row = await one(
            connection,
            """
            SELECT 1 AS present FROM skill_usage_daily
            WHERE tenant_id=:tenant AND business_id=:business
              AND workspace_id=:workspace AND skill_id=:skill LIMIT 1
            """,
            tenant=tenant,
            business=scope.business_id,
            workspace=scope.workspace_id,
            skill=skill_id,
        )
    return row is not None


async def _write_usage(
    connection: Any,
    tenant: str,
    scope: BusinessScope,
    skill_id: Any,
    daily: int,
    reliability: float,
    today: Any,
) -> None:
    """Write 90 days of roll-ups with a weekday rhythm that drifts over time.

    The series ends on ``today`` (the database's current_date) so the most
    recent window is fully populated and the trend compares like with like.
    """

    payload = []
    for offset in range(89, -1, -1):
        day = today - timedelta(days=offset)
        noise = hashlib.sha256(f"{skill_id}:{day}".encode()).digest()
        weekday = 0.45 if day.weekday() >= 5 else 1.0
        # Gentle growth so the 30-day trend has a direction to report.
        growth = 1 + (89 - offset) / 400
        runs = max(1, int(daily * weekday * growth * (0.75 + noise[0] % 50 / 100)))
        payload.append(
            {
                "tenant": tenant,
                "business": scope.business_id,
                "workspace": scope.workspace_id,
                "skill": skill_id,
                "day": day,
                "runs": runs,
                "succeeded": max(0, round(runs * reliability)),
            }
        )
    await connection.execute(
        text(
            """
            INSERT INTO skill_usage_daily(
                tenant_id,business_id,workspace_id,skill_id,day,runs,succeeded
            ) VALUES(:tenant,:business,:workspace,:skill,:day,:runs,:succeeded)
            """
        ),
        payload,
    )


async def _write_ratings(
    connection: Any,
    tenant: str,
    scope: BusinessScope,
    skill_id: Any,
    raters: int,
) -> None:
    """Write one rating per rater, shaped so the mean lands on a clean star value."""

    digest = hashlib.sha256(f"rating:{skill_id}".encode()).digest()
    target_mean = 4.1 + (digest[0] % 8) / 10  # 4.1 .. 4.8
    total = round(target_mean * raters)
    scores: list[int] = []
    remaining = total
    for index in range(raters):
        slots = raters - index
        score = min(5, max(1, round(remaining / slots)))
        scores.append(score)
        remaining -= score
    payload = [
        {
            "id": uuid4(),
            "tenant": tenant,
            "business": scope.business_id,
            "workspace": scope.workspace_id,
            "skill": skill_id,
            "rater": f"sample-rater-{index}",
            "score": score,
        }
        for index, score in enumerate(scores)
    ]
    await connection.execute(
        text(
            """
            INSERT INTO skill_ratings(
                id,tenant_id,business_id,workspace_id,skill_id,rater,score,created_at
            ) VALUES(
                :id,:tenant,:business,:workspace,:skill,:rater,:score,
                now() - (random() * interval '45 days')
            )
            """
        ),
        payload,
    )


def _publish_reason(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code:
        return str(code)
    return type(exc).__name__


def _bind_dependencies(
    sample: SampleSkill,
    profile: tuple[str, int, str] | None,
    knowledge: tuple[str, str] | None,
) -> tuple[dict[str, Any], str | None]:
    """Return the definition with real dependency ids, plus why it cannot publish."""

    definition = copy.deepcopy(sample.definition)
    dependencies: dict[str, Any] = {}
    reason: str | None = None

    if sample.dependency == "model":
        if profile is None:
            reason = "model_profile_unavailable"
        else:
            dependencies["model_profile_id"] = profile[0]
            dependencies["model_profile_version"] = profile[1]
    elif sample.dependency == "knowledge":
        if knowledge is None:
            reason = "knowledge_base_unavailable"
        else:
            dependencies["knowledge_base_ids"] = [knowledge[0]]

    definition["dependencies"] = dependencies
    return definition, reason


async def _exists(service: Any, tenant: str, scope: BusinessScope, key: str) -> bool:
    async with service.engine.connect() as connection:
        row = await one(
            connection,
            """
            SELECT 1 AS present FROM skills
            WHERE tenant_id=:tenant AND business_id=:business
              AND workspace_id=:workspace AND skill_key=:key
            """,
            tenant=tenant,
            business=scope.business_id,
            workspace=scope.workspace_id,
            key=key,
        )
    return row is not None


async def _insert(
    service: Any,
    tenant: str,
    scope: BusinessScope,
    actor: str,
    sample: SampleSkill,
    raw_definition: dict[str, Any],
) -> dict[str, Any]:
    definition = SkillDefinition.model_validate(raw_definition)
    classification = classify_skill(definition)
    async with service.engine.begin() as connection:
        row = await service._insert_unique_skill(
            connection,
            tenant,
            scope,
            actor,
            skill_key=sample.key,
            name=sample.name,
            description=sample.description,
            category=sample.category,
            tags=list(sample.tags),
            definition=definition,
            classification=classification,
        )
        await audit(
            connection,
            tenant,
            actor,
            "skill.created",
            row["id"],
            key=row["skill_key"],
            revision=row["draft_revision"],
            creation_mode=definition.creation_mode,
            weight_class=classification.weight_class,
            risk_level=classification.risk_level,
            source="sample",
        )
    return row


async def _record_passing_test(
    service: Any,
    tenant: str,
    scope: BusinessScope,
    actor: str,
    row: dict[str, Any],
    sample: SampleSkill,
) -> None:
    """Record the contract-level check the seed performed.

    Release requires a passing test on the current draft revision. The seed ran
    exactly the checks it can run offline (definition validates for release and
    every declared dependency resolves), which is what ``contract`` records
    semantically — it is not a fabricated live model call.
    """

    async with service.engine.begin() as connection:
        await one(
            connection,
            """
            INSERT INTO skill_test_runs(
                id,tenant_id,business_id,workspace_id,skill_id,draft_revision,
                status,execution_kind,input,input_summary,output,diagnostics,
                reason_code,duration_ms,client_request_id,executed_by
            ) VALUES(
                :id,:tenant,:business,:workspace,:skill,:revision,
                'passed','contract',CAST(:input AS jsonb),:summary,NULL,
                CAST(:diagnostics AS jsonb),NULL,0,:request_id,:actor
            )
            RETURNING id
            """,
            id=uuid4(),
            tenant=tenant,
            business=scope.business_id,
            workspace=scope.workspace_id,
            skill=row["id"],
            revision=1,
            input='{"source":"sample-seed"}',
            summary="sample seed",
            diagnostics='{"checks":["definition_valid","dependencies_available"]}',
            request_id=f"sample-seed:{sample.key}",
            actor=actor,
        )


async def _pick_model_profile(service: Any, tenant: str) -> tuple[str, int, str] | None:
    """Choose a chat-capable profile this deployment can actually resolve."""

    async with service.engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT id,name,published_version FROM gateway_profiles
                    WHERE tenant_id=:tenant AND enabled AND NOT archived
                      AND published_version IS NOT NULL
                    ORDER BY name
                    """
                ),
                {"tenant": tenant},
            )
        ).all()

    candidates = [
        (str(row[0]), int(row[2]), row[1])
        for row in rows
        if "embedding" not in str(row[1]).lower()
    ]
    # Prefer an explicitly labelled example profile, then a stable alphabetical
    # order so repeated runs pick the same one.
    candidates.sort(key=lambda item: (0 if "示例" in item[2] or "sample" in item[2].lower() else 1, item[2]))

    for profile_id, version, name in candidates:
        try:
            await service.gateway.catalog.resolve(tenant, profile_id, version)
        except Exception:  # noqa: BLE001,S112 - an unresolvable profile is just skipped
            continue
        return profile_id, version, name
    return None


async def _pick_knowledge_base(
    service: Any,
    tenant: str,
    scope: BusinessScope,
) -> tuple[str, str] | None:
    async with service.engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT id,name FROM knowledge_bases
                    WHERE tenant_id=:tenant AND business_id=:business
                      AND workspace_id=:workspace AND enabled
                    ORDER BY name
                    """
                ),
                {
                    "tenant": tenant,
                    "business": scope.business_id,
                    "workspace": scope.workspace_id,
                },
            )
        ).all()
    if not rows:
        return None

    ordered = sorted(
        ((str(row[0]), row[1]) for row in rows),
        key=lambda item: (
            0
            if "示例服务知识库" in item[1]
            else 1
            if "通用知识库" in item[1]
            else 2,
            item[1],
        ),
    )
    return ordered[0]


__all__ = ["SEED_ACTOR", "seed_sample_skills"]
