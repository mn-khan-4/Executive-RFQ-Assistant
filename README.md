# Executive RFQ Assistant 🚀

An Intelligent Tender Processing System with **strict multi-tenant, role-based access control**. Each user operates in a fully isolated agent sandbox — their emails, threads, drafts, contacts, and OAuth tokens are never shared with other users.

> For full product requirements and database schema, see [`prd.md`](./prd.md).

---

## ✨ Key Features

- **🧠 OpenRouter Integration**: Powered by **Gemma 3 12B** via OpenRouter for high-performance extraction and cost-efficiency.
- **📊 Real-time Progress Tracking**: A dynamic dashboard UI that shows the agent's live status and batch progress.
- **📧 Multi-Provider Email Ingestion**: Per-user **Gmail** and **Outlook (Office 365)** OAuth2 connections, stored in `mail_accounts`.
- **📋 RFI Generator**: Automatically drafts clarification emails for missing documents or metadata.
- **📂 Standardized Storage**: Strict 01-08 folder hierarchy for organized tender management.
- **⚡ FastAPI Backend**: High-performance asynchronous API with HttpOnly cookie sessions and rate limiting.
- **🔐 Multi-Tenant RBAC**: Three-tier role system (superadmin / admin / user) with full data isolation per user.

---

## 🏗️ Project Structure

```text
/Executive-RFQ-Assistant/
├── agents/           # Core AI Logic (Classification, Extraction, RFIs)
├── api/              # FastAPI Endpoints & OAuth Callbacks
│   └── routes/       # auth, admin, user, emails, drafts, threads, contacts, dashboard, assistant
├── auth/             # Security: JWT, HttpOnly cookies, role dependencies, audit log
├── config/           # App Settings, Database Config, and LLM Prompts
├── database/         # SQLAlchemy Models & Alembic Migrations
├── integrations/     # Per-user Gmail/Outlook Listeners & Storage Handlers
├── models/           # Unified LLM Client (OpenRouter/Ollama)
├── scripts/          # Background Processors & Run Scripts
├── ui/               # Role-specific Dashboards (HTML/JS/CSS)
│   ├── login.html          # Shared login for admin + user
│   ├── admin-login.html    # Superadmin-only login
│   ├── index.html          # User dashboard
│   └── admin.html          # Admin / Superadmin dashboard
└── storage/          # Tender file storage (Mandatory 01-08 structure)
```

---

## 🔐 Security Model & Role Matrix

> See [`prd.md`](./prd.md) for the full specification.

### Roles

| Role | Description |
|---|---|
| `superadmin` | Full platform control. Create/delete/promote users. Dedicated login URL. |
| `admin` | User management (edit, deactivate, reset password). Cannot create or delete users. |
| `user` | Fully isolated agent sandbox. Sees only their own data. |

### Login URLs

| Role | Login URL | Redirect After Login |
|---|---|---|
| `user` | `/agent/login` → `/` | `/user_portal` (User Dashboard) |
| `admin` | `/agent/login` → `/` | `/admin_portal` (Admin Dashboard) |
| `superadmin` | `/agent/splogin` | `/admin_portal` (Superadmin Dashboard) |

> **Security rule**: Superadmin cannot log in via `/agent/login`. Users and admins cannot access `/agent/splogin`.

### API Endpoint Access Matrix

| Endpoint | `user` | `admin` | `superadmin` |
|---|:---:|:---:|:---:|
| `GET /api/dashboard/stats` | ✅ own data | ✅ own data | ✅ own data |
| `GET /api/emails/` | ✅ own | ✅ own | ✅ own |
| `GET /api/threads/` | ✅ own | ✅ own | ✅ own |
| `GET /api/drafts/` | ✅ own | ✅ own | ✅ own |
| `GET /api/contacts/` | ✅ own | ✅ own | ✅ own |
| `GET /api/admin/stats` | ❌ 403 | ✅ | ✅ |
| `GET /api/admin/users` | ❌ 403 | ❌ 403 | ✅ |
| `POST /api/admin/users` | ❌ 403 | ❌ 403 | ✅ |
| `PATCH /api/admin/users/{id}` | ❌ 403 | ❌ 403 | ✅ |
| `GET /api/admin/audit` | ❌ 403 | ❌ 403 | ✅ |
| `GET /api/user/me` | ✅ | ✅ | ✅ |
| `PATCH /api/user/me` | ✅ own | ✅ own | ✅ own |

### FastAPI Role Dependencies

