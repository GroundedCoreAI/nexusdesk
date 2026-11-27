"""Sample Skill seeding: idempotency and dependency honesty.

These run against an isolated tenant that has no model profile and no knowledge
base, which is the interesting case: the seed must still create every row and
report why none of them could be published, rather than pretending they are
releasable.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from test_platform_postgres import platform as _platform_fixture

from agent_platform.business_capabilities.skill_library.samples import SAMPLE_SKILLS
from agent_platform.business_capabilities.skill_library.seed import seed_sample_skills

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]
skill_platform_base = _platform_fixture


@pytest_asyncio.fixture
async def seeded_platform(skill_platform_base):
    client, services, settings = skill_platform_base
    try:
        yield client, services, settings
    finally:
        async with services.repository.engine.begin() as connection:
            for table in ("skill_packages", "skill_versions", "skill_test_runs", "skills"):
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id=:tenant"),
                    {"tenant": settings.tenant_id},
                )


async def test_seed_creates_every_sample_then_skips_on_rerun(seeded_platform):
    _client, services, settings = seeded_platform
    service = services.groups.business.skill_library

    first = await seed_sample_skills(service, settings.tenant_id)
    assert sorted(first["created"]) == sorted(sample.key for sample in SAMPLE_SKILLS)
    assert first["skipped"] == []

    second = await seed_sample_skills(service, settings.tenant_id)
    assert second["created"] == []
    assert sorted(second["skipped"]) == sorted(sample.key for sample in SAMPLE_SKILLS)

    async with services.repository.engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT skill_key,name,category,tags,status,weight_class,risk_level
                    FROM skills WHERE tenant_id=:tenant
                    """
                ),
                {"tenant": settings.tenant_id},
            )
        ).mappings().all()

    assert len(rows) == len(SAMPLE_SKILLS)
    by_key = {row["skill_key"]: row for row in rows}
    for sample in SAMPLE_SKILLS:
        row = by_key[sample.key]
        assert row["name"] == sample.name
        assert row["category"] == sample.category
        assert list(row["tags"]) == list(sample.tags)
        # No package means the weight class is a fact, not an opinion.
        assert row["weight_class"] == "declarative"


async def test_seed_without_dependencies_keeps_samples_as_drafts(seeded_platform):
    _client, services, settings = seeded_platform
    service = services.groups.business.skill_library

    report = await seed_sample_skills(service, settings.tenant_id)

    assert report["dependencies"] == {"model_profile": None, "knowledge_base": None}
    assert report["published"] == []
    expected_drafts = {sample.key for sample in SAMPLE_SKILLS}
    assert set(report["drafts"]) == expected_drafts
    reasons = {item["key"]: item["reason"] for item in report["failed"]}
    assert reasons["customer-intent-recognition"] == "model_profile_unavailable"
    assert reasons["order-info-query"] == "knowledge_base_unavailable"

    async with services.repository.engine.connect() as connection:
        statuses = {
            row[0]
            for row in (
                await connection.execute(
                    text("SELECT status FROM skills WHERE tenant_id=:tenant"),
                    {"tenant": settings.tenant_id},
                )
            ).all()
        }
        versions = (
            await connection.execute(
                text("SELECT count(*) FROM skill_versions WHERE tenant_id=:tenant"),
                {"tenant": settings.tenant_id},
            )
        ).scalar()

    assert statuses == {"draft"}
    # Nothing was published, so no version rows were invented either.
    assert versions == 0


async def test_dry_run_reports_without_writing(seeded_platform):
    _client, services, settings = seeded_platform
    service = services.groups.business.skill_library

    report = await seed_sample_skills(service, settings.tenant_id, dry_run=True)
    assert sorted(report["created"]) == sorted(sample.key for sample in SAMPLE_SKILLS)

    async with services.repository.engine.connect() as connection:
        count = (
            await connection.execute(
                text("SELECT count(*) FROM skills WHERE tenant_id=:tenant"),
                {"tenant": settings.tenant_id},
            )
        ).scalar()
    assert count == 0
