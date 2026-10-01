"""WebSockets: live system stats, training runs and pipeline runs."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import session_scope
from app.models import PipelineLog, PipelineRun, Run, RunMetric
from app.services.hub import hub
from app.services.settings_store import settings_store
from app.services.system import system_monitor
from app.utils import iso, to_jsonable

router = APIRouter()
PING_EVERY_S = 15


def _authorised(ws: WebSocket) -> bool:
    if not settings_store.get()["security"].get("require_auth"):
        return True
    from app.routers.settings import decode_token

    token = ws.query_params.get("token")
    return bool(token and decode_token(token))


async def _pump(ws: WebSocket, channel: str, snapshot: Optional[Callable[[], Any]] = None) -> None:
    if not _authorised(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    queue = hub.subscribe(channel)
    try:
        if snapshot is not None:
            data = await asyncio.get_running_loop().run_in_executor(None, snapshot)
            if data is not None:
                await ws.send_json(to_jsonable(data))
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=PING_EVERY_S)
            except asyncio.TimeoutError:
                msg = {"type": "ping"}
            await ws.send_json(msg)
    except (WebSocketDisconnect, RuntimeError, ConnectionError):
        pass
    finally:
        hub.unsubscribe(channel, queue)


@router.websocket("/ws/system")
async def ws_system(ws: WebSocket) -> None:
    await _pump(ws, "system", lambda: {"type": "system", **system_monitor.latest})


def _run_snapshot(run_id: int) -> Optional[dict[str, Any]]:
    from sqlmodel import select

    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            return {"type": "error", "message": "run not found"}
        history = s.exec(select(RunMetric).where(RunMetric.run_id == run_id).order_by(RunMetric.epoch)).all()
        return {"type": "snapshot", "run_id": run_id, "status": run.status, "epoch": run.epoch,
                "total_epochs": run.total_epochs, "progress": run.progress, "metrics": run.metrics,
                "elapsed_s": run.duration_s,
                "history": [{"epoch": m.epoch, "train_loss": m.train_loss, "val_loss": m.val_loss,
                             "train_acc": m.train_acc, "val_acc": m.val_acc, "f1": m.f1} for m in history]}


@router.websocket("/ws/runs/{run_id}")
async def ws_run(ws: WebSocket, run_id: int) -> None:
    await _pump(ws, f"run:{run_id}", lambda: _run_snapshot(run_id))


def _pipeline_snapshot(run_id: int) -> Optional[dict[str, Any]]:
    from sqlmodel import select

    with session_scope() as s:
        run = s.get(PipelineRun, run_id)
        if run is None:
            return {"type": "error", "message": "pipeline run not found"}
        logs = s.exec(select(PipelineLog).where(PipelineLog.run_id == run_id).order_by(PipelineLog.id)).all()
        return {"type": "snapshot", "run_id": run_id, "status": run.status, "nodes": run.nodes,
                "logs": [{"ts": iso(l.ts), "level": l.level, "node": l.node, "message": l.message} for l in logs[-200:]]}


@router.websocket("/ws/pipelines/{run_id}")
async def ws_pipeline(ws: WebSocket, run_id: int) -> None:
    await _pump(ws, f"pipeline:{run_id}", lambda: _pipeline_snapshot(run_id))
