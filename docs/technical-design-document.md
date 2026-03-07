# Technical Design Document (TDD): OFAC / Watchlist Screening Platform

**Version:** 1.1  
**Date:** 2026-03-06  
**Repo:** `ofac-screening-aws`  

This document describes the technical design for the OFAC / watchlist screening platform deployed on AWS. It includes AWS architecture, API flows, process flows, and component responsibilities.

## 1. System Overview

The platform supports:
- **Single Screening (Sync):** user submits a single entity and receives an immediate response.
- **Batch Screening (Async):** user uploads a batch; the platform returns immediately with a job id; a worker processes in background.
- **Daily Screening (Scheduled):** selected batches are automatically re-screened daily shortly after midnight Eastern time.
- **AuthN/AuthZ:** OIDC login (AWS Cognito or enterprise IdP federation) and role-based authorization.
- **Audit Trail:** all key user/system actions are recorded for traceability.
- **API Access Logging:** every `/api/v1/*` request is logged with status, latency, auth state, and correlation id.
- **Operational Controls:** log retention and high-risk external API failure alerting.

## 2. AWS Architecture (Deployed View)

### 2.1 Logical Diagram

```mermaid
flowchart LR
  subgraph Internet[Public Internet]
    U[User Browser]
  end

  subgraph AWS[AWS Account]
    CF[CloudFront Distribution<br/>HTTPS]
    ALB[Application Load Balancer<br/>HTTP origin from CloudFront]

    subgraph VPC[VPC]
      subgraph ECS[ECS Cluster: Screening]
        FE[Frontend Service<br/>Fargate Task<br/>Nginx + SPA]
        BE[Backend Service<br/>Fargate Task<br/>FastAPI]
        WK[Worker Service<br/>Fargate Task<br/>SQS consumer + scheduler]
      end

      SD[Service Discovery (Cloud Map)<br/>Namespace: screening.internal<br/>backend.screening.internal]
      Q[SQS Queue<br/>screening-requests]
      DB[(RDS PostgreSQL)]
      CW[CloudWatch Logs]
    end

    COG[AWS Cognito User Pool<br/>OIDC]
  end

  U -->|HTTPS| CF
  CF -->|HTTP| ALB
  ALB --> FE

  FE -->|/api/* reverse proxy| BE
  FE --- SD
  BE --- SD

  BE -->|enqueue| Q
  BE -->|read/write| DB
  BE -->|emit logs| CW

  WK -->|poll| Q
  WK -->|read/write| DB
  WK -->|emit logs| CW

  U -->|OIDC Auth Code + PKCE| COG
  U -->|Bearer access token| FE
  FE -->|Bearer access token forwarded| BE
```

### 2.2 Key AWS Components

- **CloudFront**
  - Provides HTTPS required for browser crypto APIs (OIDC PKCE) and a single public entrypoint.
  - Origin is the public ALB.
- **ALB**
  - Routes traffic to the frontend service target group.
  - Backend traffic stays internal: the frontend Nginx reverse-proxies `/api/` to the backend service name.
- **ECS/Fargate**
  - `ofac-screening-frontend-svc`: serves SPA + reverse proxy.
  - `ofac-screening-backend-svc`: FastAPI REST API and synchronous screening.
  - `ofac-screening-worker-svc`: consumes SQS and runs daily schedule loop (often desired count 0 in dev to reduce cost).
- **Cloud Map service discovery**
  - Backend resolves as `backend.screening.internal` from the frontend tasks.
- **SQS**
  - Buffers batch work; decouples user submission from screening execution.
- **RDS PostgreSQL**
  - Stores jobs, items, daily schedule definitions and run metadata, and audit events.
- **Cognito**
  - User login and token issuance (or federation from enterprise IdP).
  - Group membership in tokens maps to app roles/permissions.
- **CloudWatch Logs**
  - Central log streams per ECS service for support and troubleshooting.

## 3. Security Design

### 3.1 Authentication

- Browser uses **OIDC Authorization Code + PKCE** against Cognito.
- Frontend stores session per configuration (session storage supported for tab-close logout behavior).
- Frontend sends `Authorization: Bearer <access_token>` with API requests.

