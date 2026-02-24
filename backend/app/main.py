from __future__ import annotations

import asyncio
import time

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models import EntityMatchResponse, MatchJobAccepted, MatchJobProgress, MatchJobRequest
from .queue import SqsQueue
from .repository import JobRepository
from .screening_service import ScreeningService

repository = JobRepository(settings.app_db_path)
queue = SqsQueue()
service = ScreeningService(repository=repository, queue=queue)

app = FastAPI(title=settings.app_name, version=settings.app_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    queue.ensure_queue()


def get_service() -> ScreeningService:
    return service


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/screenings/jobs", response_model=MatchJobAccepted)
def create_screening_job(payload: MatchJobRequest, svc: ScreeningService = Depends(get_service)) -> MatchJobAccepted:
    try:
        return svc.submit_job(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/screenings/jobs/{job_id}", response_model=MatchJobProgress)
def get_screening_job(job_id: str, svc: ScreeningService = Depends(get_service)) -> MatchJobProgress:
    progress = svc.get_progress(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return progress


@app.post("/api/v1/screenings/match", response_model=EntityMatchResponse)
async def match_and_wait(payload: MatchJobRequest, svc: ScreeningService = Depends(get_service)) -> EntityMatchResponse:
    accepted = svc.submit_job(payload)
    timeout_seconds = settings.screening_sync_timeout_s
    poll_interval = max(settings.screening_poll_interval_ms / 1000.0, 0.1)
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        progress = svc.get_progress(accepted.job_id)
        if progress and progress.responses is not None:
            return svc.get_terminal_match_response(progress)
        await asyncio.sleep(poll_interval)

    raise HTTPException(
        status_code=504,
        detail=(
            f"Job {accepted.job_id} exceeded {timeout_seconds}s while waiting for worker completion. "
            "Use /api/v1/screenings/jobs/{job_id} for async polling."
        ),
    )

