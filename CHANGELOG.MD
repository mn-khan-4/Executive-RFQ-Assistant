v2.0.0-multitenant — Multi-User, Role-Based, Database-Backed Mail & Calendar Integration
🚀 Major Features
Multi-Tenancy:
Full per-user data isolation for all business tables: emails, threads, contacts, attachments, tags, drafts, topics, etc., with user_id foreign key.
Each user acts as an independent agent—no cross-user data access in app or API.
Role-Based Security:
Roles enforced (superadmin, admin, user) at both backend (API) and frontend (UI/routing) for all dashboard access and critical actions. Superadmin gets dedicated login and full user/role management; admins and users have access only to scoped features.
Database-Backed Mail & Calendar Integrations:
All Gmail and Outlook OAuth tokens now managed via the new mail_accounts table, with unique constraints per user and provider. Agents and background tasks fetch tokens and operate strictly by the authenticated user's context. Legacy local .json file fallback for development and smooth migration.
🛠️ Fixes & Improvements
Session/Calendar Cache Hardening:
Fixed security bug: calendar caches are now isolated by user (no calendar data leakage).
Session Summary Leak:
/api/session-summary properly filters by user (no cross-account stat displays).
Background & Agent Isolation:
All background jobs, reply generators, and agent scripts use proper user context.
Error Handling/Feedback:
Expired or invalid tokens trigger clear, actionable user UI feedback (never a stack trace).
Role Downgrade Robustness:
Users demoted from admin retain their mail/calendar integrations without breakage.
🔒 Security
All endpoints and dashboard routes now return 403 Forbidden with a clear error for unauthorized role access, and always redirect to login for unauthenticated users.
Key API endpoints (user management, audit, platform stats) are now strictly protected by backend role checks.
All critical access or permission violations are logged for audit review, including the provider and user_id.
🗃️ Data Migration
Introduced and migrated all accounts to the mail_accounts table for OAuth credentials.
Applied missing UniqueConstraint imports to prevent schema errors.
Legacy Gmail/Outlook tokens still supported for seamless transition, but all new connections require per-user DB storage.
📝 Documentation
README.md rewritten with a Security Model, Role Matrix, user_id data mapping, and a dashboard URL table.
PRD archived in repo root for audit/compliance tracking.
Docstrings added to all major agent, fetcher, and integration modules to specify per-user handling and DB contexts.
All temporary test code/scripts removed.
Post-merge QA checklist and future work roadmap added to docs.
This release establishes a robust, audit-ready, multi-tenant architecture.
All high-severity security and data isolation issues after migration have been resolved and validated under comprehensive regression and integration testing.
System is now production-ready and prepared for future SSO/2FA, advanced monitoring, and further scaling.