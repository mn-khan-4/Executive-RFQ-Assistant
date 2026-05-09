# Multi-Tenant Role-Based RFQ Assistant System — PRD

## Summary
Upgrade the Executive-RFQ-Assistant codebase to support strict multi-tenancy and robust role-based access:
- Three roles: superadmin, admin, user.
- True per-user data isolation: each user acts in their own "sandboxed agent".
- User/admin login at the same endpoint, superadmin using a distinct URL.
- Dedicated dashboards and management UIs for each role.
- Per-user Gmail (OAuth) and agent logic isolation.

---

## Functional Requirements

### Roles
- **Superadmin**
  - Only role that can create, delete, and fully manage users.
  - Can promote/demote users to/from admin.
  - Has a dedicated login/UI (`/agent/splogin`), and a superadmin-only dashboard.
  - Cannot be accessed via the user/admin login.

- **Admin**
  - Shares login page with users (`/agent/login`).
  - Can manage (but not create) users: edit, deactivate, reset password, etc.
  - Cannot access superadmin UI or endpoints.

- **User**
  - Shares login page with admin.
  - All data (emails, threads, attachments, contacts, calendar, etc.) is fully isolated by `user_id`—no user can see another's data.
  - Own Gmail connection, own visual agent portal/dashboard.
  - Cannot perform any user management.

---

## Database/Backend
- Add a `user_id` column to ALL main business/data tables (`contacts`, `threads`, `emails`, `attachments`, `tags`, `draft_replies`, `topics`, etc.) and enforce this everywhere.
- Add `role` field in the `users` table, values: `'superadmin' | 'admin' | 'user'`.
- Index/Foreign Key every `user_id` to users.id.
- Add a `mail_accounts` table for Gmail/Outlook tokens, owned by `user_id`.
- Audit log table should indicate who performed what (target_user, actor_user).
- Create or update DB migrations for all the above.

---

## Auth & Routing
- `/agent/login`: users or admins login here.
  - If role is `admin` redirect to `/agent/admin-dashboard`.
  - If role is `user` redirect to `/agent/user-dashboard`.
- `/agent/splogin`: only for superadmin login; others are rejected.
  - Redirect to `/agent/superadmin-dashboard` on success.
- All dashboard endpoints enforce role at backend.
- API endpoints must check and enforce current user's role for sensitive calls.
- Admin cannot create users or access any superadmin endpoints.

---

## Dashboards/UIs
- **Superadmin Dashboard**: List/add/edit/delete all users, change roles, stats, system logs.
- **Admin Dashboard**: List/edit/disable users, but no create/delete; stats as allowed.
- **User Dashboard**: User agent workflow, only user’s own data, email connection, real-time activity.

All dashboards and login pages must keep the styling/branding continuous with the current project.

---

## Per-user Gmail/Agent Data
- All Gmail OAuth tokens and related account integration are per-user, stored and loaded by `user_id`.
- All data queries (emails, threads, attachments, contacts, tags, drafts, followups, calendar, etc.) are filtered by `user_id`.

---

## Security
- **Never** allow admins to access superadmin-only UIs, API routes, or actions, even by direct URL.
- All routes should check `user.role` and enforce at the backend.
- All sensitive actions should be logged in audit.

---

## Implementation Milestones (recommended for AI cursor agent)
1. Update `database/models.py` and add migrations for all table changes.
2. Update all CRUD endpoints (and FastAPI dependencies) for per-user data scope and role enforcement.
3. Build admin/user/superadmin dashboards and login templates/pages, using current design system.
4. Implement Gmail/OAuth connection per user.
5. Update/extend tests.
6. Update `README.md` and technical docs.

---

## Non-functional
- All pages and APIs must remain performant, even with large user tables.
- All styling and UX must remain consistent with existing branding.

---

# DETAILED DATABASE SCHEMA (PostgreSQL DDL)