### 3.2 Authorization Model

Roles are derived from token claims (e.g., Cognito `cognito:groups`, or `custom:roles` if federating).

Role intent:
- `viewer`: can perform screening only in mock mode.
- `analyst`: can do single + batch screening.
- `compliance`: analyst permissions + daily screening enable/disable.
- `admin`: compliance permissions + user admin + audit visibility.

Backend enforces permissions per endpoint (scope/role checks).

### 3.3 Token Validation

Backend validates JWT signature using JWKS and checks:
- issuer matches configured issuer
- algorithm matches allowed list
- audience compatibility for Cognito access tokens:
  - accept app client id in `aud` OR `client_id` OR `azp`

Auth audit behavior:
- API 401/403 outcomes are written to `audit_events` and `api_access_logs`.
- Identity-provider login attempts (hosted by Cognito/enterprise IdP) remain in IdP-native audit logs; this app records API-layer authentication outcomes.

## 4. Component Responsibilities

### 4.1 Frontend (SPA + Nginx reverse proxy)

Responsibilities:
- Provide UI for Single/Batch/Daily screening and results.
- Initiate OIDC login/logout and maintain session.
- Call backend APIs under `/api/v1/*`.
- Poll job progress for batch screening and render status transitions.
- Enforce UX constraints based on user permissions (hide/disable actions).

Runtime configuration:
- `VITE_*` values are injected at container startup into `app-config.js`.
- Nginx config is generated at startup; `/api/` is reverse-proxied to `BACKEND_UPSTREAM`.

### 4.2 Backend API (FastAPI)

Responsibilities:
- Validate and accept screening requests.
- Provide synchronous screening endpoint for immediate results.
- Create batch jobs and enqueue SQS messages for async processing.
- Provide job progress endpoints for polling.
- Manage daily schedule definitions (list/disable).
- Write audit events for key actions and failures.
- Run middleware-based API access logging (method/path/status/latency/user/auth state).
- Generate and return request correlation id (`X-Correlation-ID`) and propagate to downstream screening flows.

### 4.3 Worker (SQS Consumer + Daily Scheduler Loop)

Responsibilities:
- Poll SQS messages and process screening items.
- Enforce screening throughput and execute screening calls for selected types.
- Enforce throughput constraint via fixed-rate limiter (`32 TPS`).
- Persist item results (completed/failed) into the database.
- Periodically check due daily schedules and trigger new batch jobs.
- Apply retention policy cleanup for audit/access/error stores.
- Emit high-risk audit alerts when external API failures exceed configured threshold/window.

### 4.4 Screening Engine Adapter (Actimize Watchlist Adapter)

Responsibilities:
- Provide `screen_single` and `screen_many_types`.
- Normalize results into a stable structure for UI consumption.
- Support mock screening for demos/dev environments.

Note: In this repo, the adapter is configured for the Actimize/Kong sanctions API and preserves the "single-type per request" behavior required by Actimize-style engines.

### 4.5 Data Store (PostgreSQL)

Responsibilities:
- Persist job metadata, per-item status transitions, request payloads, and response payloads.
- Persist daily schedules and next-run calculations.
- Persist audit events for compliance and troubleshooting.
- Persist API access logs (`api_access_logs`) for request/response traceability.
- Persist external API failures (`external_api_errors`) with provider/operation context.

## 5. Data Model (Business Objects)

### 5.1 Screening Types

- `Sanction`
- `PEP`
- `AME`
- `Fincen 314(a)`
- `Global Sanction`

### 5.2 Entity Types

- `Individual`
- `Organization`
- `Vessel`
- `Aircraft`

### 5.3 Job Status (Batch)

- `queued`
- `processing`
- `completed`
- `failed`

Item status is tracked similarly and rolls up to job snapshot counts.

### 5.4 Audit and Access Objects

- `audit_events`
  - Business and system action trail (screening submit, queue lifecycle, schedule actions, auth failures, alert events).
- `api_access_logs`
  - One row per `/api/v1/*` request including method, path, status, duration, user context, auth state, and correlation id.
