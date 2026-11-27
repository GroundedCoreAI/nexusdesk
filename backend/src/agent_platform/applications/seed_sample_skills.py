"""Seed the sample Skill corpus.

Run from backend::

    python -m agent_platform.applications.seed_sample_skills --dry-run
    python -m agent_platform.applications.seed_sample_skills

Idempotent: existing ``skill_key`` rows are skipped, so it is safe to re-run
after a partial failure or a database restore. Samples whose dependency this
deployment lacks are created as drafts and named in the report.
"""

import argparse
import asyncio
import json

from agent_platform.applications.platform_runtime.runtime_composition import (
    runtime_services,
)
from agent_platform.business_capabilities.skill_library.seed import seed_sample_skills
from agent_platform.core_platform.platform_services.platform_settings.settings import (
    Settings,
)


async def seed(dry_run: bool) -> dict:
    settings = Settings()
    async with runtime_services(settings) as services:
        service = services.groups.business.skill_library
        return await seed_sample_skills(
            service,
            settings.tenant_id,
            dry_run=dry_run,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the sample Skills.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing anything.",
    )
    args = parser.parse_args()
    report = asyncio.run(seed(args.dry_run))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        print("\nSome samples could not be published; see failed reasons above.")


if __name__ == "__main__":
    main()
