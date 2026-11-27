# Team product reliability test plan

**Draft execution plan. Owner: Jad. Prepared 2026-11-27 against `2b31471`. All cases: not run.**
Implement and run these checks after the final candidate is frozen. The scope is failure
handling, concurrent use and the API contract, as assigned in [the plan](plan.md).
Use [the Failure Matrix](failure-matrix.md) for expected behavior and
[security scenarios](security-scenarios.md) for access and mutation boundaries.

## Preparation and run record

Use a disposable local or staging PostgreSQL database, fake Health/Calendar/model transports and
an email sink. SQLite can cover ordinary schema and pure logic checks; it cannot establish
PostgreSQL row-lock or concurrent approval behavior. Never aim fault injection or load at the
production service. Keep Google writes off and provider credentials absent from the test runner.

Freeze the commit, migration head, configuration, timezone, OS, runtime versions, database
version, machine resources, fixture seed, script revision and network mode. Record effective
limits and timeouts by name and value, without credentials. Decide final performance thresholds
with Karim before measuring; the numbers below are a proposed test profile, not existing SLAs.

Every result includes actual output, state after the request, elapsed time where relevant and
sanitized evidence. A skipped or blocked case is listed separately. Final app execution remains
deferred; this preparation does not change CI, dependencies or application behavior.

## Fault injection cases

Inject at the network or storage boundary with a fake transport, clock or controlled database
failure. Record attempts and elapsed time so that bounded failure can be distinguished from
silent retry. Run a healthy control before and after each fault.

| ID | Fault and scope | Expected check | Matrix |
|---|---|---|---|
| CHAOS-01 | Health read times out, returns 429/5xx or malformed later page | Bounded attempts; failed status; no partial history presented as successful; no check-in from failed sync | FM-07, FM-08 |
| CHAOS-02 | Calendar read fails or loses its sign-in while Health succeeds | Health remains usable; Calendar unavailable/stale state is explicit; no fabricated zero meetings | FM-09, FM-10 |
| CHAOS-03 | Health connection expires while Calendar works | Calendar retains its own sign-in and continues within its permissions | FM-07, FM-09 |
| CHAOS-04 | Database fails before a mutation or rolls back after flush | No partial approval or false success; controlled response; sanitized storage error | FM-11 |
| CHAOS-05 | Worker stops before due delivery and resumes after deadline | Original deadline survives; no early send or duplicate logical delivery; recovery delay measured | FM-13 |
| CHAOS-06 | Member withdraws consent or recipient role changes just before send | Current membership, consent and role determine delivery and later access | FM-14, FM-15 |
| CHAOS-07 | Mail is rejected, times out, or is accepted before a local failure | In-app state remains truthful; definite and unknown mail outcomes distinguished | FM-16 |
| CHAOS-08 | One team's daily or weekly work raises | Other teams continue; failed team is identifiable to operators without private payloads | FM-17 |
| CHAOS-09 | A model-dependent briefing path fails or exhausts its budget | Computed evidence remains; no invented result or approved action; cost cap respected | FM-20 |
| CHAOS-10 | Telemetry fails or receives an exception containing a synthetic secret | Business outcome does not depend on telemetry availability; exported data is scrubbed | FM-21 |

For CHAOS-05 and CHAOS-06 use a controllable UTC clock and render the corresponding local time.
Cover just before, exactly at and after the hour, worker restart, repeated sync and repeat send.
Exercise recipient replacement both before delivery and after an alert was opened. No live
waiting or real email is needed for these cases.

Reuse relevant fixtures in `backend/tests/test_checkin.py`, `backend/tests/test_calendar.py`,
`backend/tests/test_health_client.py`, `backend/tests/test_mcp_postgres.py` and
`backend/tests/test_observability.py`; inspect the final implementation before adding new tests.

## Proposed load profile

Choose k6 or Locust when implementing the runner; do not add both. Seed a synthetic team with
eight eligible people and a separate withheld team. Use distinct sessions for different actors.
Prepare tokens outside command-line arguments and never include authorization headers in output.