- `external_api_errors`
  - Error repository for upstream screening API failures with provider, endpoint, status code, and request context.

## 6. API Design

Base path: `/api/v1` (except health endpoint).

### 6.1 Cross-Cutting API Behavior

- AuthN/AuthZ:
  - `/api/v1/*` uses bearer JWT validation when `AUTH_ENABLED=true`.
  - Authorization uses role/scopes with permissions (`screening.read`, `screening.write`, `screening.daily`, `screening.admin`, `screening.useradmin`, `screening.single.mock`).
- Correlation and access audit:
  - Every API response includes `X-Correlation-ID`.
  - Every `/api/v1/*` request is written to `api_access_logs` with method, path, status, latency, auth state, and user context.
  - 401/403 outcomes emit audit events (`API_AUTHENTICATION_FAILED`, `API_AUTHORIZATION_FAILED`).
- Screening guardrails:
  - Business Unit is mandatory for screening submissions and is validated against user mapping.
  - Sync screening allows viewer role only in `mock_screening=true`.
  - Daily/scheduled operations require compliance/admin permission.
- Error handling:
  - Validation/business rule failures return `400`.
  - Authorization failures return `403`.
  - Missing entities return `404`.
  - External screening API failures are persisted to `external_api_errors`.

### 6.2 Endpoint Catalog

| Method | Path | Required Permission | Functionality |
|---|---|---|---|
| `GET` | `/health` | None | Liveness/readiness response (`{"status":"ok"}`). |
| `POST` | `/api/v1/screenings/jobs` | `screening.write` or `screening.daily` or `screening.admin` | Creates async screening job from JSON payload (`queries`, screening types, schedule options). If `daily_screening=true`, schedule is created/updated and first execution is deferred to schedule time. |
| `POST` | `/api/v1/screenings/batch-upload` | `screening.write` or `screening.daily` or `screening.admin` | Uploads batch file + query payload, validates file content rules, optionally stores source in S3, creates job/schedule, supports optional subscription creation. |
| `GET` | `/api/v1/screenings/jobs/{job_id}` | `screening.read` | Returns job progress counts and terminal responses when complete. |
| `GET` | `/api/v1/screenings/submissions` | `screening.read` | Returns user-visible submission history for single and batch runs with normalized result status. |
| `POST` | `/api/v1/screenings/match` | `screening.write` or `screening.single.mock` or `screening.admin` | Performs synchronous screening, persists job/item metadata, returns immediate merged results; logs per-item API call success/failure. |
| `GET` | `/api/v1/screenings/daily-schedules` | `screening.read` | Lists active schedules with frequency, next run, source file metadata, and business unit. |
| `DELETE` | `/api/v1/screenings/daily-schedules/{schedule_id}` | `screening.daily` or `screening.admin` | Disables one daily schedule and writes audit event. |
| `GET` | `/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` | `screening.read` | Lists subscriptions for a schedule (scoped to caller context). |
| `POST` | `/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` | `screening.read` | Upserts subscription email for schedule notifications. |
| `DELETE` | `/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` | `screening.read` | Removes subscription by email for the schedule. |
| `GET` | `/api/v1/business-units` | `screening.read` | Returns active business units mapped to current user. |
| `GET` | `/api/v1/admin/business-units` | `screening.admin` or `screening.useradmin` | Lists all business units (`include_inactive` supported). |
| `POST` | `/api/v1/admin/business-units` | `screening.admin` or `screening.useradmin` | Creates new business unit reference row. |
| `PUT` | `/api/v1/admin/business-units/{business_unit_code}` | `screening.admin` or `screening.useradmin` | Updates business unit code/name and cascades code change to mappings/metadata. |
| `DELETE` | `/api/v1/admin/business-units/{business_unit_code}` | `screening.admin` or `screening.useradmin` | Deletes business unit and related user mappings. |
| `GET` | `/api/v1/admin/business-unit-mappings` | `screening.admin` or `screening.useradmin` | Lists user-to-business-unit mappings. |
| `PUT` | `/api/v1/admin/business-unit-mappings/{user_id}` | `screening.admin` or `screening.useradmin` | Replaces mapping for one user with supplied business unit list. |
| `GET` | `/api/v1/admin/users` | `screening.admin` or `screening.useradmin` | Lists known users (DB + Cognito user pool enumeration fallback). |
| `GET` | `/api/v1/audit-events` | `screening.admin` or `screening.useradmin` | Returns audit events with pagination (`limit`, `offset`) and optional `user_id` filter. |

