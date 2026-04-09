# Technical Design Document (TDD): OFAC / Watchlist Screening Platform

**Version:** 1.5  
**Date:** 2026-04-09  
**Repo:** `ofac-screening-aws`  

This document describes the technical design for the OFAC / watchlist screening platform deployed on AWS. It includes AWS architecture, API flows, process flows, and component responsibilities.

## Revision Summary

- Batch upload is now fully **backend-parsed**: the frontend submits only the source file plus metadata, and the backend validates/normalizes rows into `EntityExample` payloads before job creation.
- The batch upload response now returns `row_meta` so the UI can render placeholder/result rows without duplicating client-side parsing logic.
- The screening dashboard is split into two backend APIs:
  - `GET /api/v1/screenings/summary` for full-history aggregate cards
  - `GET /api/v1/screenings/results` for newest-first result rows capped to `300`
- Large immediate uploads continue to use the S3-backed `JOB_DISPATCH` pattern so the worker expands queued work asynchronously instead of performing per-record dispatch in the request thread.
- Audit operations now support paged admin retrieval, and raw Actimize/Prudential request/response troubleshooting logs can be enabled with redaction.
- Authentication wording is aligned to the current AWS deployment baseline: OIDC via AWS Cognito (with optional enterprise federation), with old local Keycloak references removed from the active design baseline.

## 1. System Overview

The platform supports:
- **Single Screening (Sync):** user submits a single entity and receives an immediate response.
- **Batch Screening (Async):** user uploads a CSV/XLSX file plus metadata only; the backend parses, validates, and normalizes the file before creating async work.
- **Large Batch Dispatch (Async):** for very large immediate batch uploads, backend stores the uploaded source file and a backend-generated `queries.json` in S3 and enqueues a `JOB_DISPATCH` SQS message so the worker can expand/enqueue per-record tasks without hitting CloudFront origin timeouts.
- **Daily Screening (Scheduled):** selected batches are automatically re-screened on their configured cadence (`DAILY`, `WEEKLY`, `MONTHLY`) shortly after the configured local run time.
- **AuthN/AuthZ:** OIDC login (AWS Cognito or enterprise IdP federation) and role-based authorization.
- **Audit Trail:** key user/system actions are recorded for traceability, with admin-facing paged audit APIs.
- **Fast Screening Dashboard:** summary cards load from a dedicated aggregate API over the full user history, while the Screening Results grid loads a separate recent-results feed capped for UX performance.
- **API Access Logging:** every `/api/v1/*` request is logged with status, latency, auth state, and correlation id.
- **Raw Upstream Troubleshooting Logs:** outbound Prudential/Actimize request and response payloads are logged to CloudWatch with sensitive fields redacted.
- **Operational Controls:** explicit schema initialization, connection pooling, DB retry/backoff, retention cleanup, and high-risk external API failure alerting.

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
    S3[(S3 Bucket<br/>Batch Upload Storage)]
    SNS[SNS<br/>Schedule Notifications]
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
  BE -->|upload source + generated queries.json| S3

  WK -->|poll| Q
  WK -->|read/write| DB
  WK -->|emit logs| CW
  WK -->|download queries.json (JOB_DISPATCH)| S3
  WK -->|publish completion| SNS

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
- **S3 (optional, required for large batch dispatch)**
  - Stores batch upload source files (`.csv` / `.xlsx`) and backend-generated `queries.json` when enabled.
  - Large immediate uploads use S3-backed `JOB_DISPATCH` expansion to avoid CloudFront timeouts.
- **SNS (optional)**
  - Publishes scheduled screening completion notifications to subscribed email recipients (implementation uses per-recipient SNS topics to avoid repeated email confirmation prompts when schedules change).
- **CloudWatch Logs**
  - Central log streams per ECS service for support and troubleshooting.

## 3. Security Design by Component

### 3.1 Frontend Container Security (`frontend`)

- Browser uses **OIDC Authorization Code + PKCE** against Cognito.
- Frontend stores session per configuration (including session-storage mode for tab-close logout behavior).
- Frontend sends `Authorization: Bearer <access_token>` with API requests.
- Frontend permissions are a UX concern only: buttons/tabs may be hidden or disabled, but enforcement remains in the backend container.

### 3.2 Backend Container Authorization (`backend`)

Roles are derived from token claims (for example Cognito `cognito:groups` or federated custom role claims).

Role intent:
- `viewer`: can perform screening only in mock mode.
- `analyst`: can do single + batch screening.
- `compliance`: analyst permissions + daily screening enable/disable.
- `admin`: compliance permissions + user admin + audit visibility.

Backend enforces permissions per endpoint with scope/role checks.

### 3.3 Backend Token Validation (`backend`)

Backend validates JWT signature using JWKS and checks:
- issuer matches configured issuer
- algorithm matches allowed list
- audience compatibility for Cognito access tokens:
  - accept app client id in `aud` OR `client_id` OR `azp`

Auth audit behavior:
- API `401`/`403` outcomes are written to `audit_events` and `api_access_logs`.
- Identity-provider login attempts (hosted by Cognito/enterprise IdP) remain in IdP-native audit logs; this app records API-layer authentication outcomes.

## 4. Component Responsibilities and Functional Ownership

### 4.1 Frontend (SPA + Nginx reverse proxy)

Responsibilities:
- Provide UI for Single/Batch/Daily screening and results.
- Initiate OIDC login/logout and maintain session.
- Call backend APIs under `/api/v1/*`.
- Poll job progress for batch screening and render status transitions.
- Enforce UX constraints based on user permissions (hide/disable actions).
- Persist screening workspace state and audit-log filter/page state in browser `localStorage`.
- Load dashboard summary counts from `GET /api/v1/screenings/summary` across the full user history.
- Load Screening Results rows from `GET /api/v1/screenings/results` using a recent-results window capped to the latest `300` rows for the signed-in user.
- Expose environment-configurable review-alert navigation via `VITE_ACTIMIZE_REVIEW_ALERT_URL`.

Runtime configuration:
- `VITE_*` values are injected at container startup into `app-config.js`.
- Nginx config is generated at startup; `/api/` is reverse-proxied to `BACKEND_UPSTREAM`.

### 4.2 Backend API (FastAPI)

Responsibilities:
- Validate and accept screening requests.
- Provide synchronous screening endpoint for immediate results.
- Create batch jobs and enqueue SQS messages for async processing.
- Provide a lightweight screening summary API that returns aggregate counts for the signed-in user without loading result rows.
- Provide a lightweight recent-results API that returns only the latest `300` result rows for the signed-in user, separated from summary-card aggregation.
- Parse uploaded CSV/XLSX files server-side, validate row rules, normalize them into `EntityExample` payloads, and return `row_meta` for UI rendering.
- For immediate large batch uploads, create the job quickly and enqueue a single `JOB_DISPATCH` message; the worker expands into per-record `SCREEN_ITEM` tasks using backend-generated `queries.json` stored in S3.
- Provide job progress endpoints for polling.
- Manage daily schedule definitions (list/disable).
- Write audit events for key actions and failures.
- Run middleware-based API access logging (method/path/status/latency/user/auth state).
- Generate and return request correlation id (`X-Correlation-ID`) and propagate to downstream screening flows.
- Validate database schema at startup, but do not run DDL automatically in runtime API processes.

