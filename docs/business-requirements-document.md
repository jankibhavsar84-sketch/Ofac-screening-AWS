# Business Requirements Document (BRD)

## Application
OFAC / Watchlist Screening Application

## Document Version
- Version: 1.2
- Date: April 9, 2026
- Status: Updated for AWS batch dispatch, dashboard performance split, and operational validation

## 1. Business Purpose
The application shall allow business users to screen individuals and entities against watchlists, receive immediate results for single requests, process large files in batch mode, maintain a compliant audit trail of all user actions, and support recurring re-screening of selected populations with appropriate operational controls.

## 2. Business Objectives
1. Reduce sanctions and watchlist exposure risk through consistent screening.
2. Support both real-time and high-volume screening workflows.
3. Maintain traceable user accountability for compliance and investigations.
4. Enable recurring daily re-screening of selected batch populations.
5. Improve usability and responsiveness for high-volume result review.
6. Support business-unit-based submission controls and visibility.

## 2.1 Revision Summary
- Batch uploads are now validated and normalized by the backend from the uploaded CSV/XLSX source file; users no longer depend on browser-side parsing to create the submitted screening payload.
- The screening dashboard now separates summary counts from recent result rows so dashboard cards remain responsive even when user history grows large.
- Large immediate uploads use asynchronous dispatch so the platform can acknowledge accepted work before all individual screening items are expanded and processed.
- Admin/compliance audit review now supports paged retrieval of audit activity.
- Scheduled screening supports subscription-based completion notifications.
- Current operational validation results from April 8, 2026 are captured in this BRD for business readiness visibility.

## 3. Scope
### In Scope
- Single (real-time) screening workflow.
- Batch (asynchronous) screening workflow.
- Backend validation of uploaded CSV/XLSX screening files.
- Multi-type screening selection (Sanction, PEP, AME, Fincen 314(a), Global Sanction).
- Daily screening scheduling and selective disablement.
- Daily screening completion notifications for subscribed recipients.
- User-scoped result visibility.
- Business-unit-based submission authorization and administration.
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
| BR-UA-004 | The system shall require a valid business unit for screening submissions. | Must | Screening submission cannot proceed without a business unit mapped to the submitting user context. |
| BR-UA-005 | The system shall enforce role-based access for screening, schedule, audit, and user-administration functions. | Must | Users only see or execute actions permitted by their assigned role/permissions. |
| BR-UA-006 | Authorized administrators shall be able to maintain user-to-business-unit mappings. | Should | Authorized admin users can add, change, and review business-unit assignments. |

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
| BR-BS-006 | The system shall validate uploaded batch files on the server side before creating screening work. | Must | Invalid file structure or row data is rejected with a user-readable validation message before job submission. |
| BR-BS-007 | The system shall support CSV and XLSX upload formats for batch screening. | Must | Users can submit `.csv` or `.xlsx` files and unsupported formats are rejected. |
| BR-BS-008 | For large immediate uploads, the platform shall acknowledge accepted work as queued without waiting for all row-level screening items to finish. | Must | Successful submission returns a queued batch/job response while actual item screening continues asynchronously. |
| BR-BS-009 | The platform shall return row-level identity metadata for accepted batch uploads so users can review in-progress and final results by uploaded record. | Should | Accepted batch response supports rendering uploaded records by display name and entity type. |

## Component D: Daily Screening Schedule
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-DS-001 | Users shall be able to mark eligible batch submissions for daily re-screening. | Must | Daily Screening option is available and persisted with the batch. |
| BR-DS-002 | Daily re-screening shall run during midnight hours in US Eastern Time. | Must | Scheduled runs occur shortly after 12:00 AM ET. |
| BR-DS-003 | Users shall be able to disable daily screening for a specific batch after submission. | Must | A user can stop one schedule without affecting others. |
| BR-DS-004 | Disabling a schedule shall be auditable. | Must | Audit record exists for each disable action. |
| BR-DS-005 | Users shall be able to subscribe one or more email recipients for scheduled screening completion notifications. | Should | Schedule subscriptions can be created, viewed, and removed for a scheduled batch. |
| BR-DS-006 | Scheduled completion notifications shall include enough context for the recipient to identify the schedule and resulting job. | Should | Notification contains schedule/job reference information and summary context. |

