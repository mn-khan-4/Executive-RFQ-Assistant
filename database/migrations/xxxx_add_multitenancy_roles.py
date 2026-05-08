"""Add user_id to main tables and role to users

Revision ID: xxxx_multitenancy_roles
Revises: <previous_revision_id>
Create Date: 2026-05-08
"""

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('contacts', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('topics', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('tags', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('threads', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('emails', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('attachments', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('draft_replies', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('followup_tasks', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('assistant_conversations', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('assistant_chat', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('role', sa.String(length=50), server_default='user'))

    # Add foreign keys
    op.create_foreign_key(None, 'contacts', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'topics', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'tags', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'threads', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'emails', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'attachments', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'draft_replies', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'followup_tasks', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'assistant_conversations', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'assistant_chat', 'users', ['user_id'], ['id'])

    # Make columns NOT NULL if you're also sure of data migration

def downgrade():
    # Reverse operations (drop columns/fks)
    op.drop_constraint(None, 'contacts', type_='foreignkey')
    op.drop_constraint(None, 'topics', type_='foreignkey')
    op.drop_constraint(None, 'tags', type_='foreignkey')
    op.drop_constraint(None, 'threads', type_='foreignkey')
    op.drop_constraint(None, 'emails', type_='foreignkey')
    op.drop_constraint(None, 'attachments', type_='foreignkey')
    op.drop_constraint(None, 'draft_replies', type_='foreignkey')
    op.drop_constraint(None, 'followup_tasks', type_='foreignkey')
    op.drop_constraint(None, 'assistant_conversations', type_='foreignkey')
    op.drop_constraint(None, 'assistant_chat', type_='foreignkey')

    op.drop_column('contacts', 'user_id')
    op.drop_column('topics', 'user_id')
    op.drop_column('tags', 'user_id')
    op.drop_column('threads', 'user_id')
    op.drop_column('emails', 'user_id')
    op.drop_column('attachments', 'user_id')
    op.drop_column('draft_replies', 'user_id')
    op.drop_column('followup_tasks', 'user_id')
    op.drop_column('assistant_conversations', 'user_id')
    op.drop_column('assistant_chat', 'user_id')
    op.drop_column('users', 'role')