### 4.3 Worker (SQS Consumer + Daily Scheduler Loop)

Responsibilities:
- Poll SQS messages and process screening items.
- Handle `JOB_DISPATCH` messages for large immediate batch uploads by downloading `queries.json` from S3, creating job items in bulk, and enqueuing per-record `SCREEN_ITEM` tasks using `SendMessageBatch` (10 at a time).
- Enforce screening throughput and execute screening calls for selected types.
- Enforce throughput constraint via fixed-rate limiter (`SCREENING_TPS`) and concurrency cap (`SCREENING_PARALLEL_MESSAGES`) per worker task.
- Persist item results (completed/failed) into the database.
- Periodically check due daily schedules and trigger new batch jobs.
- Apply retention policy cleanup for audit/access/error stores.
- Emit high-risk audit alerts when external API failures exceed configured threshold/window.
- Use pooled PostgreSQL connections with retry/backoff for transient DB acquisition failures.
- Emit detailed CloudWatch logs for async screening start/success/failure, including raw external API request/response payloads with redaction.

### 4.4 Screening Engine Adapter (Actimize Watchlist Adapter)

Responsibilities:
- Provide `screen_single` and `screen_many_types`.
- Normalize results into a stable structure for UI consumption.
- Support mock screening for demos/dev environments.
- Accept Prudential wrapper responses that use either `status_code` or `statusCode`, and unwrap nested `body` payloads before normalization.
- Enforce current Prudential response contract:
  - HTTP `200` + payload `message="PM"` => potential match
  - HTTP `200` + payload `message="NM"` => clear
  - any other payload/status => failure

Note: In this repo, the adapter is configured for the Actimize/Kong sanctions API and preserves the "single-type per request" behavior required by Actimize-style engines.

### 4.5 Data Store (PostgreSQL)

Responsibilities:
- Persist job metadata, per-item status transitions, request payloads, and response payloads.
- Persist daily schedules and next-run calculations.
- Persist audit events for compliance and troubleshooting.
- Persist API access logs (`api_access_logs`) for request/response traceability.
- Persist external API failures (`external_api_errors`) with provider/operation context.
- Persist source-upload metadata (`batch_file_uploads`) and daily schedule dedupe state (`schedule_record_state`).
- Separate schema initialization from runtime by using `python -m app.init_db` during setup/deployment.

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

### 5.5 Database Design Diagram

```mermaid
erDiagram
  jobs ||--o{ job_items : contains
  jobs ||--|| job_metadata : describes
  batch_file_uploads o|--o| jobs : source_upload_for
  daily_schedules o|--o{ schedule_subscriptions : has
  daily_schedules o|--o{ schedule_record_state : tracks
  daily_schedules o|--o{ jobs : triggers
  jobs o|--o| job_schedule_notifications : notifies_once
  daily_schedules o|--o{ schedule_notifications : emits
  business_units ||--o{ user_business_units : maps
  business_units ||--o{ daily_schedules : scopes
  business_units ||--o{ job_metadata : scopes
  jobs o|--o{ external_api_errors : may_record
  jobs o|--o{ audit_events : may_record
```

### 5.6 Table Names, Structure, and Use Case

#### `jobs`

- Primary key: `job_id`
- Core columns: `status`, `created_at`, `updated_at`, `total_items`, `source_schedule_id`, `source_upload_id`, `user_id`, `user_name`
- Use case: top-level execution container for sync, batch, and scheduled screening runs

#### `job_items`

- Primary key: `(job_id, item_key)`
- Core columns: `request_json`, `response_json`, `status`, `error_text`, `updated_at`
- Use case: per-record screening state and normalized response storage

#### `job_metadata`

- Primary key: `job_id`
- Core columns: `mode`, `screening_types_json`, `mock_screening`, `batch_name`, `file_name`, `daily_screening`, `schedule_frequency`, `daily_schedule_id`, `query_count`, `deferred_until`, `business_unit_code`
- Use case: UI/history metadata for jobs that does not belong in the execution counter table

#### `daily_schedules`

- Primary key: `schedule_id`
- Core columns: `batch_name`, `user_id`, `user_name`, `queries_json`, `screening_types_json`, `mock_screening`, `schedule_frequency`, `timezone`, `run_hour`, `run_minute`, `created_at`, `last_run_at`, `next_run_at`, `is_active`, `source_upload_id`, `source_file_name`, `source_s3_uri`, `business_unit_code`
- Use case: persisted recurring-screening definitions and next-run state

#### `batch_file_uploads`

- Primary key: `upload_id`
- Core columns: `schedule_id`, `job_id`, `user_id`, `user_name`, `file_name`, `s3_bucket`, `s3_key`, `s3_uri`, `queries_s3_bucket`, `queries_s3_key`, `queries_s3_uri`, `file_hash`, `record_count`, `created_at`, `is_active`
- Use case: traceability for uploaded source files and backend-generated `queries.json`

#### `schedule_record_state`

- Primary key: `(schedule_id, record_hash)`
- Core columns: `first_seen_at`, `last_screened_at`, `last_job_id`
- Use case: dedupe and incremental daily schedule behavior so unchanged records are not rescreened unnecessarily

#### `schedule_subscriptions`

- Primary key: `subscription_id`
- Core columns: `schedule_id`, `user_id`, `user_name`, `email`, `is_active`, `created_at`, `updated_at`
- Use case: scheduled screening completion recipients

#### `job_schedule_notifications`

- Primary key: `job_id`
- Core columns: `schedule_id`, `created_at`
- Use case: idempotency guard so one scheduled job triggers notifications once

#### `schedule_notifications`

- Primary key: `notification_id`
- Core columns: `created_at`, `user_id`, `user_name`, `email`, `schedule_id`, `job_id`, `title`, `message`, `summary_json`
- Use case: notification outbox/audit trail for schedule completion messaging

#### `audit_events`

- Primary key: `event_id`
- Core columns: `created_at`, `user_id`, `user_name`, `action`, `entity_type`, `entity_id`, `details_json`
- Use case: admin/compliance-facing audit trail for screening, auth, and operational actions

#### `api_access_logs`

- Primary key: `access_id`
- Core columns: `created_at`, `correlation_id`, `request_method`, `request_path`, `query_string`, `status_code`, `duration_ms`, `client_ip`, `user_agent`, `user_id`, `user_name`, `auth_state`, `details_json`
- Use case: request-level operational traceability for `/api/v1/*`

#### `external_api_errors`

- Primary key: `error_id`
- Core columns: `created_at`, `provider`, `operation`, `endpoint`, `status_code`, `user_id`, `user_name`, `job_id`, `item_key`, `error_text`, `details_json`
- Use case: upstream screening failure analysis and alerting

#### `business_units`

- Primary key: `business_unit_code`
- Core columns: `business_unit_name`, `is_active`, `created_at`, `updated_at`
- Use case: runtime-managed reference data for business-unit authorization and submission scoping

#### `user_business_units`

- Primary key: `(user_id, business_unit_code)`
- Core columns: `user_name`, `is_active`, `created_at`, `updated_at`
- Use case: user-to-business-unit authorization mapping used by screening submission flows

## 6. Backend API Container Design

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

