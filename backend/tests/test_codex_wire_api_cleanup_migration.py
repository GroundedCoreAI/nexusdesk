"""The 0074 migration removes legacy ``codex_wire_api="chat"`` without touching other data."""

import json
from uuid import uuid4

import pytest
from test_ticket_migrations import migrate, query
from test_ticket_migrations import migration_database as _migration_database

pytestmark = pytest.mark.postgres
migration_database = _migration_database

TENANT = "codex-wire-cleanup-test"


def _insert_connection(url, spec):
    identifier = uuid4()
    query(
        url,
        "INSERT INTO gateway_connections(id,tenant_id,name,spec,revision) "
        "VALUES($1,$2,$3,CAST($4 AS jsonb),5)",
        identifier,
        TENANT,
        "channel",
        json.dumps(spec),
    )
    return identifier


def _insert_profile_version(url, profile_id, version, routes):
    snapshot = {"spec": {"operation": "chat"}, "routes": routes}
    query(
        url,
        "INSERT INTO gateway_profile_versions(profile_id,version,snapshot) "
        "VALUES($1,$2,CAST($3 AS jsonb))",
        profile_id,
        version,
        json.dumps(snapshot),
    )


def _conn_spec(wire):
    spec = {
        "name": "c",
        "protocol": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "execution_credential_ref": "6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f",
    }
    if wire is not None:
        spec["codex_wire_api"] = wire
    return spec


def _route(wire):
    connection = _conn_spec(wire)
    return {"model_id": str(uuid4()), "model": {"model_name": "deepseek-flash"},
            "connection_id": str(uuid4()), "connection": connection}


def test_0074_cleans_chat_in_connection_and_snapshot_and_is_idempotent(migration_database):
    url = migration_database
    migrate(url, "head")

    chat_conn = _insert_connection(url, _conn_spec("chat"))
    responses_conn = _insert_connection(url, _conn_spec("responses"))
    no_key_conn = _insert_connection(url, _conn_spec(None))

    profile_id = uuid4()
    query(
        url,
        "INSERT INTO gateway_profiles(id,tenant_id,name,spec) "
        "VALUES($1,$2,$3,CAST($4 AS jsonb))",
        profile_id, TENANT, "profile",
        json.dumps({"operation": "chat", "model_id": str(uuid4()), "fallback_model_ids": []}),
    )
    _insert_profile_version(url, profile_id, 1, [_route("chat"), _route("responses"), _route(None)])
    _insert_profile_version(url, profile_id, 2, [_route("chat")])

    # Run the migration from the previous head to the new one.
    migrate(url, "0073_execution_parser_diag", "downgrade")
    migrate(url, "head")

    def connection_spec(identifier):
        return json.loads(query(url, "SELECT spec FROM gateway_connections WHERE id=$1", identifier)[0][0])

    assert connection_spec(chat_conn)["codex_wire_api"] == "responses"
    assert connection_spec(responses_conn)["codex_wire_api"] == "responses"
    assert "codex_wire_api" not in connection_spec(no_key_conn)
    # Revision advanced once, other fields untouched.
    row = query(url, "SELECT revision,name,spec FROM gateway_connections WHERE id=$1", chat_conn)[0]
    assert row[0] == 6
    assert row[1] == "channel"
    assert json.loads(row[2])["base_url"] == "https://api.deepseek.com/v1"

    def snapshot(profile_id, version):
        return json.loads(
            query(url, "SELECT snapshot FROM gateway_profile_versions WHERE profile_id=$1 AND version=$2",
                  profile_id, version)[0][0]
        )

    routes = snapshot(profile_id, 1)["routes"]
    assert [r["connection"].get("codex_wire_api") for r in routes] == ["responses", "responses", None]
    assert snapshot(profile_id, 2)["routes"][0]["connection"]["codex_wire_api"] == "responses"
    # Version numbers and model data are preserved.
    assert [r[0] for r in query(
        url, "SELECT version FROM gateway_profile_versions WHERE profile_id=$1 ORDER BY version",
        profile_id)] == [1, 2]
    assert routes[0]["model"] == {"model_name": "deepseek-flash"}

    # Idempotent: re-running leaves every value unchanged.
    before = [connection_spec(i) for i in (chat_conn, responses_conn, no_key_conn)]
    migrate(url, "0073_execution_parser_diag", "downgrade")
    migrate(url, "head")
    assert [connection_spec(i) for i in (chat_conn, responses_conn, no_key_conn)] == before
    assert [r["connection"].get("codex_wire_api") for r in snapshot(profile_id, 1)["routes"]] == [
        "responses", "responses", None]