| ID | Stage | Proposed duration and concurrency | Operations and required observations |
|---|---|---|---|
| LOAD-01 | Baseline | 2 minutes, 1 user | Authorized report, bounded evidence and Calendar reads; establish p50/p95/p99 and throughput |
| LOAD-02 | Ordinary team use | 5 minutes, 5 then 10 users | Same read mix across two teams and MCP; measure errors and isolation throughout |
| LOAD-03 | Mixed work | 5 minutes, 10 users | Reads plus independent synthetic submissions and permitted decisions; run due check-ins with email sink and inspect queue delay |
| LOAD-04 | Contention and limits | Bounded bursts, at most 10 users | Same-submission approvals, simultaneous invitations, repeat sync and configured limits; inspect one valid final state |
| LOAD-05 | Recovery | 2 minutes, 1 user after the burst | Service returns near baseline; no accumulated duplicate delivery or permanently busy account |

A proposed LOAD-02 acceptance target is p95 below 2 seconds for ordinary report/evidence/Calendar
reads and under 1% unexpected errors at the agreed load. Freeze or revise those targets before
the run based on the staging resources. They do not apply to provider syncs or model turns.
For the due pass, propose delivery within two minute ticks after it becomes due during normal
operation; measure recovery from a stopped worker separately. These are proposed gates.

At every stage require zero cross-team leaks and unauthorized writes, no duplicated logical
approval/delivery, and no forbidden data in output. Report an intentional 401/403/404/422/429
separately from a timeout or 5xx; an unrelated error cannot satisfy a denial case. Count requests
actually sent, dropped iterations and achieved throughput so a stalled runner cannot appear fast.

Stop the run on any privacy or integrity failure, growing uncontrolled queue, or sustained 5xx.
Do not increase beyond the agreed ceiling to find a breaking point. Record the stopping cause
and preserve the failed profile. Summarize CPU/memory, database connections, p50/p95/p99, request
rate, expected denials, unexpected errors, due-work delay and post-run consistency.

## Contract verification cases

Verify real backend responses against `mobile/src/api/types.ts`, the mock and HTTP client;
TypeScript compilation alone does not validate runtime JSON. Use the final OpenAPI schema and
synthetic requests. Compare names, casing, enum states, optional/null/missing distinctions,
units, ISO dates, timezone boundaries and error envelopes. Specify accepted status codes before
running rather than accepting any error.

| ID | Surface | Required comparison |
|---|---|---|
| CONTRACT-01 | Account and feature configuration | Role and feature fields match types; flag off/on and pending/approved states agree with UI |
| CONTRACT-02 | Team overview and weekly reports | Ready, no finding, withheld and no report stay distinct; per-metric coverage and dates match |
| CONTRACT-03 | Report evidence | Report-owned bounded record, unit and comparison windows; no individual values or stray evidence |
| CONTRACT-04 | Calendar status and daily counts | Connected, disconnected, failed, synced empty and never synced remain distinguishable |
| CONTRACT-05 | Team meeting load | Observed, below minimum, unavailable and week-not-over states; exact week and cohort |
| CONTRACT-06 | Member check-in | Consent version, waiting due time, send/stop and own evidence; no authority to act for another member |
| CONTRACT-07 | Recipient check-in | Current supervisor/HR view contains permitted identity and state, no metric or reason; role loss revokes access |
| CONTRACT-08 | HR invitation | Pending versus accepted contact, invalid/used link behavior and final role; response fields agree with UI |
| CONTRACT-09 | Harness connection and submission | Pending versus approved, rejected, stale and revoked states; app response agrees with mock |
| CONTRACT-10 | Shared errors | Error shape and intended status across validation, denied access, unavailable service and limits |

MCP has its own tool contract: also compare `team_overview`, `team_finding_evidence` and
`team_meeting_load` with the shared app view for the same synthetic week. Include a historical
week and withheld team. A renamed tool or endpoint must update the case before the run, with
the change recorded; do not hide a broken contract by silently switching to mock data.

## Delivery and retest

Keep implementation commits separate for contract tests, fault injection and the load runner.
Each should work with its own fixtures and no paid traffic. Add the relevant free checks to CI
only after review; keep the resource-heavy load run deliberate. Record results in a dated run
report with links to the case ids and final revision. For failures, retain the original outcome,
fix in a focused PR, then record the retest without overwriting the failure.