All public REST endpoints in this section are owned by the `backend` container in ECS service `ofac-screening-backend-svc`.

| Method | Path | Container | Required Permission | Functionality |
|---|---|---|---|---|
| `GET` | `/health` | `backend` | None | Liveness/readiness response (`{"status":"ok"}`). |
| `POST` | `/api/v1/screenings/jobs` | `backend` | `screening.write` or `screening.daily` or `screening.admin` | Creates async screening job from JSON payload (`queries`, screening types, schedule options). If `daily_screening=true`, schedule is created/updated and first execution is deferred to schedule time. |
| `POST` | `/api/v1/screenings/batch-upload` | `backend` | `screening.write` or `screening.daily` or `screening.admin` | Uploads batch file + metadata only, validates file content rules on the backend, normalizes rows into `EntityExample` payloads, optionally stores source and generated `queries.json` in S3, and returns `row_meta` for UI rendering. For scheduled/daily runs, creates job/schedule. For immediate large runs, requires S3 upload enabled and enqueues a `JOB_DISPATCH` message so the worker can expand/enqueue per-record tasks without request timeouts. Supports optional subscription creation for schedules. |
| `GET` | `/api/v1/screenings/jobs/{job_id}` | `backend` | `screening.read` | Returns job progress counts and terminal responses when complete. |
| `GET` | `/api/v1/screenings/submissions` | `backend` | `screening.read` | Returns legacy user-visible submission history for single and batch runs with normalized result status. |
| `GET` | `/api/v1/screenings/summary` | `backend` | `screening.read` | Returns full-history dashboard counts for the signed-in user (`total`, `clear`, `potential`, `pending`, `failed`, `match`) without loading result rows. |
| `GET` | `/api/v1/screenings/results` | `backend` | `screening.read` | Returns only the latest `300` normalized screening-result rows for the signed-in user, ordered newest-first for fast grid rendering. |
| `POST` | `/api/v1/screenings/match` | `backend` | `screening.write` or `screening.single.mock` or `screening.admin` | Performs synchronous screening, persists job/item metadata, returns immediate merged results; logs per-item API call success/failure. |
| `GET` | `/api/v1/screenings/daily-schedules` | `backend` | `screening.read` | Lists active schedules with frequency, next run, source file metadata, and business unit. |
| `DELETE` | `/api/v1/screenings/daily-schedules/{schedule_id}` | `backend` | `screening.daily` or `screening.admin` | Disables one daily schedule and writes audit event. |
| `GET` | `/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` | `backend` | `screening.read` | Lists subscriptions for a schedule (scoped to caller context). |
| `POST` | `/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` | `backend` | `screening.read` | Upserts subscription email for schedule notifications. |
| `DELETE` | `/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` | `backend` | `screening.read` | Removes subscription by email for the schedule. |
| `GET` | `/api/v1/business-units` | `backend` | `screening.read` | Returns active business units mapped to current user. |
| `GET` | `/api/v1/admin/business-units` | `backend` | `screening.admin` or `screening.useradmin` | Lists all business units (`include_inactive` supported). |
| `POST` | `/api/v1/admin/business-units` | `backend` | `screening.admin` or `screening.useradmin` | Creates new business unit reference row. |
| `PUT` | `/api/v1/admin/business-units/{business_unit_code}` | `backend` | `screening.admin` or `screening.useradmin` | Updates business unit code/name and cascades code change to mappings/metadata. |
| `DELETE` | `/api/v1/admin/business-units/{business_unit_code}` | `backend` | `screening.admin` or `screening.useradmin` | Deletes business unit and related user mappings. |
| `GET` | `/api/v1/admin/business-unit-mappings` | `backend` | `screening.admin` or `screening.useradmin` | Lists user-to-business-unit mappings. |
| `PUT` | `/api/v1/admin/business-unit-mappings/{user_id}` | `backend` | `screening.admin` or `screening.useradmin` | Replaces mapping for one user with supplied business unit list. |
| `GET` | `/api/v1/admin/users` | `backend` | `screening.admin` or `screening.useradmin` | Lists known users (DB + Cognito user pool enumeration fallback). |
| `GET` | `/api/v1/audit-events` | `backend` | `screening.admin` or `screening.useradmin` | Returns audit events with pagination (`limit`, `offset`) and optional `user_id` filter. |
| `GET` | `/api/v1/audit-events/page` | `backend` | `screening.admin` or `screening.useradmin` | Returns paged audit events with `items`, `total`, `limit`, `offset`, optional `user_id`, and `errors_only` filtering. |

### 6.3 API Specifications by Functional Group

All APIs below are served by the `backend` container in `ofac-screening-backend-svc`.

#### 6.3.1 Health and Screening APIs

##### `GET /health` (`backend`)

Request:

```http
GET /health HTTP/1.1
Host: d3ppga4y8wg1ck.cloudfront.net
```

Response:

```json
{
  "status": "ok"
}
```

##### `POST /api/v1/screenings/jobs` (`backend`)

Request:

```json
{
  "queries": {
    "P001": {
      "schema": "Person",
      "properties": {
        "partyKey": "P001",
        "name": ["Jane Doe"],
        "birthDate": ["1980-01-01"],
        "gender": ["Female"]
      }
    }
  },
  "screening_types": ["Sanction", "PEP"],
  "mock_screening": false,
  "business_unit_code": "US_PRU_HR",
  "daily_screening": false,
  "schedule_frequency": "DAILY",
  "schedule_run_at": null,
  "schedule_id": null,
  "batch_name": "Example Batch"
}
```

Response:

```json
{
  "job_id": "6a2bb3b7-6a2f-4c6b-9f4a-3c82e7c4f2ad",
  "status": "QUEUED",
  "submitted_at": "2026-03-08T21:12:33.123456+00:00",
  "total_items": 1,
  "business_unit_code": "US_PRU_HR",
  "daily_schedule_id": null,
  "screened_item_keys": []
}
```

##### `POST /api/v1/screenings/batch-upload` (`backend`)

Request:
- multipart form-data
- required parts: `file`, `business_unit_code`
- common optional parts: `screening_types_json`, `batch_name`, `daily_screening`, `schedule_frequency`, `mock_screening`

Example:

```text
file=batch.xlsx
screening_types_json=["Sanction"]
business_unit_code=US_PRU_HR
batch_name=PGIM_SANCTION_BATCH
daily_screening=false
mock_screening=false
```

Response:

```json
{
  "job_id": "493f2ca6-6b61-4017-8220-843d377d436b",
  "status": "QUEUED",
  "submitted_at": "2026-03-22T19:39:54.995828+00:00",
  "total_items": 1000,
  "business_unit_code": "US_PRU_HR",
  "daily_schedule_id": null,
  "screened_item_keys": [],
  "source_upload_id": "298c33ad-c110-4d7e-a03b-b742fff5cea2",
  "file_name": "batch.xlsx",
  "s3_uri": "s3://amzn-s3-quickscreen-batch/screening-input/.../batch.xlsx",
  "schedule_frequency": null,
  "row_meta": [
    {
      "key": "AMLP_I_000001",
      "display_name": "Jane Doe",
      "ui_type": "Individual"
    }
  ]
}
```

