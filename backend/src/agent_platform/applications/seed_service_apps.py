"""Install or refresh the immutable skill-centric service application examples.

The seed is idempotent and honors ``AGENT_SERVICE_APP_EXAMPLES_ENABLED``. It
uses the first published Agent in the configured scope, refreshes outdated
code-owned examples by template version, and never updates a user's copied
application.

    python -m agent_platform.applications.seed_service_apps
"""

import asyncio

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


async def main() -> None:
    settings = Settings()
    if not settings.service_app_examples_enabled:
        print("Service application examples are disabled; nothing to seed.")
        return
    async with runtime_services(settings) as runtime:
        result = await runtime.groups.business.service_apps.seed_defaults(
            settings.tenant_id,
            actor="seed-service-apps",
        )
    print(
        "Service application examples ready for tenant "
        f"{settings.tenant_id}: {result['applications']} installed."
    )


if __name__ == "__main__":
    asyncio.run(main())
