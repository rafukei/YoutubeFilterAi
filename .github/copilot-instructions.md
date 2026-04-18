## Copilot Instructions — YoutubeFilterAi

### Architecture overview
Five Docker Compose services: **FastAPI backend** (`backend/app/main.py`), **React SPA** (`frontend/src/App.tsx`), **PostgreSQL**, **Redis** (rate limiting), and **NGINX** reverse proxy. Data flows: User → NGINX :80 → `/api/*` to backend :8000, everything else to frontend :5173.

### Build & run
```bash
cp .env.example .env          # set SECRET_KEY, ADMIN_PASSWORD
docker compose up --build      # full stack at http://localhost
# Backend only: cd backend && uvicorn app.main:app --reload
# Frontend only: cd frontend && npm install && npm run dev
# Tests:         cd backend && pytest tests/ -v
```

### Backend conventions (Python / FastAPI)
- **Config**: all settings via env vars → `backend/app/config.py` (`pydantic-settings`). Never hard-code secrets.
- **DB**: async SQLAlchemy in `backend/app/database.py`. Models in `backend/app/models.py` (7 tables: users, prompts, youtube_channels, telegram_bots, web_views, messages, **app_settings**). Use `get_db` dependency for sessions.
- **Auth**: JWT + bcrypt in `backend/app/auth.py`. Admin auth checks `.env` creds, not DB. Use `get_current_user` dependency on all user endpoints.
- **Routes**: one file per domain in `backend/app/api/` — `auth_routes.py`, `resource_routes.py`, `process_routes.py`, `admin_routes.py`. All prefixed `/api/`.
- **Services** (`backend/app/services/`): YouTube transcript fetch (`__init__.py`), OpenRouter AI client with Redis rate limiting (`ai_service.py`), Telegram sender (`telegram_service.py`).
- **Docstrings**: every function documents Args, Returns, Raises. Follow this pattern in new code.

### Frontend conventions (React / Vite / TypeScript / Tailwind)
- API client with auto-JWT in `frontend/src/api.ts` (axios interceptor).
- One page component per file in `frontend/src/pages/`. Layout shell in `frontend/src/components/Layout.tsx`.
- Admin pages: `AdminUsersPage.tsx` (user management), `AdminSettingsPage.tsx` (system settings).
- Styling: Tailwind utility classes only, indigo-600 primary, rounded-lg/2xl cards.

### Prompt routing pattern (critical domain logic)
Every user prompt must instruct the AI to append a JSON routing block:
```json
{"message": "...", "telegram_bots": ["bot_name"], "web_views": ["view_name"], "visibility": true}
```
`backend/app/services/ai_service.py::parse_ai_routing()` extracts this. If missing, the full response becomes the message with `visibility: true`.

### Rate limiting
OpenRouter free-tier: configurable via admin settings (`app_settings.openrouter_rate_limit`), tracked in Redis via `ai_service.py::_check_rate_limit()`. Always check before calling OpenRouter.

### Admin Settings (runtime config)
The `app_settings` table stores runtime-configurable settings:
- `registration_enabled` – toggle user self-registration
- `require_approval` – auto-approve new users or require admin approval
- `allow_gmail_auth` – enable Google OAuth login
- `google_client_id/secret` – OAuth credentials
- `openrouter_rate_limit` – requests per minute per user

Admin UI: `/admin/settings` → `AdminSettingsPage.tsx`

### Key rules for AI agents
1. **Always include source video URL** in Telegram messages and stored messages — users must be able to verify.
2. **Never commit `.env`** — it's in `.gitignore`. New env vars → add to `.env.example` + document in README.
3. **GDPR**: `User.gdpr_consent_at` must be set before processing personal data. Cascade deletes remove all user data.
4. **Admin routes** use separate JWT claim (`is_admin`), not user table. See `backend/app/api/admin_routes.py`.
5. **Tests**: add to `backend/tests/`. Run `pytest tests/ -v`. Test files: `test_auth.py`, `test_services.py`, `test_auth_api.py`, `test_resources_api.py`, `test_admin_api.py`, `test_process_api.py`.
6. **No HTTPS in app** — handled by external NGINX. Don't add SSL config to FastAPI or Vite.
7. **Registration toggle**: Check `app_settings.registration_enabled` in `auth_routes.py::register()` before allowing new registrations.