##### `GET /api/v1/screenings/jobs/{job_id}` (`backend`)

Request:

```text
GET /api/v1/screenings/jobs/493f2ca6-6b61-4017-8220-843d377d436b
```

Response:

```json
{
  "job_id": "493f2ca6-6b61-4017-8220-843d377d436b",
  "status": "COMPLETED",
  "submitted_at": "2026-03-22T19:39:54.995828+00:00",
  "total_items": 1000,
  "completed_items": 1000,
  "failed_items": 0,
  "pending_items": 0,
  "processing_items": 0,
  "responses": {
    "AMLP_I_000001": {
      "results": [],
      "total": { "value": 0, "relation": "eq" },
      "query": {
        "schema": "Person",
        "properties": {
          "partyKey": "AMLP_I_000001",
          "name": ["Jane Doe"]
        }
      },
      "status": 200,
      "engine_message": "NM"
    }
  },
  "limit": 5
}
```

##### `GET /api/v1/screenings/submissions` (`backend`)

Request:

```text
GET /api/v1/screenings/submissions?limit=5
```

Response:

```json
[
  {
    "id": "493f2ca6-6b61-4017-8220-843d377d436b",
    "mode": "BATCH",
    "createdAt": "2026-03-22T19:39:54.995828+00:00",
    "businessUnitCode": "US_PRU_HR",
    "overallResult": "NO_HIT",
    "screeningTypes": ["Sanction"],
    "fileName": "batch.xlsx"
  }
]
```

##### `GET /api/v1/screenings/summary` (`backend`)

Request:

```text
GET /api/v1/screenings/summary
```

Response:

```json
{
  "total": 71981,
  "clear": 55235,
  "potential": 0,
  "pending": 101,
  "failed": 16746,
  "match": 0
}
```

##### `GET /api/v1/screenings/results` (`backend`)

Request:

```text
GET /api/v1/screenings/results?limit=300
```

Response:

```json
[
  {
    "id": "493f2ca6-6b61-4017-8220-843d377d436b_AMLP_I_000001",
    "entity": "Jane Doe",
    "partyKey": "AMLP_I_000001",
    "mode": "BATCH",
    "type": "Individual",
    "country": "US",
    "engineStatus": "NO_HIT",
    "manualMatch": false,
    "uiStatus": "Clear",
    "matchingScore": null,
    "submittedAt": "2026-03-22T19:39:54.995828+00:00",
    "batchSubmissionId": "493f2ca6-6b61-4017-8220-843d377d436b",
    "dailyScheduleId": null,
    "dailyScheduleActive": false
  }
]
```

##### `POST /api/v1/screenings/match` (`backend`)

Request:

```json
{
  "queries": {
    "AMLP_DD083427C0BB6275": {
      "schema": "Person",
      "properties": {
        "partyKey": "AMLP_DD083427C0BB6275",
        "name": ["Janki Bhavsar"],
        "address": ["101 Arrowgate Drive"],
        "country": ["US"]
      }
    }
  },
  "screening_types": ["Sanction"],
  "mock_screening": false,
  "business_unit_code": "US_PRU_HR"
}
```

Response:

```json
{
  "responses": {
    "AMLP_DD083427C0BB6275": {
      "results": [],
      "total": { "value": 0, "relation": "eq" },
      "query": {
        "schema": "Person",
        "properties": {
          "partyKey": "AMLP_DD083427C0BB6275",
          "name": ["Janki Bhavsar"]
        }
      },
      "status": 200
    }
  },
  "limit": 5
}
```

#### 6.3.2 Daily Schedule APIs

##### `GET /api/v1/screenings/daily-schedules` (`backend`)

Request:

```text
GET /api/v1/screenings/daily-schedules
```

Response:

```json
[
  {
    "schedule_id": "sch_123",
    "batch_name": "Actimize_Sanction_Daily_Screening",
    "user_id": "610bf5e0-e011-70f9-6430-21484b3de4f4",
    "user_name": "Tapankumar Bhavsar",
    "business_unit_code": "US_PRU_HR",
    "screening_types": ["Sanction"],
    "schedule_frequency": "DAILY",
    "timezone": "America/New_York",
    "run_hour": 0,
    "run_minute": 22,
    "created_at": "2026-03-19T00:00:00+00:00",
    "last_run_at": "2026-03-25T04:22:00+00:00",
    "next_run_at": "2026-03-26T04:22:00+00:00",
    "total_items": 100,
    "is_active": true
  }
]
```

##### `DELETE /api/v1/screenings/daily-schedules/{schedule_id}` (`backend`)

Request:

```text
DELETE /api/v1/screenings/daily-schedules/sch_123
```

Response:

```json
{
  "status": "removed",
  "schedule_id": "sch_123"
}
```

##### `GET /api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` (`backend`)

Request:

```text
GET /api/v1/screenings/daily-schedules/sch_123/subscriptions
```

Response:

```json
[
  {
    "subscription_id": "sub_123",
    "schedule_id": "sch_123",
    "user_id": "610bf5e0-e011-70f9-6430-21484b3de4f4",
    "user_name": "Tapankumar Bhavsar",
    "email": "tdbhavsar@gmail.com",
    "is_active": true,
    "created_at": "2026-03-22T10:00:00+00:00"
  }
]
```

##### `POST /api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` (`backend`)

Request:

```text
POST /api/v1/screenings/daily-schedules/sch_123/subscriptions?email=tdbhavsar@gmail.com
```

Response:

```json
{
  "subscription_id": "sub_123",
  "schedule_id": "sch_123",
  "user_id": "610bf5e0-e011-70f9-6430-21484b3de4f4",
  "user_name": "Tapankumar Bhavsar",
  "email": "tdbhavsar@gmail.com",
  "is_active": true,
  "created_at": "2026-03-22T10:00:00+00:00"
}
```

##### `DELETE /api/v1/screenings/daily-schedules/{schedule_id}/subscriptions` (`backend`)

Request:

```text
DELETE /api/v1/screenings/daily-schedules/sch_123/subscriptions?email=tdbhavsar@gmail.com
```

Response:

```json
{
  "status": "removed",
  "schedule_id": "sch_123",
  "email": "tdbhavsar@gmail.com"
}
```

#### 6.3.3 Reference Data and Administration APIs

##### `GET /api/v1/business-units` (`backend`)

Request:

```text
GET /api/v1/business-units
```

Response:

```json
[
  {
    "business_unit_code": "US_PRU_HR",
    "business_unit_name": "US Prudential HR",
    "is_active": true,
    "created_at": "2026-03-09T15:22:00+00:00",
    "updated_at": "2026-03-24T19:10:00+00:00"
  }
]
```

##### `GET /api/v1/admin/business-units` (`backend`)

Request:

```text
GET /api/v1/admin/business-units?include_inactive=true
```

Response:

```json
[
  {
    "business_unit_code": "US_PRU_HR",
    "business_unit_name": "US Prudential HR",
    "is_active": true,
    "created_at": "2026-03-09T15:22:00+00:00",
    "updated_at": "2026-03-24T19:10:00+00:00"
  },
  {
    "business_unit_code": "LEGACY_TEST",
    "business_unit_name": "Legacy Test Unit",
    "is_active": false,
    "created_at": "2026-02-01T11:00:00+00:00",
    "updated_at": "2026-03-01T11:00:00+00:00"
  }
]
```

