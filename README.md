# YoutubeFilterAi

AI-powered YouTube transcript filter and summariser with Telegram bot integration.

## Architecture

```
┌─────────┐     ┌──────────────┐     ┌─────────────┐
│  NGINX  │────▶│  React SPA   │     │  PostgreSQL  │
│  :80    │     │  (Vite) :5173│     │    :5432     │
│         │────▶│              │     └──────▲───────┘
│         │     └──────────────┘            │
│         │────▶┌──────────────┐     ┌──────┴───────┐
│         │     │  FastAPI     │────▶│    Redis      │
│         │     │  :8000       │     │    :6379      │
│         │     └──────┬───────┘     └──────────────┘
└─────────┘            │
                       ├──▶ YouTube Transcript API
                       ├──▶ OpenRouter AI API
                       └──▶ Telegram Bot API
```

**Services** (all in Docker Compose):
| Service   | Tech              | Purpose                              |
|-----------|-------------------|--------------------------------------|
| `backend` | Python / FastAPI  | REST API, auth, AI pipeline          |
| `frontend`| React / Vite / TS | User & admin interfaces              |
| `db`      | PostgreSQL 16     | Persistent storage                   |
| `redis`   | Redis 7           | Rate limiting for OpenRouter calls   |
| `nginx`   | NGINX             | Reverse proxy (HTTP only, HTTPS handled externally) |

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env    # edit SECRET_KEY, ADMIN_PASSWORD

# 2. Start everything
docker compose up --build

# 3. Open browser
# User UI:  http://localhost
# Admin UI: http://localhost/admin/login
# API docs: http://localhost/api/docs
```

Changing the default ports
--------------------------

The project ships with these defaults:

- NGINX (host)       : 80  → proxies to the backend/frontend inside the compose network
- Backend (FastAPI)  : container listens on 8000 (uvicorn), exposed to host as 8000 by default
- Frontend (Vite)    : container listens on 5173, exposed to host as 5173 by default

There are two common port-change scenarios and the minimal steps for each.

1) Change the host port only (recommended when you want the app to be reachable on a different host port)

   - Edit `docker-compose.yml` and change the `ports` mapping for the service(s). Example: to expose the backend on host port 8080 while keeping the container port 8000:

     backend:
       # ...
       ports:
         - "8080:8000"

   - No change is required in `nginx/nginx.conf` if you only change the host mapping because NGINX inside the compose network talks to the `backend` service on the container port (8000).

   - Apply the change:

     ```bash
     docker compose up -d --build
     docker compose restart nginx backend
     ```

2) Change the container (internal) port (requires coordinated changes)

   - Update the backend command/uvicorn port in `docker-compose.yml` (and anywhere else the container is started). Example: change the uvicorn port to 9000:

     backend:
       command: uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
       ports:
         - "9000:9000"   # host_port:container_port

   - Update `nginx/nginx.conf` upstream for the backend to point to the new internal port (9000):

     upstream backend {
         server backend:9000;
     }

   - If you run the frontend on a different internal port (Vite `--port`), update the frontend `command` in `docker-compose.yml` and the nginx upstream `frontend:PORT` accordingly.

   - Rebuild and restart the stack:

     ```bash
     docker compose up -d --build
     docker compose restart nginx backend frontend
     ```

Local development (no Docker)
-----------------------------

- Backend (uvicorn): change the port when you run uvicorn locally:

  ```bash
  uvicorn app.main:app --reload --port 9000
  ```

- Frontend (Vite): pass `--port` to the dev server:

  ```bash
  npm run dev -- --host 0.0.0.0 --port 3000
  ```

Notes
-----

- If you only need the app to be reachable on a different host port, prefer changing the host mapping in `docker-compose.yml` (HOST:CONTAINER) because it's the smallest change and doesn't require touching `nginx/nginx.conf` or the container command.
- If you change the internal (container) port, you must update `nginx/nginx.conf` so the proxy forwards to the new port inside the Docker network.
- After any change to `nginx/nginx.conf`, restart the `nginx` service so it picks up the new config.
- Keep `.env` values (like `ALLOWED_ORIGINS`) in sync if they include port numbers.


## Development (without Docker)

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Start Postgres + Redis locally, then:
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

**Tests:**
```bash
cd backend && pytest tests/ -v
```

## Key Concepts

### Prompt Routing
Every user prompt must end with a JSON routing block that tells the system where to send the AI result:
```json
{
  "message": "the final summary...",
  "telegram_bots": ["financial_news_bot"],
  "web_views": ["financial_news"],
  "visibility": true
}
```

### Processing Pipeline
1. User submits YouTube URL + prompt
2. Backend fetches transcript via `youtube-transcript-api`
3. Transcript + prompt sent to OpenRouter AI (user's own API key)
4. AI response parsed for routing JSON
5. Message stored in DB, sent to specified Telegram bots and web views
6. Source video URL always included so user can verify

### Rate Limiting
Free-tier OpenRouter users are limited to `OPENROUTER_FREE_RPM` requests/minute (default: 10). Tracked per-user in Redis.

## Database Schema

Six tables: `users`, `prompts` (tree structure via `parent_id`), `youtube_channels`, `telegram_bots`, `web_views`, `messages`. See `backend/app/models.py` for full schema.

## Security & GDPR

- JWT authentication (bcrypt password hashing)
- Admin credentials in `.env` only
- Optional Google OAuth2
- GDPR consent timestamp on user model
- Cascade delete removes all user data on account deletion
- No secrets in code; `.env` excluded from git
- HTTPS handled by external NGINX/load balancer

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── config.py            # Settings from env vars
│   │   ├── database.py          # Async SQLAlchemy setup
│   │   ├── models.py            # ORM models (6 tables)
│   │   ├── schemas.py           # Pydantic request/response
│   │   ├── auth.py              # JWT, password hashing
│   │   ├── api/
│   │   │   ├── auth_routes.py   # Login, register
│   │   │   ├── resource_routes.py # CRUD: prompts, channels, bots, views
│   │   │   ├── process_routes.py  # Video processing pipeline
│   │   │   └── admin_routes.py    # Admin user management
│   │   └── services/
│   │       ├── __init__.py      # YouTube transcript fetcher
│   │       ├── ai_service.py    # OpenRouter client + rate limiter
│   │       └── telegram_service.py # Telegram message sender
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Router + auth state
│   │   ├── api.ts               # Axios client with JWT
│   │   ├── components/Layout.tsx # Nav bar wrapper
│   │   └── pages/               # One file per page
│   ├── package.json
│   └── Dockerfile
├── nginx/nginx.conf
├── docker-compose.yml
├── .env.example
└── .gitignore
```
