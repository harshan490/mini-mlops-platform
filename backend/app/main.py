"""Mini MLOps Platform API.

Run from ``backend/``:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import select

from app.config import APP_VERSION
from app.db import init_db, session_scope
from app.models import Deployment, User
from app.routers import datasets, deployments, experiments, models, monitoring, pipelines, settings, system, users, ws
from app.services.alerts import alert_engine
from app.services.hub import hub
from app.services.pipeline_runner import pipeline_runner
from app.services.serving import serving
from app.services.settings_store import settings_store
from app.services.system import system_monitor
from app.services.trainer import trainer

log = logging.getLogger("mini-mlops")
PUBLIC_API = {"/api/auth/login", "/api/auth/status", "/api/health"}


def _bootstrap() -> None:
    init_db()
    with session_scope() as s:
        empty = s.exec(select(User)).first() is None
    if empty:
        from app.seed import seed

        log.warning("Empty database: seeding demo data (first start takes ~30 s)")
        seed()
    username, pw_hash = settings_store.admin_credentials()
    if not pw_hash:
        settings_store.set_admin_password("admin", "admin")
    trainer.recover_interrupted()
    pipeline_runner.recover_interrupted()
    with session_scope() as s:
        deps = s.exec(select(Deployment)).all()
        running = [d.id for d in deps if d.status == "Running"]
        deploying = [(d.id, d.version_id) for d in deps if d.status == "Deploying"]
    for dep_id in running:
        serving.load_now(dep_id)
    for dep_id, version_id in deploying:
        serving.rollout(dep_id, version_id, "restart", None, "Resumed rollout after server restart")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hub.bind(asyncio.get_running_loop())
    await asyncio.get_running_loop().run_in_executor(None, _bootstrap)
    system_monitor.start()
    alert_engine.start()
    serving.start_autoscaler()
    pipeline_runner.start_scheduler()
    yield
    system_monitor.stop()
    if pipeline_runner.scheduler is not None:
        pipeline_runner.scheduler.shutdown(wait=False)


app = FastAPI(title="Mini MLOps Platform", version=APP_VERSION, lifespan=lifespan,
              description="Datasets, real training, registry, in-process serving, drift monitoring and pipelines.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API and request.method != "OPTIONS":
        if settings_store.get()["security"].get("require_auth"):
            from app.routers.settings import bearer, decode_token

            token = bearer(request)
            if not token or not decode_token(token):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)


for module in (system, datasets, experiments, models, deployments, pipelines, monitoring, settings, users):
    app.include_router(module.router)
app.include_router(deployments.serve_router)
app.include_router(ws.router)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": "Mini MLOps Platform API", "version": APP_VERSION, "docs": "/docs"}