##### `POST /api/v1/admin/business-units` (`backend`)

Request:

```json
{
  "business_unit_code": "GLOBAL_COMPLIANCE",
  "business_unit_name": "Global Compliance"
}
```

Response:

```json
{
  "business_unit_code": "GLOBAL_COMPLIANCE",
  "business_unit_name": "Global Compliance",
  "is_active": true,
  "created_at": "2026-03-25T14:55:00+00:00",
  "updated_at": "2026-03-25T14:55:00+00:00"
}
```

##### `PUT /api/v1/admin/business-units/{business_unit_code}` (`backend`)

Request:

```json
{
  "business_unit_code": "GLOBAL_COMPLIANCE",
  "business_unit_name": "Enterprise Compliance"
}
```

Response:

```json
{
  "business_unit_code": "GLOBAL_COMPLIANCE",
  "business_unit_name": "Enterprise Compliance",
  "is_active": true,
  "created_at": "2026-03-25T14:55:00+00:00",
  "updated_at": "2026-03-25T15:00:00+00:00"
}
```

##### `DELETE /api/v1/admin/business-units/{business_unit_code}` (`backend`)

Request:

```text
DELETE /api/v1/admin/business-units/GLOBAL_COMPLIANCE
```

Response:

```json
{
  "status": "removed",
  "business_unit_code": "GLOBAL_COMPLIANCE"
}
```

##### `GET /api/v1/admin/business-unit-mappings` (`backend`)

Request:

```text
GET /api/v1/admin/business-unit-mappings
```

Response:

```json
[
  {
    "user_id": "610bf5e0-e011-70f9-6430-21484b3de4f4",
    "user_name": "Tapankumar Bhavsar",
    "business_unit_codes": ["US_PRU_HR", "GLOBAL_COMPLIANCE"]
  }
]
```

##### `PUT /api/v1/admin/business-unit-mappings/{user_id}` (`backend`)

Request:

```json
{
  "user_name": "Tapankumar Bhavsar",
  "business_unit_codes": ["US_PRU_HR", "GLOBAL_COMPLIANCE"]
}
```

Response:

```json
{
  "user_id": "610bf5e0-e011-70f9-6430-21484b3de4f4",
  "user_name": "Tapankumar Bhavsar",
  "business_unit_codes": ["US_PRU_HR", "GLOBAL_COMPLIANCE"]
}
```

##### `GET /api/v1/admin/users` (`backend`)

Request:

```text
GET /api/v1/admin/users
```

Response:

```json
[
  {
    "user_id": "610bf5e0-e011-70f9-6430-21484b3de4f4",
    "display_name": "Tapankumar Bhavsar"
  },
  {
    "user_id": "perf_load_user_01",
    "display_name": "perf_load_user_01"
  }
]
```

#### 6.3.4 Audit and Operational Trace APIs

##### `GET /api/v1/audit-events` (`backend`)

Request:

```text
GET /api/v1/audit-events?limit=50&offset=0&user_id=610bf5e0-e011-70f9-6430-21484b3de4f4
```

Response:

```json
[
  {
    "event_id": 18742,
    "created_at": "2026-03-25T15:05:00+00:00",
    "user_id": "610bf5e0-e011-70f9-6430-21484b3de4f4",
    "user_name": "Tapankumar Bhavsar",
    "action": "SYNC_SCREENING_SUBMITTED",
    "entity_type": "screening_job",
    "entity_id": "job_123",
    "details": {
      "business_unit_code": "US_PRU_HR",
      "correlation_id": "e2df2ee7-ff05-4e8c-9b7d-7d08f45e8c1b"
    }
  }
]
```

##### `GET /api/v1/audit-events/page` (`backend`)

Request:

```text
GET /api/v1/audit-events/page?limit=100&offset=0&errors_only=true
```

Response:

```json
{
  "items": [
    {
      "event_id": 18744,
      "created_at": "2026-03-25T15:06:00+00:00",
      "user_id": "610bf5e0-e011-70f9-6430-21484b3de4f4",
      "user_name": "Tapankumar Bhavsar",
      "action": "SYNC_SCREENING_API_CALL_FAILED",
      "entity_type": "screening_item",
      "entity_id": "job_123:AMLP_000001",
      "details": {
        "status_code": 500,
        "provider": "prudential",
        "operation": "entity-screenings"
      }
    }
  ],
  "total": 42,
  "limit": 100,
  "offset": 0
}
```

## 7. Component Interaction Flows

### 7.1 Frontend-Initiated Authentication Flow

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

### 7.2 Frontend-Initiated Screening Flows

#### 7.2.1 Single Screening (Sync)

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

#### 7.2.2 Batch Screening (Async - JSON Submit)

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

#### 7.2.3 Batch Upload (Async - Large Batch Dispatch)

```mermaid
sequenceDiagram
  participant UI as Frontend
  participant API as FastAPI
  participant DB as PostgreSQL
  participant S3 as S3 Upload Bucket
  participant Q as SQS
  participant WK as Worker

  UI->>API: POST /api/v1/screenings/batch-upload (multipart: file + metadata)
  API->>API: parse + validate file, build normalized queries
  API->>S3: upload source file + generated queries.json
  API->>DB: register batch upload + create job (queued)
  API->>Q: enqueue JOB_DISPATCH (job_id + upload_id)
  API-->>UI: 202 {job_id, status=queued, row_meta}

  WK->>Q: receive JOB_DISPATCH
  WK->>S3: download queries.json
  WK->>DB: bulk insert job_items
  WK->>Q: enqueue SCREEN_ITEM messages in batches (SendMessageBatch)
  WK->>Q: delete JOB_DISPATCH
```

### 7.3 Worker-Initiated Scheduling and Rollup Flows

#### 7.3.1 Daily Screening Trigger (Worker Scheduler)

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

#### 7.3.2 Batch Job Status Rollup

```mermaid
stateDiagram-v2
  [*] --> queued
  queued --> processing: worker starts items
  processing --> completed: all items done and >=1 success
  processing --> failed: all items done and all failed
```

### 7.4 Cross-Component Observability Flow

#### 7.4.1 Correlation and Access Audit Flow

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

## 8. Operational Design by Component

### 8.1 Worker Container Throughput and Rate Limiting

- Worker enforces a fixed-rate schedule for outbound screening calls.
- Default is `32 TPS` across the worker process.
- Worker concurrency is controlled separately by `SCREENING_PARALLEL_MESSAGES` per ECS task.
- Overall throughput is therefore a function of:
  - ECS worker desired count
  - `SCREENING_PARALLEL_MESSAGES`
  - `SCREENING_TPS`
  - upstream Prudential latency/error rate

### 8.2 Backend and Worker Resilience

- Worker marks failures per item; job can still complete with partial failures.
- Messages are deleted after processing to avoid duplicates (at-least-once queue semantics should be accounted for by idempotent writes).
- Daily schedule trigger uses a claim step to reduce duplicate schedule runs.
- Prudential/Actimize HTTP `429/500/502/503/504` responses are retried with exponential backoff.
- Prudential wrapped responses are normalized whether they use `status_code/body` or `statusCode/body`.
- Repository uses a shared PostgreSQL connection pool per process and retries transient DB acquisition failures.
- Runtime API/worker processes validate schema only; schema creation/migration is an explicit deployment/setup step via `python -m app.init_db`.

