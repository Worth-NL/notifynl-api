"""add organisation_letter_provider table

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-29 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'organisation_letter_provider',
        sa.Column('organisation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organisation.id'), primary_key=True),
        sa.Column(
            'provider_details_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('provider_details.id'), nullable=False
        ),
        sa.Column('endpoint_url', sa.String(), nullable=True),
        sa.Column('auth_method', sa.String(), nullable=True),
        sa.Column('address_placement', sa.String(length=5), nullable=False, server_default='60mm'),
        # Fernet-encrypted JSON (credentials for the provider's auth_method)
        sa.Column('auth_config', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.CheckConstraint(
            "auth_method IS NULL OR auth_method IN ('basic', 'api_key', 'oauth')", name='ck_olp_auth_method'
        ),
        sa.CheckConstraint("address_placement IN ('50mm', '60mm')", name='ck_olp_address_placement'),
    )
    op.create_index(
        'ix_organisation_letter_provider_provider_details_id', 'organisation_letter_provider', ['provider_details_id']
    )


def downgrade():
    op.drop_index('ix_organisation_letter_provider_provider_details_id', table_name='organisation_letter_provider')
    op.drop_table('organisation_letter_provider')
