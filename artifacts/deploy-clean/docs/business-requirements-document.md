# Business Requirements Document (BRD)

## Application
OFAC / Watchlist Screening Application

## Document Version
- Version: 1.1
- Date: March 6, 2026
- Status: Updated for enterprise audit controls

## 1. Business Purpose
The application shall allow business users to screen individuals and entities against watchlists, receive immediate results for single requests, process large files in batch mode, and maintain a compliant audit trail of all user actions.

## 2. Business Objectives
1. Reduce sanctions and watchlist exposure risk through consistent screening.
2. Support both real-time and high-volume screening workflows.
3. Maintain traceable user accountability for compliance and investigations.
4. Enable recurring daily re-screening of selected batch populations.

## 3. Scope
### In Scope
- Single (real-time) screening workflow.
- Batch (asynchronous) screening workflow.
- Multi-type screening selection (Sanction, PEP, AME, Fincen 314(a), Global Sanction).
- Daily screening scheduling and selective disablement.
- User-scoped result visibility.
- Audit logging of user actions.
- API access logging with request/response metadata.
- Correlation ID traceability across API, queue, and worker processing.
- Operational retention and risk alerting controls for audit/error data.

### Out of Scope
- Case management and adjudication workflow after match.
- Alert disposition workflow in external systems.
- Customer onboarding/KYC data mastering.

## 4. Business Requirements by Component

## Component A: User Context and Access
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-UA-001 | The system shall require a selected business user context before submitting screening requests. | Must | Screening cannot be submitted without selecting a user context. |
| BR-UA-002 | The system shall attribute each screening action to the selected user. | Must | Each action is recorded with user identity and timestamp. |
| BR-UA-003 | The system shall display screening results only for the selected user context. | Must | Results view changes when selected user changes and shows only that user's records. |

## Component B: Single Screening (Synchronous)
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-SS-001 | Business users shall be able to submit a single screening request and receive an immediate response. | Must | Response is returned in the same interaction without waiting for batch completion. |
| BR-SS-002 | Users shall be able to select one or many screening types per single request. | Must | UI allows multi-select of the defined screening types before submission. |
| BR-SS-003 | The system shall support a mock screening mode for single requests (hit-check only, no alert generation). | Must | Users can enable/disable mock mode at submission time. |
| BR-SS-004 | When multiple screening types are selected, screening shall be executed for each selected type and returned as one business response. | Must | Final response reflects all selected types for the same request. |

## Component C: Batch Screening (Asynchronous)
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-BS-001 | Users shall upload batch files and submit batch screening with a business-defined batch name. | Must | Batch submission requires file and batch name. |
| BR-BS-002 | Users shall be able to select one or many screening types per batch submission. | Must | UI supports multi-select of screening types in batch flow. |
| BR-BS-003 | Batch screening shall run asynchronously and not block user interaction. | Must | User can continue working after batch submission. |
| BR-BS-004 | Until batch completion, the result status shall be shown as "In Progress" in the Screening Results tab. | Must | Newly submitted batch entries remain In Progress until final status is available. |
| BR-BS-005 | Users shall be able to refresh and view updated batch results. | Must | Manual refresh updates status/result rows. |

## Component D: Daily Screening Schedule
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-DS-001 | Users shall be able to mark eligible batch submissions for daily re-screening. | Must | Daily Screening option is available and persisted with the batch. |
| BR-DS-002 | Daily re-screening shall run during midnight hours in US Eastern Time. | Must | Scheduled runs occur shortly after 12:00 AM ET. |
| BR-DS-003 | Users shall be able to disable daily screening for a specific batch after submission. | Must | A user can stop one schedule without affecting others. |
| BR-DS-004 | Disabling a schedule shall be auditable. | Must | Audit record exists for each disable action. |

## Component E: Screening Results and Dashboard
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-SR-001 | Results shall present business-friendly statuses (Clear, Potential Match, Pending/In Progress, Match). | Must | Statuses are visible and filterable in results. |
| BR-SR-002 | Dashboard counters shall reflect current user-scoped screening totals by status. | Must | Counter values update based on selected user and latest data. |
| BR-SR-003 | Users shall be able to inspect hit-entity details from a result row. | Should | Hit details are accessible from results actions. |
| BR-SR-004 | Entity type representation shall be visually identifiable in forms and results. | Should | Entity icons/labels are consistent across selection and results. |

## Component F: Audit and Compliance
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-AU-001 | The system shall capture each user action relevant to screening and schedule management. | Must | Submit, refresh, schedule create/disable, and screening actions are auditable. |
| BR-AU-002 | Audit records shall include who, what action, when, and contextual details. | Must | Audit data contains user identity, timestamp, action type, and action context. |
| BR-AU-003 | Audit records shall be retrievable for review and compliance checks. | Must | Authorized users can list audit history by user and/or recent time period. |
| BR-AU-004 | The system shall log every backend API request with status code, latency, and correlation identifier. | Must | Each `/api/v1/*` request creates an access-log row including method, path, status, duration, and correlation id. |
| BR-AU-005 | Authentication and authorization failures shall be auditable. | Must | 401/403 API responses create explicit audit events with endpoint, status, and correlation id. |
| BR-AU-006 | Asynchronous processing lifecycle shall be auditable end-to-end. | Must | Queue enqueue, dequeue/pickup, and worker processing outcomes are stored in audit logs with correlation id. |
| BR-AU-007 | External screening API errors shall be stored in a dedicated error repository with context. | Must | Each external API failure stores provider, operation, status code, request context, and related correlation id. |
| BR-AU-008 | Sensitive request attributes in operational logs shall be masked or redacted. | Must | Access logs do not persist raw secrets/tokens/password-like values. |
| BR-AU-009 | The platform shall support configurable retention windows for audit/access/error logs. | Must | Worker applies retention policy and records purge actions in audit trail. |

## Component H: Operational Risk Controls
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-OR-001 | The platform shall trigger a high-risk audit alert when external API failures exceed threshold within a configurable window. | Must | Alert event is recorded once per provider/operation window when threshold is crossed. |
| BR-OR-002 | Correlation id shall be propagated from inbound API request through queue message to worker execution events. | Must | A single correlation id can be used to trace one screening request across API, SQS, worker, and failure logs. |

## Component G: Throughput and Service Levels
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-SL-001 | Screening execution shall support Actimize throughput constraints of 32 TPS. | Must | Processing behavior respects defined throughput limit. |
| BR-SL-002 | Single screening user experience shall prioritize low-latency response. | Must | Single requests return immediately in interactive user flow. |
| BR-SL-003 | Batch processing shall provide eventual completion with visible progress status. | Must | Batch requests transition from In Progress to final states without manual re-submission. |

## 5. Business Success Metrics
1. 100% of screening submissions are attributable to a user identity.
2. 100% of batch submissions display In Progress before finalization.
3. 100% of daily schedules can be disabled individually.
4. 100% of auditable actions are queryable for compliance review.
5. Single screening responses are returned in real-time user workflow.
6. 100% of backend API calls generate an access-log record.
7. 100% of screening external API failures are persisted with context and correlation id.

## 6. Assumptions
1. Actimize remains the system of record for screening decision inputs.
2. Business users are pre-provisioned and available for selection.
3. Business operations accept asynchronous completion for batch requests.
4. Compliance operations require immutable audit history for screening actions.