### 8.3 Backend and Worker Observability

- Application logs shipped to CloudWatch via ECS log driver.
- Audit events provide a business-level trail, separate from system logs.
- API access logs provide request-level traceability with latency and auth state.
- Correlation id is propagated to queue/worker/external error records for end-to-end troubleshooting.
- Raw Prudential/Actimize request and response payloads are logged to CloudWatch when `ACTIMIZE_LOG_RAW_API_IO=true`.
- Sensitive fields such as bearer tokens, client assertions, secrets, and access tokens are redacted before logging.
- Worker troubleshooting logs now capture the same raw wrapped Prudential success/error payload shapes seen by sync screening, which is important when batch and sync behavior diverge because of parser-version drift.

### 8.4 Data Store Retention and Risk Alerting

- Worker executes periodic retention cleanup for:
  - `audit_events`
  - `api_access_logs`
  - `external_api_errors`
- Retention windows are configurable with environment variables.
- High-risk alerting rule:
  - If external API failures exceed configured threshold inside configured time window, worker records `HIGH_RISK_EXTERNAL_API_FAILURE_ALERT` in `audit_events`.
- Access-log query parameters are redacted for sensitive key types (token/secret/password/email-like fields).

### 8.5 ECS Cost Controls (Dev)

- Keep worker desired count at `0` when not testing batch/daily.
- Use small Fargate tasks (256/512) for dev.
- Use minimal RDS instance for dev and stop when not needed (per environment policy).
- Active batch-performance deployments may intentionally pin the worker service above zero and override `SCREENING_PARALLEL_MESSAGES`; this is an operational deployment choice, not a config default.

### 8.6 Performance Validation Snapshot (2026-04-08)

Latest retained batch-upload performance artifact:
- `artifacts/perf/batch_upload_same_file_20_users_2026-04-08T17-23-25-021Z.json`

Test profile:
- `20` concurrent authenticated browser users
- Shared CloudFront endpoint: `https://d3ppga4y8wg1ck.cloudfront.net`
- Same uploaded Excel file for all users
- File size/workload represented `1000` screening rows per successful submission
- Objective: validate whether the large-batch upload flow can return the accepted/queued response before CloudFront times out

Observed result summary:

| Metric | Result |
|---|---|
| Test start | `2026-04-08T17:23:26.672Z` |
| Concurrent users | `20` |
| Successful submissions | `11` |
| Failed submissions | `9` |
| Overall success rate | `55.0%` |
| Successful submit latency | `17.6s` min / `42.6s` p50 / `49.2s` p95 / `52.1s` max |
| All-attempt latency | `17.6s` min / `46.0s` p50 / `60.3s` p95 / `60.3s` max |
| CloudFront `504` failures | `7` |
| Non-HTTP test/setup failures | `2` (`No Business Unit option available`) |

Interpretation:
- The April 8, 2026 run shows the large-batch dispatch design is **partially effective**: more than half of users received a successful queued response for a `1000`-row upload without waiting for per-item screening completion.
- The remaining primary failure mode is still **front-door request timeout during submission**, evidenced by `7` CloudFront `504 Gateway Timeout` responses clustered around `60s`.
- Two failures were not backend timeout failures; they were test-session/setup issues where the UI reported `No Business Unit option available`.
- Based on these timings, the current architecture reduces but does **not yet fully eliminate** request-time bottlenecks for concurrent large uploads. Additional reduction in synchronous pre-queue processing time may still be required for reliable `20 x 1000-row` parallel submissions through CloudFront.

## 9. Deployment Artifacts

- ECS task definitions in `deploy/ecs/`
  - `frontend-task-definition.json`
  - `backend-task-definition.json`
  - `worker-task-definition.json`
- CloudFront distribution config example in `deploy/cloudfront-distribution-config.json`

## 10. Appendix: Runtime Configuration

### 10.1 Frontend (container env)

Frontend settings are provided as container env vars and written at startup into `app-config.js` (see `frontend/entrypoint.sh`).

| Parameter | Default Value | Explanation |
|---|---:|---|
| `BACKEND_UPSTREAM` | `http://backend.screening.internal:8000` | Backend origin that Nginx proxies to for `/api/*` (typically the ECS service-discovery name). |
| `NGINX_CLIENT_MAX_BODY_SIZE` | `25m` | Max upload size for `/api/` reverse-proxy requests (must accommodate batch source files). |
| `VITE_SCREENING_API_BASE_URL` | `/api/v1` | Base path used by the SPA for API requests (Nginx proxies `/api/*` to backend). |
| `VITE_SCREENING_POLL_INTERVAL_MS` | `750` | UI polling interval for job progress (`GET /api/v1/screenings/jobs/{job_id}`). |
| `VITE_SCREENING_JOB_TIMEOUT_MS` | `90000` | UI timeout for long-running job polling flows before surfacing a timeout to the user. |
| `VITE_ACTIMIZE_REVIEW_ALERT_URL` | *(empty)* | Optional review-alert URL shown in hit-entity details. |
| `VITE_AUTH_ENABLED` | `false` | Enables OIDC login + bearer token attachment to API calls. |
| `VITE_OIDC_AUTHORITY` | *(empty)* | OIDC issuer/authority URL (required when `VITE_AUTH_ENABLED=true`). |
| `VITE_OIDC_CLIENT_ID` | *(empty)* | OIDC client id (required when `VITE_AUTH_ENABLED=true`). |
| `VITE_OIDC_REDIRECT_URI` | *(empty)* | OIDC redirect URI. If blank, frontend code falls back to `${window.location.origin}/`. |
| `VITE_OIDC_POST_LOGOUT_REDIRECT_URI` | *(empty)* | Optional post-logout redirect. If blank, frontend falls back to the redirect URI. |
| `VITE_OIDC_SCOPE` | `openid profile email` | Requested scopes (add `roles` / group scope if your IdP requires it). |
| `VITE_OIDC_IDLE_TIMEOUT_MS` | `900000` | Frontend session idle timeout (ms). |
| `VITE_OIDC_CLEAR_SESSION_ON_CLOSE` | `true` | If `true`, clears stored auth/session state when the browser tab is closed. |

### 10.2 Backend/Worker (container env)

Backend and worker share the same settings (see `backend/app/config.py` and `backend/.env.example`).

