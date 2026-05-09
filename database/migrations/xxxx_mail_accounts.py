"""
Add mail_accounts table for per-user OAuth tokens

Revision ID: xxxx_mail_accounts
Revises: xxxx_multitenancy_roles
Create Date: 2026-05-08
"""

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'mail_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('email_address', sa.String(length=255), nullable=False),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text()),
        sa.Column('token_expiry', sa.DateTime()),
        sa.Column('meta_data', sa.dialects.postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.UniqueConstraint('user_id', 'provider', 'email_address', name='uq_user_provider_email'),
    )

def downgrade():
    op.drop_table('mail_accounts')
