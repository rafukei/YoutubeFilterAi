"""
FastAPI application entrypoint.

Startup:
    - Connects to Redis
    - Creates DB tables (dev only; use Alembic in prod)
    - Starts background channel scheduler
    - Includes all API routers

Run locally: uvicorn app.main:app --reload --port 8000
Run in Docker: handled by Dockerfile CMD
"""

import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.api.auth_routes import router as auth_router
from app.api.resource_routes import router as resource_router
from app.api.process_routes import router as process_router
from app.api.admin_routes import router as admin_router
from app.services.scheduler import scheduler_loop

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect Redis, create tables, start scheduler. Shutdown: cancel scheduler, close Redis."""
    # Redis
    app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    # Create tables (dev convenience – use Alembic migrations in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Start background scheduler
    app.state.scheduler_task = asyncio.create_task(scheduler_loop(app.state.redis))
    yield
    # Shutdown
    app.state.scheduler_task.cancel()
    await app.state.redis.close()


app = FastAPI(
    title=settings.APP_NAME,
    description="YouTube transcript AI filter & summariser",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS – allow the frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router)
app.include_router(resource_router)
app.include_router(process_router)
app.include_router(admin_router)


@app.get("/api/health")
async def health():
    """Health-check endpoint for Docker / NGINX."""
    return {"status": "ok"}
