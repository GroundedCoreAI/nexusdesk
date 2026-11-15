"""Merge the customer-service and execution-platform revision branches.

Two revision chains diverge from ``0057_industry_pack_runtime`` and both reached
the integration branch:

- ``0058_service_application_v2`` .. ``0066_hosted_web`` (bound service
  applications, hosted web page, turn diagnostics)
- ``0058_agent_execution_metadata`` .. ``0059_execution_runtime_host``
  (execution platform phases 2-4)

Each chain is internally consistent, but ``alembic upgrade head`` refuses to run
with more than one head, so the merge needs an explicit join point. Nothing has
to be executed here: the two branches touch disjoint tables, and every schema
change already happened in its own revision. This revision only exists to
collapse the graph back to a single head, so later migrations can keep
``down_revision`` as a plain string again.

Renaming ``0058``/``0059`` was not an option -- revision identifiers are primary
keys in ``alembic_version`` on every database that already ran them.
"""

revision = "0067_merge_heads"
down_revision = ("0066_hosted_web", "0059_execution_runtime_host")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
