# OFAC Screening Enterprise App

This repository has been upgraded to an enterprise-style architecture:

- Frontend: React + Vite, containerized (Nginx runtime)
- Backend API: FastAPI
- Queue: AWS SQS (LocalStack in local Docker setup)
- Screening engine: Actimize Watchlist adapter (single-request model)
- Throughput control: Worker-side throttle at 32 TPS

## Architecture

1. Frontend submits screening queries to FastAPI.
2. FastAPI persists job + items in SQLite and enqueues one SQS message per entity.
3. Worker consumes SQS, screens each entity with Actimize (or mock mode), and enforces `32 TPS`.
4. Worker stores normalized results back in SQLite.
5. Frontend polls job status and renders results when complete.

## Key Paths

- Frontend API client: `src/api/openSanctions.ts`
- FastAPI app: `backend/app/main.py`
- SQS worker: `backend/app/worker.py`
- Actimize adapter: `backend/app/actimize.py`
- Persistence: `backend/app/repository.py`
- Local stack orchestration: `docker-compose.yml`

## Local Run (Containerized)

```bash
docker compose up --build
```

Endpoints:

- Frontend: `http://localhost:8080`
- Backend health: `http://localhost:8000/health`
- LocalStack (SQS): `http://localhost:4566`

## Environment Variables

Frontend (`.env`, see `.env.example`):

- `VITE_SCREENING_API_BASE_URL` default `/api/v1`
- `VITE_SCREENING_POLL_INTERVAL_MS` default `750`
- `VITE_SCREENING_JOB_TIMEOUT_MS` default `90000`

Backend/Worker (`backend/.env.example`):

- `SCREENING_TPS=32` for Actimize single-request throughput
- `ACTIMIZE_MOCK=true` for local simulation
- Set `ACTIMIZE_MOCK=false` + `ACTIMIZE_BASE_URL` + `ACTIMIZE_API_KEY` for real engine

## API Endpoints

- `POST /api/v1/screenings/jobs` create async job
- `GET /api/v1/screenings/jobs/{job_id}` get progress/result
- `POST /api/v1/screenings/match` submit and wait (sync wrapper over async pipeline)

## Notes

- The frontend keeps the same `matchBatch(...)` contract, so existing UI logic remains intact.
- Failed item responses are normalized with `status=500` so UI can still render deterministic rows.
- Current local persistence uses SQLite for simplicity; production can swap repository to RDS/DynamoDB.