## Component E: Screening Results and Dashboard
| ID | Business Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| BR-SR-001 | Results shall present business-friendly statuses (Clear, Potential Match, Pending/In Progress, Match). | Must | Statuses are visible and filterable in results. |
| BR-SR-002 | Dashboard counters shall reflect current user-scoped screening totals by status. | Must | Counter values update based on selected user and latest data. |
| BR-SR-003 | Users shall be able to inspect hit-entity details from a result row. | Should | Hit details are accessible from results actions. |
| BR-SR-004 | Entity type representation shall be visually identifiable in forms and results. | Should | Entity icons/labels are consistent across selection and results. |
| BR-SR-005 | Dashboard summary totals shall represent the signed-in user's full screening history even when the visible result grid is limited for usability. | Must | Summary cards show full-history totals while the results table loads a recent-result window. |
| BR-SR-006 | The screening result grid may limit the number of rows initially loaded in order to preserve responsiveness. | Must | Recent rows are displayed promptly without requiring the entire history set to load first. |
| BR-SR-007 | When a hit or reviewable result exists, the platform should provide a configurable navigation path to the downstream review experience. | Should | Result details can surface a review link when configured for the environment. |

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
| BR-AU-010 | Authorized audit users shall be able to review audit activity using paged retrieval suitable for large audit volumes. | Must | Audit review supports page-based retrieval without requiring full-history download. |

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
| BR-SL-004 | Large batch upload design shall prioritize returning a queued acknowledgement within the front-door request window. | Must | Accepted large uploads return queued confirmation without waiting for row-level screening completion. |
| BR-SL-005 | The platform shall preserve dashboard and results usability as submission history grows. | Must | Users can access summary metrics and recent results without performance degradation caused by loading all history at once. |

## 5. Business Success Metrics
1. 100% of screening submissions are attributable to a user identity.
2. 100% of batch submissions display In Progress before finalization.
3. 100% of daily schedules can be disabled individually.
4. 100% of auditable actions are queryable for compliance review.
5. Single screening responses are returned in real-time user workflow.
6. 100% of backend API calls generate an access-log record.
7. 100% of screening external API failures are persisted with context and correlation id.
8. 100% of accepted batch uploads are server-validated before asynchronous processing begins.
9. Dashboard summary cards remain usable for high-history users without loading the full result history into the initial grid.

## 6. Current Validation Snapshot
### April 8, 2026 Batch Upload Validation
- Concurrent users: `20`
- Successful submissions: `11`
- Failed submissions: `9`
- Overall success rate: `55.0%`
- Successful submission latency: `17.6s` minimum, `42.6s` p50, `49.2s` p95, `52.1s` maximum
- Primary failure mode: CloudFront `504 Gateway Timeout` during submission (`7` users)
- Secondary failure mode: test/setup issue with missing business unit option (`2` users)

Business interpretation:
- The large-batch asynchronous dispatch design shows measurable improvement because more than half of concurrent users received a queued response for the `1000`-row upload test without waiting for full screening completion.
- The current business readiness risk is that front-door timeout behavior still exists under parallel high-volume submission, so additional optimization may be required before treating this scenario as fully production-ready at the tested concurrency.

## 7. Assumptions
1. Actimize remains the system of record for screening decision inputs.
2. Business users are pre-provisioned and available for selection.
3. Business operations accept asynchronous completion for batch requests.
4. Compliance operations require immutable audit history for screening actions.
5. Business-unit mappings are maintained accurately enough to support submission authorization.
