"""Shared pytest helpers for database gate enforcement and CI diagnostics."""

import os

import pytest


def _is_ci_or_strict() -> bool:
    return (
        os.environ.get("CI", "").lower() == "true"
        or os.environ.get("REQUIRE_POSTGRES_TESTS") == "1"
    )


def require_test_database_url() -> str:
    """Return TEST_DATABASE_URL, or fail closed in CI instead of silently skipping."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if url:
        return url
    message = "Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database"
    if _is_ci_or_strict():
        pytest.fail(f"Infrastructure configuration error: {message}")
    pytest.skip(message)


def require_migration_database_url() -> str:
    """Return MIGRATION_TEST_DATABASE_URL, or fail closed in CI instead of silently skipping."""
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL", "").strip()
    if url:
        return url
    message = "Requires a test PostgreSQL role with CREATEDB (MIGRATION_TEST_DATABASE_URL)"
    if _is_ci_or_strict():
        pytest.fail(f"Infrastructure configuration error: {message}")
    pytest.skip(message)
