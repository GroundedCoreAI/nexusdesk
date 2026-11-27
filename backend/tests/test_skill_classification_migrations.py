import json
from uuid import uuid4

import pytest
from test_ticket_migrations import migrate, query
from test_ticket_migrations import migration_database as _migration_database

migration_database = _migration_database
pytestmark = pytest.mark.postgres


def insert_skill(url, key, definition):
    query(
        url,
        """INSERT INTO skills(id,tenant_id,business_id,workspace_id,skill_key,name,
        category,draft_definition,created_by,updated_by)
        VALUES($1,'demo','customer-service','default',$2,'Seed Skill','general',
        $3::jsonb,'tester','tester')""",
        uuid4(),
        key,
        json.dumps(definition),
    )


def test_classification_backfill_and_reversibility(migration_database):
    url = migration_database
    migrate(url, "0076_skill_library")
    insert_skill(
        url,
        "refund-action",
        {
            "type": "action",
            "dependencies": {"tool_names": ["refund_order"]},
            "runtime": {"max_amount": 12000},
        },
    )
    insert_skill(
        url,
        "plain-reply",
        {"type": "instruction", "dependencies": {}, "runtime": {}},
    )

    migrate(url, "head")
    rows = {
        row[0]: row
        for row in query(
            url,
            "SELECT skill_key,weight_class,risk_level,data_scope FROM skills",
        )
    }
    assert rows["refund-action"][1] == "declarative"
    assert rows["refund-action"][2] == "r3"
    assert set(rows["refund-action"][3]) == {"money", "tool"}
    assert rows["plain-reply"][2] == "r0"
    assert rows["plain-reply"][3] == []

    migrate(url, "0076_skill_library", "downgrade")
    assert not query(
        url,
        """SELECT column_name FROM information_schema.columns
        WHERE table_name='skills'
          AND column_name IN ('weight_class','risk_level','data_scope')""",
    )
    assert query(url, "SELECT count(*) FROM skills")[0][0] == 2

    migrate(url, "head")
    assert (
        query(url, "SELECT risk_level FROM skills WHERE skill_key='refund-action'")[0][0]
        == "r3"
    )