### 6.3 Functional Notes By API Area

- Screening submission APIs:
  - Persist job, item, metadata, and audit records.
  - Async jobs enqueue one SQS message per item and track queue lifecycle audit events.
  - Sync jobs execute immediately and write per-item external API call audit lifecycle.
- Batch-upload validation:
  - `queries_json` must be non-empty object.
  - `PartyKey` is required, cannot be blank, and must be unique.
  - Legacy `row_<n>` keys are rejected.
  - Allowed schema values: person/individual/company/organization/legalentity/unknown.
  - Gender validation allows `M`, `F`, or blank (plus textual male/female/unknown variants).
  - At least one non-empty name is required.
- Scheduling and subscriptions:
  - Schedule creation does not screen immediately; worker executes at `next_run_at`.
  - Schedule runs support frequency (`DAILY`, `WEEKLY`, `MONTHLY`) and dedupe against previously screened schedule record hashes.
  - Completion notifications are generated for subscribed emails and logged.
- Admin APIs:
  - Business unit reference table is runtime-managed via API (create/update/delete/list).
  - User/business-unit mapping determines selectable BU values in screening flows and is enforced on submit.
- Audit APIs:
  - `audit_events` is admin-only.
  - Additional operational telemetry is stored in `api_access_logs` and `external_api_errors` tables for enterprise support/compliance queries.

## 7. Process Flows

### 7.1 OIDC Login (Cognito)

```mermaid
sequenceDiagram
  participant B as Browser
  participant C as Cognito
  participant FE as Frontend SPA
  participant API as Backend API

  B->>FE: Open app (HTTPS)
  FE->>C: Redirect to /authorize (PKCE)
  C-->>B: Login UI
  B->>C: Authenticate
  C-->>FE: Redirect with authorization code
  FE->>C: Exchange code for tokens
  FE->>API: API call with Bearer access token
  API-->>FE: 200/403 based on permissions
```

### 7.2 Single Screening (Sync)

```mermaid
sequenceDiagram
  participant UI as Frontend
  participant API as FastAPI
  participant ENG as Screening Engine Adapter
  participant DB as PostgreSQL

  UI->>API: POST /api/v1/screenings/match
  API->>DB: audit SYNC_SCREENING_SUBMITTED
  loop for each screening type selected
    API->>ENG: screen_single(type)
    ENG-->>API: result(type)
  end
  API->>DB: store screening record + audit
  API-->>UI: response (merged hits)
```

### 7.3 Batch Screening (Async)

```mermaid
sequenceDiagram
  participant UI as Frontend
  participant API as FastAPI
  participant DB as PostgreSQL
  participant Q as SQS
  participant WK as Worker
  participant ENG as Screening Engine Adapter

  UI->>API: POST /api/v1/screenings/jobs
  API->>DB: create job + items + audit
  API->>Q: enqueue 1 message per item
  API-->>UI: 202 {job_id, status=queued}

  loop worker processes messages
    WK->>Q: receive message
    WK->>DB: mark item processing
    loop for each selected screening type
      WK->>ENG: screen_single(type) (rate limited)
      ENG-->>WK: result(type)
    end
    WK->>DB: mark item completed/failed
    WK->>Q: delete message
  end

  UI->>API: GET /api/v1/screenings/jobs/{job_id} (poll)
  API-->>UI: progress + results when terminal
```

### 7.4 Daily Screening Trigger (Worker Scheduler)

```mermaid
sequenceDiagram
  participant WK as Worker
  participant DB as PostgreSQL
  participant API as FastAPI
  participant Q as SQS

  WK->>DB: list due schedules
  WK->>DB: claim schedule run (atomic)
  WK->>API: submit_job(saved batch payload)
  API->>DB: create new job + audit
  API->>Q: enqueue items
  WK->>DB: update next_run_at
```