| Parameter | Default Value | Explanation |
|---|---:|---|
| `APP_NAME` | `OFAC Screening Enterprise API` | Used by FastAPI for service metadata/log labeling. |
| `APP_VERSION` | `1.0.0` | Used by FastAPI for service metadata. |
| `APP_DB_PATH` | `/tmp/screening.db` | SQLite path (used when `APP_DB_URL` is not configured). |
| `APP_DB_URL` | *(empty)* | PostgreSQL connection string. Set in AWS deployments (recommended). |
| `DB_POOL_MIN_SIZE` | `1` | Minimum PostgreSQL pooled connections per process. |
| `DB_POOL_MAX_SIZE` | `8` | Maximum PostgreSQL pooled connections per process. |
| `DB_POOL_TIMEOUT_S` | `5.0` | Connection-pool acquisition timeout. |
| `DB_CONNECT_MAX_ATTEMPTS` | `4` | Retry attempts for transient DB acquisition failures. |
| `DB_CONNECT_BACKOFF_INITIAL_MS` | `100` | Initial DB retry backoff. |
| `DB_CONNECT_BACKOFF_MAX_MS` | `1500` | Max DB retry backoff. |
| `CORS_ALLOW_ORIGINS` | `*` | CORS allow-list for API responses. Tighten in production. |
| `MULTIPART_MAX_PART_SIZE` | `25m` | Max multipart part size accepted by the backend for `/screenings/batch-upload`. |
| `AWS_REGION` | `us-east-1` | AWS region for SQS/S3/SNS clients. |
| `AWS_SQS_QUEUE_NAME` | `screening-requests` | Queue used for async screening. |
| `AWS_ENDPOINT_URL` | *(empty)* | Optional override for localstack/dev. |
| `AWS_ACCESS_KEY_ID` | *(empty)* | Optional static credentials (prefer ECS task role in AWS). |
| `AWS_SECRET_ACCESS_KEY` | *(empty)* | Optional static credentials (prefer ECS task role in AWS). |
| `AWS_S3_UPLOAD_BUCKET` | *(empty)* | Enables S3 storage for uploads. Required for large batch `JOB_DISPATCH` flow. |
| `AWS_S3_UPLOAD_PREFIX` | `screening-input` | Key prefix for S3 uploads (source files and `queries.json`). |
| `AWS_SNS_NOTIFICATIONS_ENABLED` | `false` | Enables SNS notifications for scheduled screening completion. |
| `AWS_SNS_SCHEDULE_TOPIC_PREFIX` | `ofac-screening-schedule` | Prefix used for SNS topics created for schedule/email notifications. |
| `ACTIMIZE_MOCK` | `false` | If `true`, returns deterministic mock responses instead of calling Actimize. |
| `ACTIMIZE_BASE_URL` | *(empty)* | Base URL for Actimize screening API (required when not mocking). |
| `ACTIMIZE_PROVIDER` | `prudential` | Provider label used in audit/error telemetry. |
| `ACTIMIZE_API_KEY` | *(empty)* | Optional API key auth (sent via headers when configured). |
| `ACTIMIZE_BEARER_TOKEN` | *(empty)* | Optional static bearer token auth (sent via headers when configured). |
| `ACTIMIZE_TOKEN_URL` | *(empty)* | OAuth token endpoint for client-credentials (when using dynamic bearer tokens). |
| `ACTIMIZE_CLIENT_ID` | *(empty)* | OAuth client id (required if `ACTIMIZE_TOKEN_URL` is set). |
| `ACTIMIZE_CLIENT_SECRET` | *(empty)* | OAuth client secret (optional if using client assertion). |
| `ACTIMIZE_CLIENT_ASSERTION_TYPE` | `urn:ietf:params:oauth:client-assertion-type:jwt-bearer` | OAuth client assertion type when using JWT client assertion. |
| `ACTIMIZE_CLIENT_ASSERTION_ALGORITHM` | `RS256` | JWT signing algorithm for client assertion. |
| `ACTIMIZE_CLIENT_ASSERTION_AUDIENCE` | *(empty)* | JWT audience; defaults to `ACTIMIZE_TOKEN_URL` when unset. |
| `ACTIMIZE_CLIENT_ASSERTION_KID` | *(empty)* | Optional JWT header `kid` for key selection. |
| `ACTIMIZE_CLIENT_ASSERTION_PRIVATE_KEY` | *(empty)* | PEM private key for client assertion (inline). |
| `ACTIMIZE_CLIENT_ASSERTION_PRIVATE_KEY_B64` | *(empty)* | PEM private key for client assertion (base64-encoded). |
| `ACTIMIZE_CLIENT_ASSERTION_PRIVATE_KEY_PATH` | *(empty)* | PEM private key for client assertion (file path). |
| `ACTIMIZE_SCOPE` | *(empty)* | Optional OAuth scope string for token request. |
| `ACTIMIZE_SOURCE_SYSTEM` | `ZIP` | Sent in Actimize payload as `sourceSystem` and used when deriving fallback `partyKey`. |
| `ACTIMIZE_REQUESTER_NAME` | `SCREENING_SYSTEM` | Default requester name sent in Actimize payload when user name is not provided. |
| `ACTIMIZE_ALERT_REVIEW_URL` | *(empty)* | Optional URL included in scheduled completion notifications for where to review alerts. |
| `ACTIMIZE_TIMEOUT_S` | `10.0` | HTTP timeout (seconds) for Actimize requests. |
| `ACTIMIZE_LOG_RAW_API_IO` | `false` | Enables raw upstream request/response logging to CloudWatch with redaction. |
| `ACTIMIZE_RAW_API_LOG_MAX_CHARS` | `20000` | Max raw request/response characters retained per log entry. |
| `SCREENING_TPS` | `32` | Worker outbound throughput cap (TPS). |
| `SCREENING_PARALLEL_MESSAGES` | `1` | Max in-flight SQS screening items processed concurrently per worker task. |
| `SCREENING_POLL_INTERVAL_MS` | `750` | Intended poll interval (ms) used by clients/UX; backend uses it for any internal timing where applicable. |
| `SCREENING_SYNC_TIMEOUT_S` | `60` | Timeout budget (seconds) for synchronous screening request flows. |
| `SCREENING_RESULT_LIMIT` | `5` | Default max number of matches returned per item. |
| `DAILY_SCREENING_TIMEZONE` | `America/New_York` | Timezone for schedule calculations. |
| `DAILY_SCREENING_HOUR` | `0` | Hour-of-day for default daily schedule run time (local to `DAILY_SCREENING_TIMEZONE`). |
| `DAILY_SCREENING_MINUTE` | `5` | Minute-of-hour for default daily schedule run time. |
| `DAILY_SCREENING_CHECK_INTERVAL_S` | `30` | How often the worker checks for due schedules. |
| `AUDIT_ACCESS_LOG_ENABLED` | `true` | Enables middleware access logging into `api_access_logs`. |
| `AUDIT_EVENT_RETENTION_DAYS` | `3650` | Retention window for `audit_events` cleanup. |
| `API_ACCESS_LOG_RETENTION_DAYS` | `365` | Retention window for `api_access_logs` cleanup. |
| `EXTERNAL_API_ERROR_RETENTION_DAYS` | `365` | Retention window for `external_api_errors` cleanup. |
| `OPERATIONAL_CLEANUP_INTERVAL_S` | `3600` | How often the worker purges old operational data. |
| `HIGH_RISK_EXTERNAL_API_ERROR_WINDOW_MINUTES` | `15` | Rolling window for high-risk external API failure detection. |
| `HIGH_RISK_EXTERNAL_API_ERROR_THRESHOLD` | `10` | Threshold count inside the window that triggers high-risk alert audit events. |
| `AUTH_ENABLED` | `false` | Enables JWT validation + permission enforcement for `/api/v1/*`. |
| `AUTH_ISSUER` | *(empty)* | JWT issuer URL. Required when `AUTH_ENABLED=true`. |
| `AUTH_JWKS_URL` | *(empty)* | JWKS URL for signature verification. Required when `AUTH_ENABLED=true`. |
| `AUTH_AUDIENCE` | *(empty)* | JWT audience/app-client id (required for Cognito access tokens). |
| `AUTH_ALGORITHMS` | `RS256` | Allowed JWT signing algorithms. |

