# Team product failure matrix

**Draft for review. Owner: Jad. Prepared 2026-11-27 against `2b31471`.**
Each row defines a failure, an observable response and the evidence needed on the frozen final
app. All rows are **planned for final verification**. Existing tests identify useful starting
points; their presence does not establish that the full failure was tested on the release.
Security priorities follow [the threat model](threat-model.md).

## Recording a result

For each case retain: id, frozen commit, date, environment, synthetic fixture, injected fault,
expected result, actual result, stored state, latency where relevant, evidence location and issue.
Use `not run`, `pass`, `fail`, `blocked` or `not applicable` with a reason. A crash or timeout is
not an access denial; an expected failure marker is not a pass. Preserve failures in the totals.

Priority P0 covers privacy, credentials and unauthorized state changes. P1 covers other failures
that need repair or a documented restriction before release. The detection column describes
what to inspect, not a promise that a production alert already exists.

## Failure inventory

| ID | Component and injected failure | Detection | Required behavior | Proof to collect | Starting point | Priority |
|---|---|---|---|---|---|---|
| FM-01 | API authentication: missing, expired or revoked session | Protected response and database reads | Reject access; return no protected data or mutation | Status, redacted response and unchanged records | `backend/tests/test_auth.py` | P0 |
| FM-02 | Object access: substitute another team's report or evidence id | Response and record lookup | Disclose neither the record nor its existence through a success payload | Own-team control and cross-team refusal | `backend/tests/test_supervisor_view.py` | P0 |
| FM-03 | MCP authentication: invalid, expired or revoked connection | MCP error and permitted audit entry | Refuse reads and submissions with a meaningful denial; no stack trace or token echo | Client-visible denial, no write and sanitized log | `backend/tests/test_mcp.py`, `test_mcp_oauth.py` | P0 |
| FM-04 | MCP role removal while an old session remains open | Reuse existing connection after demotion | Recheck current permission; no team, member or check-in disclosure | Before/after role requests | `backend/tests/test_mcp.py` | P0 |
| FM-05 | Team input: note or event contains personal content or instructions | Submission, approval and model-input boundary | Refuse unsafe content; benign context still works; no unauthorized instructions execute | App and MCP variants; track open #246 | `backend/tests/test_note_screen.py` | P0 |
| FM-06 | Approval: repeat or race a stale submission decision | Affected rows, notifications and audit events | Apply at most once; reject an unauthorized or stale decision | Two PostgreSQL sessions, one final application | `backend/tests/test_mcp_postgres.py` | P0 |
| FM-07 | Health sync: expired sign-in or revoked scope | Sync status and connection state | Show reconnect need; preserve stored history; do not evaluate a check-in from a failed sync | Failed run, unchanged data and no new alert | `backend/tests/test_google_connect.py`, `test_calendar.py` | P1 |
| FM-08 | Health provider: timeout, 429, 5xx or malformed page | Fake transport attempts and sync status | Bound attempts; report failure; avoid publishing partial data as a successful sync | Attempts, elapsed time, persisted data and retry behavior | `backend/tests/test_health_client.py`, `test_pull.py` | P1 |
| FM-09 | Calendar provider fails while Health works, or conversely | Both connection and sync records | Keep the providers independent; show stale or unavailable Calendar honestly | Each provider's status and unaffected data | `backend/tests/test_calendar.py` | P1 |
| FM-10 | Calendar coverage: unsynced day is mistaken for zero meetings | Stored rows, coverage and returned state | Missing stays missing; a synced empty day can be zero | Same fixture with a missing day and an empty day | `backend/tests/test_calendar.py`, `test_supervisor_view.py` | P1 |
| FM-11 | Database connection fails or a write transaction rolls back | API error, job outcome and committed records | Controlled failure; no partial approval, success claim or secret-bearing SQL in logs | Fault before/after flush; committed state from a fresh session | `backend/tests/test_api.py`, `test_db.py` | P0 |
| FM-12 | Database contention: overlapping HR invitations or approvals | Concurrent transaction outcomes | One valid current invitation or one applied decision; preserve current role rules | PostgreSQL race with both responses and final rows | `backend/tests/test_hr_invite_postgres.py`, `test_mcp_postgres.py` | P0 |
| FM-13 | Check-in due pass stops and restarts after the one-hour deadline | Stored due time and delivery events | Never send early; resume due work without duplicate logical delivery or a reset deadline | Frozen clock before, at and after deadline, then restart | `backend/tests/test_checkin.py` | P0 |
| FM-14 | Consent withdrawn or member leaves before send | Consent, membership and alert state | Withdraw waiting alert; Send now and the due pass cannot bypass withdrawal | Both send paths and unchanged recipients | `backend/tests/test_checkin.py` | P0 |
| FM-15 | Recipient replaced or demoted before delivery or later access | Role assignment, delivery and old URL response | Exclude former holder; revoke list/open/mark access and reminders immediately | Role change at both stages and old-link requests | `backend/tests/test_checkin.py`, `test_hr_invite.py` | P0 |
| FM-16 | Email provider refuses, times out or accepts before a local error | Outbound stub, in-app state and delivery log | Preserve permitted in-app access; no false email success; document uncertain delivery and any possible duplicate retry | Attempt log and stored delivery state; distinguish logical notice from external mail | `backend/tests/test_team_email.py`, `test_checkin.py` | P1 |
| FM-17 | One team's scheduled processing raises an exception | Per-team outcomes and other teams' records | Isolate the failed team; continue eligible work for others; expose the failure to operators | Failing and healthy synthetic teams in one pass | `backend/tests/test_checkin.py`, `test_team_briefing.py` | P1 |
| FM-18 | A report or metric falls below five eligible contributors | Coverage and bounded response fields | Withhold its figures and evidence; never render missing as steady | Four/five boundary, sparse metric and Calendar cohort | `backend/tests/test_team_reports.py`, `test_supervisor_view.py` | P0 |
| FM-19 | Historical request accidentally returns current readings or outcome | Requested week versus response and evidence dates | Preserve requested week, baseline and as-of state; never silently substitute latest | Old-week request beside a different current-week control | `backend/tests/test_supervisor_view.py` | P1 |
| FM-20 | Model-dependent path fails or exceeds its budget | Call accounting and report state | Preserve computed report; no invented findings or automatic approval; respect caps | Fake model error and exhaustion; affected feature recorded | `backend/tests/test_team_briefing.py`, `test_llm.py` | P1 |
| FM-21 | Telemetry includes an exception carrying synthetic private values | In-memory telemetry transport and metric labels | Strip values, identity, credentials and query bodies; retain useful error category | Canary absent from outbound payload, present in injected fixture | `backend/tests/test_observability.py`, `test_prometheus.py` | P0 |
| FM-22 | Frontend receives an unavailable backend or incompatible response | Visible error state and browser console | Explain failure, preserve input where applicable, avoid exposing stale data as current | Screen evidence and captured response contract | `mobile/src/api/http.ts`, `mobile/src/api/types.ts` | P1 |
| FM-23 | Disabled personal feature is reached by URL or direct request | Feature response, route and background jobs | Respect server flag; no hidden route bypass or personal background execution | Flag off/on controls in isolated config | `backend/tests/test_personal_features.py` | P1 |
| FM-24 | Excess requests or very large input exhaust a worker | Limits, latency, queue and denial response | Reject over-limit input predictably; preserve other users' access and state | Bounded local load and normal-client control | `backend/tests/test_limits.py`, `test_mcp.py` | P1 |

## Existing gaps and decisions

- FM-05 includes the open note-screen bug #246. The six known expected failures remain a gap
  until the fix and its negative and benign controls pass on the frozen release.
- FM-13 requires recovery and duplicate checks beyond a single happy-path timer test. Agree the
  acceptable delay after worker recovery before the run; the design's minute cadence is not a
  measured recovery guarantee.
- FM-16 does not assume exactly-once delivery by an external email provider. Record an
  acknowledged provider receipt, a definite rejection and an unknown timeout separately.
- [The evaluation audit](evaluation-audit.md) and [rehearsal](rehearsal-2026-11-26.md) record gaps
  in weekly report and approval monitoring. Verify signal availability before calling a row
  operationally detectable; otherwise open an observability issue.
- Health and Calendar reconnect checks use fakes first. Real sign-in, external mail and
  production faults wait for a separately agreed final test run.

## Completion rule

Every row needs a recorded result or a justified exclusion tied to the final product scope.
For a failure, link the issue, impact, affected feature and retest. Do not treat earlier suite
totals as coverage of newly planned faults. Jad supplies the matrix and evidence; Karim reviews
feature restrictions and remaining release risks before merge or release approval.