| Dependency | Allows |
|---|---|
| `get_current_user` | Any authenticated user (reads HttpOnly cookie) |
| `get_current_admin` | `admin` or `superadmin` |
| `get_current_superadmin` | `superadmin` only |

### Data Isolation

Every business table (`emails`, `threads`, `attachments`, `contacts`, `tags`, `draft_replies`, `followup_tasks`, `topics`, `assistant_conversations`, `assistant_chat`) has a `user_id` foreign key. **All queries are filtered by `user_id = current_user.id`** — no cross-user data leakage is possible at the API layer.

OAuth tokens (Gmail / Outlook) are stored in the `mail_accounts` table, scoped per `user_id`. Each user connects their own mailbox independently.

### Security Headers (Applied to Every Response)

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
- `Content-Security-Policy` (strict allowlist)
- `Referrer-Policy: strict-origin-when-cross-origin`

### Audit Log

All sensitive actions (login, logout, user creation, role changes, brute-force blocks) are written to the `audit_log` table with `actor_user_id`, `target_user_id`, `action`, `details`, `ip_address`, and `timestamp`.

---

## 🚀 Quick Start

### 1. Requirements
- Python 3.10+
- PostgreSQL 14+
- OpenRouter API Key
- **ClamAV** (Optional — malware scanning):
  - Linux: `sudo apt-get install clamav clamav-daemon`
  - Windows: [ClamAV.net](https://www.clamav.net/) → add to PATH

### 2. Installation
```bash
pip install -r requirements.txt
```

### 3. Configuration
Copy or edit `.env` and set your credentials:
```bash
# LLM
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=google/gemma-3-12b

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/rfq_db

# Auth
SECRET_KEY=your_jwt_secret_here
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Server
PORT=8069
RELOAD=false
```

### 4. Database Setup & Migrations

Initialize the database (creates all tables and seeds default users):
```bash
python -m uvicorn api.main:app --reload
```

The app auto-runs `init_db()` and seeds three default accounts on first start:

| Email | Password | Role |
|---|---|---|
| `superadmin` | `superadmin123` | superadmin |
| `admin@123` | `admin123` | admin |
| `user123` | `user12345` | user |

> ⚠️ **Change all default passwords immediately in production.**

If you need to run schema migrations manually (Alembic):
```bash
alembic upgrade head
```

### 5. Running the App

Start the API server:
```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8069 --reload
```

Or use the provided script:
```bash
python api/main.py
```

Start the Email Monitoring Agent:
```bash
python scripts/run_rfq_agent.py
```

### 6. Accessing the Dashboards

| URL | Purpose |
|---|---|
| `http://localhost:8069/` | User / Admin login |
| `http://localhost:8069/agent/splogin` | Superadmin-only login |
| `http://localhost:8069/user_portal` | User dashboard (requires `user` session) |
| `http://localhost:8069/admin_portal` | Admin/Superadmin dashboard (requires `admin`/`superadmin` session) |

---

## 📂 Mandatory Tender Structure
1. `01_Instructions` - ITT & Rules
2. `02_Scope_of_Work` - SOW Documents
3. `03_Drawings` - Drawings & Site Maps
4. `04_Specifications` - Technical Specs
5. `05_BOQ` - Bill of Quantities
6. `06_Standards` - SBC, SASO Standards
7. `07_Commercial` - Terms & Bonds
8. `08_Output` - AI Intelligence & JSON metadata

---

## 🗄️ Key Database Tables

| Table | Scoped By | Purpose |
|---|---|---|
| `users` | — | All accounts; `role` field: `superadmin \| admin \| user` |
| `mail_accounts` | `user_id` | Per-user Gmail/Outlook OAuth tokens |
| `emails` | `user_id` | Ingested emails |
| `threads` | `user_id` | Email conversation threads |
| `attachments` | `user_id` | Uploaded/extracted files |
| `contacts` | `user_id` | Sender/recipient contact records |
| `tags` | `user_id` | Custom labels |
| `draft_replies` | `user_id` | AI-generated draft emails |
| `followup_tasks` | `user_id` | Scheduled follow-up actions |
| `topics` | `user_id` | Tender/project topic groupings |
| `assistant_conversations` | `user_id` | AI chat sessions |
| `assistant_chat` | `user_id` | Individual chat messages |
| `audit_log` | `actor_user_id` / `target_user_id` | Full action audit trail |

---

Developed for high-efficiency procurement teams. 🛠️
