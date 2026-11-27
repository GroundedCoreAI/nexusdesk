"""Keep the uploaded file name beside the package digest.

The digest answers "which bytes are these"; it cannot answer "which file did I
drop in". Support and audit both ask the second question, and a bare
``sha256:9f3c...`` is not an answer a human can act on. The name is recorded for
display only -- it never influences how the archive is read, so a caller that
lies about it changes nothing but the label.

Existing rows were written before the column existed and had no name to
preserve. They are backfilled with the API's own default so the column can be
``NOT NULL``: absence would mean "unknown label", and every real package has
one.
"""

import sqlalchemy as sa
from alembic import op

revision = "0079_skill_package_filename"
down_revision = "0078_skill_packages"
branch_labels = None
depends_on = None

DEFAULT_FILENAME = "package.zip"


def upgrade() -> None:
    op.add_column(
        "skill_packages",
        sa.Column("filename", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE skill_packages SET filename = :fallback WHERE filename IS NULL"
        ).bindparams(fallback=DEFAULT_FILENAME)
    )
    op.alter_column("skill_packages", "filename", nullable=False)
    op.create_check_constraint(
        "skill_packages_filename_length",
        "skill_packages",
        "char_length(filename) BETWEEN 1 AND 255",
    )


def downgrade() -> None:
    op.drop_constraint(
        "skill_packages_filename_length", "skill_packages", type_="check"
    )
    op.drop_column("skill_packages", "filename")