## 11. Appendix: Batch File -> Actimize Request Mapping

This section documents how fields from the uploaded batch file (CSV/XLSX) map into:
1) the backend `queries_json` payload (`EntityExample` objects) and
2) the Actimize `POST /entity-screenings` JSON payload.

### 11.1 Batch File Format and Header Rules

- Supported uploads: `.csv`, `.xlsx`.
- Excel parsing uses the **first worksheet** only.
- Column header matching is **case-insensitive** and tolerant of separators:
  - headers are normalized by lowercasing and removing non-alphanumeric characters
  - example: `Party Key`, `party_key`, and `PartyKey` all map to the same field.
- Reference template: `public/Actimize_SSB1_template.xlsx`.

### 11.2 Column Mapping to `queries_json` (`EntityExample`)

Batch rows are parsed in the backend (`backend/app/batch_upload_parser.py`) and converted into normalized `EntityExample` payloads.
The backend treats the `PartyKey` as the canonical record identifier and ensures it is propagated into the downstream screening request.

| Batch File Column (template) | Parsed Field | `queries_json` (`EntityExample`) | Notes |
|---|---|---|---|
| `PartyKey` | `partyKey` | **Object key**: `queries["<PartyKey>"]` | Required and must be unique within the file; backend also injects this into `properties.partyKey` for traceability. |
| `PartyType` (`I`/`E`) | `partyType` | `schema` | `I` -> `schema="Person"`; `E` -> `schema="Company"`. If missing, UI infers from `CustomerType` and/or available name fields. |
| `CustomerType` (`Person`/`Entity`) | `customerType` | `schema` | Used as a fallback when `PartyType` is missing. |
| `PrimaryFirstName` | `firstName` | `properties.name[]` | Individual only: combined with middle/last to form a primary name string. |
| `PrimaryMiddleName` | `middleName` | `properties.name[]` | Included in the combined primary name string when present. |
| `PrimaryLastName` | `lastName` | `properties.name[]` | Individual only: required (with First Name) if `PrimaryFullName` is not provided. |
| `PrimaryFullName` | `fullName` | `properties.name[]` | Required for Organization/Unknown; for Individual it can be used instead of split names. |
| `Alias1FullName` | `aliasName` | `properties.alias[]` | Optional; sent as a single alias entry. |
| `DateOfBirth` | `dateOfBirth` | `properties.birthDate[]` | Individual only. Accepted as `YYYY-MM-DD`, `YYYY/MM/DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, or `YYYY` (year-only). |
| `Gender` | `gender` | `properties.gender[]` | Accepts `Male`, `Female`, `Other`, blank, and legacy `M/F/O`; backend normalizes to title case and later uppercases for Actimize. |
| `Addresses` | `addresses` | `properties.address[]` | Optional comma-separated list of full-address lines. If blank, UI derives a one-line address from `Address1*` fields. |
| `Address1Line1` | `addressLine1` | `properties.address[]` | Used only when `Addresses` is blank (part of derived one-line address). |
| `Address1Line2` | `addressLine2` | `properties.address[]` | Used only when `Addresses` is blank (part of derived one-line address). |
| `Address1City` | `city` | `properties.address[]` | Used only when `Addresses` is blank (part of derived one-line address). |
| `Address1StateProvince` | `state` | `properties.address[]` | Used only when `Addresses` is blank (part of derived one-line address). |
| `Address1ZipCode` | `zip` | `properties.address[]` | Used only when `Addresses` is blank (part of derived one-line address). |
| `Countries` | `countries` | `properties.nationality[]` or `properties.country[]` | Optional comma-separated list. Prefer ISO2 country codes (e.g., `US`, `IN`). |
| `Address1Country` | `country` | `properties.nationality[]` or `properties.country[]` | Used as a fallback country when `Countries` is blank. |
| `NationalityCountry1` | `countryOfCitizenship` | `properties.nationality[]` or `properties.country[]` | Added to the country set; UI uses nationality for persons and country for organizations. |
| `CountryOfBirth` | `countryOfBirth` | `properties.birthLocation[]` | Parsed and forwarded as birth location / country of birth. |
| `PartyId1Value` | `idNumber` | `properties.idNumber[]` (Person) or `properties.registrationNumber[]` (Company) | Optional. Only the ID value is forwarded. |
| `PartyId1Type` | `idType` | `properties.ids[].idType` | Parsed and forwarded when present; adapter still applies defaults if missing. |
| `PartyId1IDCountry` | `idCountry` | `properties.ids[].idCountry` | Parsed and forwarded when present; adapter still falls back to first mapped country if missing. |
| `Title` | `title` | `properties.title[]` | Forwarded when present. |
| `Notes` | *(none)* | *(not mapped)* | Ignored. |

### 11.3 Mapping from `queries_json` (`EntityExample`) to Actimize `POST /entity-screenings`

Actimize screening is performed by the backend adapter (`backend/app/actimize.py`) which posts to:

- `POST ${ACTIMIZE_BASE_URL}/entity-screenings`

The JSON payload is derived from `EntityExample` roughly as follows:

| `EntityExample` Field | Actimize JSON Field | Notes |
|---|---|---|
| `properties.partyKey` (or derived) | `partyKey` | Backend ensures `partyKey` is present for batch items; otherwise a deterministic hash-based key is generated. |
| `schema` | `partyType` | `Person`/`Individual` -> `I`; `Company`/`Organization`/`Unknown` -> `E`. |
| `properties.name[0]` | `names.fullName` | For `partyType="I"`, `firstName`/`lastName` are derived by splitting the full name if not explicitly provided. |
| `properties.alias[]` (+ additional names) | `aliases[]` | Up to 10 unique aliases; for persons, alias `firstName`/`lastName` are also derived by splitting. |
| `properties.nationality[]` / `properties.country[]` | `nationalities[]` | Converted to ISO3 (supports ISO2 or ISO3 input); up to 5 entries. |
| `properties.address[]` | `addresses[]` | Mapped as `street1` plus default `country` (first mapped nationality/country); up to 5 entries. |
| `properties.idNumber[]` / `properties.registrationNumber[]` | `ids[]` | Sent as `{idType, idValue, idCountry}` with defaults and first mapped country; up to 5 entries. |
| `properties.birthDate[]` | `dateOfBirth` or `yearOfBirth` | Dates normalize to `DD/MM/YYYY` when possible; year-only populates `yearOfBirth`. |
| `properties.birthLocation[]` | `countryofBirth` | Uses ISO3 country code when possible; otherwise passes through raw value. |
| `properties.gender[]` | `gender` | Uppercased before submission (`Female` -> `FEMALE`). |
| `properties.title[]` | `title` | Passed through when present. |

### 11.4 Current Result Classification Rules

- HTTP `200` + Prudential body `message="PM"` => **Potential Match**
- HTTP `200` + Prudential body `message="NM"` => **Clear**
- Any other HTTP status or payload message => **Failed**