### 7.5 Batch Job Status Rollup

```mermaid
stateDiagram-v2
  [*] --> queued
  queued --> processing: worker starts items
  processing --> completed: all items done and >=1 success
  processing --> failed: all items done and all failed
```

### 7.6 Correlation and Access Audit Flow

```mermaid
sequenceDiagram
  participant UI as Frontend
  participant API as FastAPI Middleware
  participant DB as PostgreSQL
  participant Q as SQS
  participant WK as Worker
  participant EXT as External Screening API

  UI->>API: /api/v1/* request (optional X-Correlation-ID)
  API->>API: assign/propagate correlation id
  API->>DB: insert api_access_logs row
  API->>Q: enqueue message with correlation id
  WK->>Q: pick message
  WK->>EXT: screening request
  EXT-->>WK: response/error
  WK->>DB: audit_events + external_api_errors (with correlation id)
```

## 8. Operational Design

### 8.1 Throughput and Rate Limiting

- Worker enforces a fixed-rate schedule for outbound screening calls.
- Default is `32 TPS` across the worker process.

### 8.2 Resilience and Retries

- Worker marks failures per item; job can still complete with partial failures.
- Messages are deleted after processing to avoid duplicates (at-least-once queue semantics should be accounted for by idempotent writes).
- Daily schedule trigger uses a claim step to reduce duplicate schedule runs.

### 8.3 Observability

- Application logs shipped to CloudWatch via ECS log driver.
- Audit events provide a business-level trail, separate from system logs.
- API access logs provide request-level traceability with latency and auth state.
- Correlation id is propagated to queue/worker/external error records for end-to-end troubleshooting.

### 8.4 Data Retention and Risk Alerting

- Worker executes periodic retention cleanup for:
  - `audit_events`
  - `api_access_logs`
  - `external_api_errors`
- Retention windows are configurable with environment variables.
- High-risk alerting rule:
  - If external API failures exceed configured threshold inside configured time window, worker records `HIGH_RISK_EXTERNAL_API_FAILURE_ALERT` in `audit_events`.
- Access-log query parameters are redacted for sensitive key types (token/secret/password/email-like fields).

### 8.5 Cost Controls (Dev)

- Keep worker desired count at `0` when not testing batch/daily.
- Use small Fargate tasks (256/512) for dev.
- Use minimal RDS instance for dev and stop when not needed (per environment policy).

## 9. Deployment Artifacts

- ECS task definitions in `deploy/ecs/`
  - `frontend-task-definition.json`
  - `backend-task-definition.json`
  - `worker-task-definition.json`
- CloudFront distribution config example in `deploy/cloudfront-distribution-config.json`

## 10. Appendix: Runtime Configuration

### 10.1 Frontend (container env)

Key values:
- `BACKEND_UPSTREAM` (example: `http://backend.screening.internal:8000`)
- `VITE_SCREENING_API_BASE_URL` (default: `/api/v1`)
- `VITE_AUTH_ENABLED` / OIDC settings

### 10.2 Backend/Worker (container env)

Key values:
- `APP_DB_URL` (PostgreSQL connection string)
- `AWS_SQS_QUEUE_NAME`
- `AUTH_ENABLED`, `AUTH_ISSUER`, `AUTH_JWKS_URL`, `AUTH_AUDIENCE`
- `SCREENING_TPS`
- `AUDIT_ACCESS_LOG_ENABLED` (default `true`)
- `AUDIT_EVENT_RETENTION_DAYS` (default `3650`)
- `API_ACCESS_LOG_RETENTION_DAYS` (default `365`)
- `EXTERNAL_API_ERROR_RETENTION_DAYS` (default `365`)
- `OPERATIONAL_CLEANUP_INTERVAL_S` (default `3600`)
- `HIGH_RISK_EXTERNAL_API_ERROR_WINDOW_MINUTES` (default `15`)
- `HIGH_RISK_EXTERNAL_API_ERROR_THRESHOLD` (default `10`)

