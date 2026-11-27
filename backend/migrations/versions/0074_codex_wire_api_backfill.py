"""Clean up the legacy ``codex_wire_api = "chat"`` value from stored gateway data.

Phase 7 follow-up to ``dbcc2a5`` (reject un-runnable Codex wire protocols). The
pinned Codex CLI removed the ``chat`` wire protocol in 0.169; a connection or a
published profile snapshot that still carries it can be saved/published on an
older build and then aborts at CLI config parse on every Run, surfacing only as
the opaque ``engine_unavailable``.

``dbcc2a5`` added publish/resolve guards but no data migration, so databases
upgraded in place keep the unusable value and cannot republish the affected
Agent (publish now rejects it with ``codex_model_profile_invalid``). This
migration is the missing cleanup step:

  * ``gateway_connections.spec`` — the editable connection, used by the legacy
    lane and as the source for newly published profile versions.
  * ``gateway_profile_versions.snapshot`` — every published version; the
    resolver reads ``routes[].connection.codex_wire_api`` verbatim from here,
    and republishing must stay possible without hand-editing JSONB.

Only the literal ``"chat"`` is replaced (with ``"responses"``, the sole value
the pinned CLI accepts). All other values, every other spec field, revisions,
and published versions are left byte-identical. The operation is idempotent.
"""

import sqlalchemy as sa
from alembic import op

revision = "0074_codex_wire_api_backfill"
down_revision = "0073_execution_parser_diag"
branch_labels = None
depends_on = None

# Replace only the legacy unsupported value; leave NULL and "responses" alone
# and never rewrite any other spec content. jsonb_set keeps all sibling keys.
_CONNECTION_SPEC = sa.text("""
    UPDATE gateway_connections
       SET spec = jsonb_set(spec, '{codex_wire_api}', '"responses"', false),
           revision = revision + 1,
           updated_at = now()
     WHERE spec->>'codex_wire_api' = 'chat'
""")

# A profile version snapshot embeds the full connection spec under each route.
# Rewrite just that nested key for every affected route of every version; the
# snapshot JSONB and its version number stay otherwise unchanged. Published
# versions are immutable at the API boundary, so this in-place correction is
# deliberately limited to the single field the CLI cannot parse.
_SNAPSHOT = sa.text("""
    UPDATE gateway_profile_versions
       SET snapshot = jsonb_set(
               snapshot,
               '{routes}',
               (
                 SELECT jsonb_agg(
                          CASE
                            WHEN elem.value ? 'connection'
                             AND elem.value->'connection'->>'codex_wire_api' = 'chat'
                            THEN jsonb_set(
                                   elem.value,
                                   '{connection,codex_wire_api}',
                                   '"responses"',
                                   false
                                 )
                            ELSE elem.value
                          END
                          ORDER BY elem.ord
                        )
                   FROM jsonb_array_elements(snapshot->'routes')
                        WITH ORDINALITY AS elem(value, ord)
               ),
               false
             )
     WHERE jsonb_typeof(snapshot->'routes') = 'array'
       AND EXISTS (
             SELECT 1
               FROM jsonb_array_elements(snapshot->'routes') AS r
              WHERE r->'connection'->>'codex_wire_api' = 'chat'
           )
""")


def upgrade() -> None:
    op.execute(_CONNECTION_SPEC)
    op.execute(_SNAPSHOT)


def downgrade() -> None:
    # Data-only cleanup. A downgrade cannot know which rows originally held
    # "chat" versus "responses"; reverting blindly would reintroduce the
    # unusable value. Preserve the sanitized data (same pattern as 0017/0062).
    pass
