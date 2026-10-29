"""Run from backend: python -m agent_platform.applications.init_local_admin"""

import asyncio
from getpass import getpass

from sqlalchemy.ext.asyncio import create_async_engine

from agent_platform.core_platform.platform_services.identity.local_admin import LocalAdmin
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


async def initialize(login, password):
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        return await LocalAdmin(engine, settings.tenant_id).initialize(login, password)
    finally:
        await engine.dispose()


def main():
    print("Create independent administrator. This disables anonymous development access.")
    login = input("Username (3-64 ASCII letters/digits/_.-): ").strip()
    password = getpass("Password (12-128 characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match; no changes made.")
    try:
        result = asyncio.run(initialize(login, password))
    except DomainError as exc:
        raise SystemExit(exc.code) from None
    print("Administrator created: " + result["username"] + " (" + result["id"] + ")")


if __name__ == "__main__":
    main()
