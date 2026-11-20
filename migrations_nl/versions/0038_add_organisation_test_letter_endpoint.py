"""add organisation_test_letter_endpoint table

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-18 12:00:00.000000

The REST endpoint an organisation's letters sent with a test or team key are delivered to. Without a row those letters
keep being simulated. Expand-only: the previous release ignores the table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'organisation_test_letter_endpoint',
        sa.Column('organisation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organisation.id'), primary_key=True),
        sa.Column('endpoint_url', sa.String(), nullable=False),
        sa.Column('auth_method', sa.String(), nullable=False),
        # Fernet-encrypted JSON (credentials for the auth_method)
        sa.Column('auth_config', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.CheckConstraint("auth_method IN ('basic', 'api_key', 'oauth')", name='ck_otle_auth_method'),
    )


def downgrade():
    op.drop_table('organisation_test_letter_endpoint')
