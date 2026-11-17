"""company board discovery + live search progress

Companies can now be added by name only: platform and board_token become optional and are
filled in by automatic discovery. search_history gets live progress columns.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table lets the same migration work on PostgreSQL and on SQLite (tests).
    with op.batch_alter_table("companies") as batch:
        batch.alter_column("platform", existing_type=sa.String(length=30), nullable=True)
        batch.alter_column("board_token", existing_type=sa.String(length=200), nullable=True)
        # Existing rows were entered by hand, so they start as "manual".
        batch.add_column(
            sa.Column("discovery_status", sa.String(length=20), nullable=False, server_default="manual")
        )
    with op.batch_alter_table("search_history") as batch:
        batch.add_column(sa.Column("companies_done", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("current_company", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("search_history") as batch:
        batch.drop_column("current_company")
        batch.drop_column("companies_done")
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("discovery_status")
        # Rows without a platform cannot satisfy NOT NULL again, so remove them first.
        op.execute("DELETE FROM companies WHERE platform IS NULL OR board_token IS NULL")
        batch.alter_column("board_token", existing_type=sa.String(length=200), nullable=False)
        batch.alter_column("platform", existing_type=sa.String(length=30), nullable=False)