```sql
-- USERS
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user',   -- superadmin | admin | user
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    preferences JSONB DEFAULT '{}'::jsonb,
    brand_voice TEXT,
    custom_instructions TEXT,
    writing_style_guide TEXT,
    last_style_sync TIMESTAMP,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);

-- MAIL ACCOUNTS (Gmail/Outlook tokens per user)
CREATE TABLE mail_accounts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL,      -- gmail | outlook
    email_address VARCHAR(255) NOT NULL,
    access_token TEXT,
    refresh_token TEXT,
    token_expiry TIMESTAMP,
    scopes JSONB DEFAULT '[]'::jsonb,
    is_connected BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at TIMESTAMP,
    meta_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_mail_accounts_provider ON mail_accounts(provider);
CREATE INDEX idx_mail_accounts_email ON mail_accounts(email_address);

-- CONTACTS
CREATE TABLE contacts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    contact_name VARCHAR(255) NOT NULL,
    email_domain VARCHAR(100),
    contact_emails TEXT[],
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_contact TIMESTAMP,
    total_interactions INTEGER NOT NULL DEFAULT 0,
    meta_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_contacts_user_id ON contacts(user_id);

-- TOPICS
CREATE TABLE topics (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    topic_name VARCHAR(255),
    topic_reference VARCHAR(100),
    thread_id VARCHAR(50) UNIQUE,
    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
    folder_path TEXT,
    meta_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_topics_user_id ON topics(user_id);
CREATE INDEX idx_topics_contact_id ON topics(contact_id);

-- THREADS
CREATE TABLE threads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id VARCHAR(50) UNIQUE NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PROCESSING',
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    topic_id INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    subject TEXT,
    contact_name VARCHAR(255),
    topic_name VARCHAR(255),
    thread_reference VARCHAR(100),
    source VARCHAR(50),
    source_email VARCHAR(255),
    source_sender VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_threads_user_id ON threads(user_id);

-- TAGS
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(50) NOT NULL,
    color VARCHAR(20) DEFAULT '#6366f1',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, name)
);

CREATE INDEX idx_tags_user_id ON tags(user_id);

-- EMAILS
CREATE TABLE emails (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id VARCHAR(50) NOT NULL,
    email_id VARCHAR(255) UNIQUE NOT NULL,
    subject TEXT,
    sender VARCHAR(255),
    recipients TEXT[],
    body TEXT,
    received_at TIMESTAMPTZ,
    is_actionable BOOLEAN NOT NULL DEFAULT TRUE,
    is_junk BOOLEAN NOT NULL DEFAULT FALSE,
    is_sent BOOLEAN NOT NULL DEFAULT FALSE,
    detection_confidence REAL,
    tags_suggested TEXT[],
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    meta_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_emails_user_id ON emails(user_id);

-- EMAIL <-> TAGS
CREATE TABLE email_tags (
    email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (email_id, tag_id)
);

-- THREAD <-> TAGS
CREATE TABLE thread_tags (
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (thread_id, tag_id)
);

-- ATTACHMENTS
CREATE TABLE attachments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id VARCHAR(50) NOT NULL,
    category VARCHAR(100),
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255),
    file_path TEXT NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    file_size_bytes INTEGER,
    doc_type VARCHAR(50),
    summary TEXT,
    is_correct BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source VARCHAR(50)
);

CREATE INDEX idx_attachments_user_id ON attachments(user_id);

-- DRAFT REPLIES
CREATE TABLE draft_replies (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id VARCHAR(50) NOT NULL,
    draft_type VARCHAR(50),
    recipient VARCHAR(255) NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    email_provider VARCHAR(20),
    provider_draft_id VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
    created_by VARCHAR(50) DEFAULT 'GENERAL_EMAIL_ASSISTANT',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    in_reply_to_email_id VARCHAR(255),
    meta_data JSONB DEFAULT '{}'::jsonb,
    scheduled_at TIMESTAMP
);

CREATE INDEX idx_draft_replies_user_id ON draft_replies(user_id);

-- FOLLOWUP TASKS
CREATE TABLE followup_tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id VARCHAR(50) NOT NULL,
    original_email_id VARCHAR(255),
    recipient VARCHAR(255),
    suggested_body TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    due_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_followup_tasks_user_id ON followup_tasks(user_id);

-- ASSISTANT CONVERSATIONS
CREATE TABLE assistant_conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) DEFAULT 'New Conversation',
    mode VARCHAR(20) NOT NULL DEFAULT 'enterprise',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_message_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_assistant_conversations_user_id ON assistant_conversations(user_id);

-- ASSISTANT CHAT
CREATE TABLE assistant_chat (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES assistant_conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_assistant_chat_user_id ON assistant_chat(user_id);

-- AUDIT LOG
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    thread_id VARCHAR(50),
    agent VARCHAR(50) DEFAULT 'RFQ_AGENT',
    action VARCHAR(100) NOT NULL,
    details JSONB DEFAULT '{}'::jsonb,
    ip_address VARCHAR(50),
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX idx_audit_log_actor_user_id ON audit_log(actor_user_id);
CREATE INDEX idx_audit_log_target_user_id ON audit_log(target_user_id);
CREATE INDEX idx_audit_log_thread_id ON audit_log(thread_id);
CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp);

-- USER MANAGEMENT MAP (OPTIONAL FOR ADMIN->USER GRANULAR ASSIGNMENT)
CREATE TABLE user_managed_users (
    id SERIAL PRIMARY KEY,
    admin_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (admin_id, user_id)
);

CREATE INDEX idx_user_managed_users_admin_id ON user_managed_users(admin_id);
CREATE INDEX idx_user_managed_users_user_id ON user_managed_users(user_id);
```
