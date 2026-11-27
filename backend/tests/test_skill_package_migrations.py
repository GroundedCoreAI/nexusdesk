import json
from uuid import uuid4

import asyncpg
import pytest
from test_ticket_migrations import migrate, query
from test_ticket_migrations import migration_database as _migration_database

migration_database = _migration_database
pytestmark = pytest.mark.postgres


def insert_skill(url, key):
    query(
        url,
        """INSERT INTO skills(id,tenant_id,business_id,workspace_id,skill_key,name,
        category,draft_definition,created_by,updated_by)
        VALUES($1,'demo','customer-service','default',$2,'Seed Skill','general',
        $3::jsonb,'tester','tester')""",
        uuid4(),
        key,
        json.dumps({"type": "instruction", "dependencies": {}, "runtime": {}}),
    )


def test_packages_are_additive_and_reversible(migration_database):
    url = migration_database
    migrate(url, "0077_skill_classification")
    insert_skill(url, "seed-skill")

    migrate(url, "head")
    columns = {
        row[0]
        for row in query(
            url,
            """SELECT column_name FROM information_schema.columns
            WHERE table_name='skills' AND column_name='draft_package_id'""",
        )
    }
    assert columns == {"draft_package_id"}
    # Every existing Skill stays valid with no package attached.
    assert query(url, "SELECT draft_package_id FROM skills WHERE skill_key='seed-skill'")[0][0] is None
    assert query(
        url,
        """SELECT column_name FROM information_schema.columns
        WHERE table_name='skill_versions' AND column_name='package_id'""",
    )

    skill_id = query(url, "SELECT id FROM skills WHERE skill_key='seed-skill'")[0][0]
    package_id = uuid4()
    query(
        url,
        """INSERT INTO skill_packages(id,tenant_id,business_id,workspace_id,skill_id,
        s3_bucket,s3_key,digest,size_bytes,file_count,manifest,created_by,filename)
        VALUES($1,'demo','customer-service','default',$2,'bucket','skills/x.zip',
        $3,10,1,'{}'::jsonb,'tester','seed.zip')""",
        package_id,
        skill_id,
        "sha256:" + "a" * 64,
    )
    query(url, "UPDATE skills SET draft_package_id=$1 WHERE id=$2", package_id, skill_id)

    # Pointing at a package row that does not exist is rejected by the foreign key.
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        query(
            url,
            "UPDATE skills SET draft_package_id=$1 WHERE skill_key='seed-skill'",
            uuid4(),
        )

    migrate(url, "0077_skill_classification", "downgrade")
    assert not query(
        url,
        """SELECT column_name FROM information_schema.columns
        WHERE table_name='skills' AND column_name='draft_package_id'""",
    )
    assert not query(
        url,
        "SELECT to_regclass('public.skill_packages') IS NOT NULL AS present",
    )[0][0]
    assert query(url, "SELECT count(*) FROM skills")[0][0] == 1

    migrate(url, "head")
    assert query(url, "SELECT count(*) FROM skills")[0][0] == 1


def test_filename_backfills_and_constrains(migration_database):
    url = migration_database
    migrate(url, "0078_skill_packages")
    insert_skill(url, "named-skill")
    skill_id = query(url, "SELECT id FROM skills WHERE skill_key='named-skill'")[0][0]
    # Written before the column existed, so this row has no name to preserve.
    query(
        url,
        """INSERT INTO skill_packages(id,tenant_id,business_id,workspace_id,skill_id,
        s3_bucket,s3_key,digest,size_bytes,file_count,manifest,created_by)
        VALUES($1,'demo','customer-service','default',$2,'bucket','skills/y.zip',
        $3,10,1,'{}'::jsonb,'tester')""",
        uuid4(),
        skill_id,
        "sha256:" + "b" * 64,
    )

    migrate(url, "head")
    # The default matches what the upload route uses when no name is supplied.
    assert query(url, "SELECT filename FROM skill_packages")[0][0] == "package.zip"

    with pytest.raises(asyncpg.NotNullViolationError):
        query(
            url,
            """INSERT INTO skill_packages(id,tenant_id,business_id,workspace_id,skill_id,
            s3_bucket,s3_key,digest,size_bytes,file_count,manifest,created_by,filename)
            VALUES($1,'demo','customer-service','default',$2,'bucket','skills/z.zip',
            $3,10,1,'{}'::jsonb,'tester',NULL)""",
            uuid4(),
            skill_id,
            "sha256:" + "c" * 64,
        )

    with pytest.raises(asyncpg.CheckViolationError):
        query(
            url,
            """INSERT INTO skill_packages(id,tenant_id,business_id,workspace_id,skill_id,
            s3_bucket,s3_key,digest,size_bytes,file_count,manifest,created_by,filename)
            VALUES($1,'demo','customer-service','default',$2,'bucket','skills/w.zip',
            $3,10,1,'{}'::jsonb,'tester','')""",
            uuid4(),
            skill_id,
            "sha256:" + "d" * 64,
        )
