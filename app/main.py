from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .slack_sync import SlackSyncStats, run_sync

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("codex_runner")

app = FastAPI(title="Codex Runner", version="1.0.0")

_settings: Settings = get_settings()
_loop_lock = asyncio.Lock()
_last_stats: SlackSyncStats | None = None
_last_error: str | None = None
_last_run_epoch: float | None = None
_polling_task: asyncio.Task[Any] | None = None


async def _sync_once() -> SlackSyncStats:
    global _last_stats, _last_error, _last_run_epoch
    try:
        result = await asyncio.to_thread(run_sync, _settings)
        _last_stats = result
        _last_error = None
        _last_run_epoch = time.time()
        return result
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        _last_run_epoch = time.time()
        logger.exception("Slack sync failed")
        raise


async def _poll_loop() -> None:
    logger.info("Starting Slack→GitHub poller (interval=%ss)", _settings.poll_interval_seconds)
    while True:
        try:
            async with _loop_lock:
                await _sync_once()
        except Exception:
            # error already logged in _sync_once
            pass
        await asyncio.sleep(_settings.poll_interval_seconds)


@app.on_event("startup")
async def on_startup() -> None:
    global _polling_task
    if _polling_task is None or _polling_task.done():
        _polling_task = asyncio.create_task(_poll_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _polling_task
    if _polling_task:
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:  # noqa: PERF203
            pass


@app.get("/healthz")
async def healthz() -> JSONResponse:
    body = {
        "last_run_epoch": _last_run_epoch,
        "last_stats": _last_stats.to_dict() if _last_stats else None,
        "last_error": _last_error,
        "poll_interval_seconds": _settings.poll_interval_seconds,
    }
    status_code = status.HTTP_200_OK if _last_error is None else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(body, status_code=status_code)


@app.post("/sync-now")
async def sync_now() -> JSONResponse:
    if _loop_lock.locked():
        raise HTTPException(status_code=423, detail="Sync already running")
    async with _loop_lock:
        try:
            result = await _sync_once()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return JSONResponse({
            "processed_messages": result.processed_messages,
            "created_issues": result.created_issues,
            "last_timestamp": result.last_timestamp,
            "run_epoch": _last_run_epoch,
        })
