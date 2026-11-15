"""Hosted web page: a public chat link owned by one open-platform application.

The open platform already had two browser delivery modes, both of which assume a
host page: the widget runs inside an iframe and demands a ``parent_origin`` that
is on the allow-list, and every visitor must sign in through an enterprise
identity provider. A Hosted Web page is the third mode: a link the tenant can
share with anyone, where the visitor is anonymous.

- ``open_embed_configs.hosted`` enables the public page independently of the
  iframe switch, so a tenant can ship one, both, or neither.
- ``hosted_key`` is the unguessable path segment. It is minted on first enable
  and can be rotated, which is the only revocation lever for a leaked link.
- ``welcome`` is the opening line the page shows before the first message.

Anonymous sessions reuse ``enterprise_sessions`` with ``provider_id`` and
``embed_revision`` both NULL. That pair is what tells the session validator the
session belongs to the hosted page (it is gated by ``hosted``) rather than to an
SSO or server-issued chat token (gated by the iframe config revision).
"""

from alembic import op

revision = "0066_hosted_web"
down_revision = "0065_open_platform_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE open_embed_configs "
        "ADD COLUMN hosted boolean NOT NULL DEFAULT false, "
        "ADD COLUMN hosted_key text, "
        "ADD COLUMN welcome text NOT NULL DEFAULT ''"
    )
    op.execute(
        "CREATE UNIQUE INDEX open_embed_configs_hosted_key "
        "ON open_embed_configs(hosted_key) WHERE hosted_key IS NOT NULL"
    )
    # Minting throttles on recent hosted sessions per application; expire cleanup
    # scans the same rows by expiry.
    op.execute(
        "CREATE INDEX enterprise_sessions_hosted_recent "
        "ON enterprise_sessions(app_id, created_at) "
        "WHERE provider_id IS NULL AND embed_revision IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS enterprise_sessions_hosted_recent")
    op.execute("DROP INDEX IF EXISTS open_embed_configs_hosted_key")
    op.execute(
        "ALTER TABLE open_embed_configs "
        "DROP COLUMN hosted, DROP COLUMN hosted_key, DROP COLUMN welcome"
    )
