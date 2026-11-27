# Team product threat model

**Draft for review. Owner: Jad. Prepared 2026-11-27 against `2b31471`.**
This model covers team reports, Calendar, MCP and check-in alerts. It defines the security
properties to verify when the final app is frozen; it does not certify the release. Product
decisions come from [the team scope](pivot.md), [the supervisor workflow](supervisor-workflow.md)
and [check-in design](escalation.md). Reconcile changes in those decisions before execution.

## Assets and consequences

| Asset | What must be protected | Consequence of a failure |
|---|---|---|
| Personal health history | Values, dates, source and ownership | A person is identified or their history is changed |
| Calendar information | Daily counts and provider credentials; avoid storing event titles | Work patterns or private events become visible |
| Identity and credentials | Password hashes, sessions, OAuth codes, refresh tokens, MCP tokens, API keys | Account takeover, unauthorized access or spend |
| Team reports and evidence | Correct cohorts, dates, units, provenance and minimum contributor counts | Disclosure or a misleading supervisor decision |
| Check-in state | Consent, member identity, recipients, due time and audit events | An unwanted or premature disclosure to an employer |
| Decisions and submissions | Pending data, approval, version and actor | An assistant or another user performs an unapproved change |
| Operational records | Logs, traces, metrics, error reports and backups | A secondary route to health data, identities or credentials |

## Actors and permitted access

| Actor | Intended access | Boundary to verify |
|---|---|---|
| Signed-out or pending account | Public entry and permitted account flows | No protected team or personal data |
| Approved member | Own data and calendar, own consent and permitted submissions | No other member's records or supervisor report |
| Supervisor | Own teams' aggregates and bounded evidence; current-role check-ins | No arbitrary individual health values or another team's data |
| Current HR contact | Check-in screens for assigned teams | No team reports, member readings or MCP access |
| Former recipient or departed member | Only access still independently authorized | Old URLs and tokens do not preserve a removed permission |
| MCP assistant | The connected account's permitted tools | A token cannot add a role or approve a decision |
| Project operator | Deployment and approved maintenance | Administration is not permission to export personal data |
| External provider or attacker | Untrusted responses or requests | Neither supplies authoritative access rules or instructions |

Named weekly levels have a separate opt-in in the existing product. Review that flow separately
if it remains in the final UI; it does not authorize individual disclosure through aggregate
reports, MCP or check-in messages.

## Data flow and trust boundaries

```text
Browser or phone -- session --> FastAPI -- scoped queries --> PostgreSQL
Assistant -- OAuth or MCP token --> MCP tools -- role checks --> shared team views
Google Health -- own sign-in --> sync -- source-labelled daily values --> PostgreSQL
Google Calendar -- separate sign-in --> sync -- daily counts --> PostgreSQL
Assistant submission --> pending record --> app approval --> accepted data or team note
Successful health sync --> consent and deterministic rule --> member waiting alert
Waiting alert --> send now or due pass --> current recipients --> protected check-in screen
API and workers --> scrubbed errors and aggregate metrics --> monitoring services
```

Each arrow crosses a boundary: authentication, user/team scope, provider input, human approval,
consent and time, or operational export. Report generation and MCP rendering must use the same
cohort and evidence rules. Check-in evidence stays with the member; recipient notices are
generic and the protected recipient screen gives the permitted identity without health values.
Check-in alerts never enter a model or MCP tool.

## Threat register

STRIDE groups threats as spoofing, tampering, repudiation, information disclosure, denial of
service and elevation of privilege. The controls below are requirements to verify, not new
implementation claims. Priority P0 means stop release for a privacy, credential or unauthorized
write failure; P1 means resolve or explicitly restrict the affected feature before release.

| ID | Category | Threat and entry point | Required control and proof | Priority |
|---|---|---|---|---|
| TM-01 | Spoofing | Stolen, expired or revoked session or MCP token is replayed | Reject protected reads and writes after expiry or revocation; examine response and state | P0 |
| TM-02 | Elevation | Caller substitutes a team, report, submission or evidence id | Check current role and ownership on every operation; guessed ids reveal no record | P0 |
| TM-03 | Disclosure | Four contributors, a sparse metric or cohort manipulation reveals a person | Apply the minimum of five per reportable figure; withhold figures and evidence below it | P0 |
| TM-04 | Disclosure | Recipient identity or signal escapes through email, inbox, MCP or a model | Generic notices; current-role screen only; no metric or reason to recipients; no check-in MCP route | P0 |
| TM-05 | Tampering | Assistant approves its own submission or repeats an approval | Pending state, app-only authorized approval, version checks and one application under concurrency | P0 |
| TM-06 | Tampering | Note or harness event carries instructions or personal health information | Screen at submission and approval; untrusted text never changes access or tool authority | P0 |
| TM-07 | Spoofing | OAuth callback, redirect, code or invitation is replayed or swapped | Bind request, client, redirect and verifier; expire and consume once; bind HR invitation to address and team | P0 |
| TM-08 | Disclosure | Role removal or consent withdrawal races with delivery | Recheck consent, membership and current recipients at delivery and access; verify waiting state is withdrawn | P0 |
| TM-09 | Tampering | Stale, fabricated or wrong-source data becomes a current observation | Separate source histories, validate schemas, preserve dates and provenance; pending imports affect no figures | P1 |
| TM-10 | Repudiation | A decision, role change or alert cannot be attributed | Retain the permitted actor, time and transition without copying health payloads into logs | P1 |
| TM-11 | Denial of service | Oversized input, slow providers, repeated syncs or MCP calls exhaust resources | Enforce bounds and limits; contain timeouts; prevent overlapping duplicate work | P1 |
| TM-12 | Disclosure | Exception details, metric labels, traces or reports leak private values | Scrub external telemetry; keep route patterns and aggregates; restrict stored trace and metrics access | P0 |
| TM-13 | Elevation | Personal routes reappear despite the team feature flag | Server and UI enforce the flag; direct requests cannot bypass it | P1 |
| TM-14 | Tampering | Historical report or outcome uses today's data or claims a cause | Preserve week, baseline and as-of meaning; cite bounded evidence and outcome limits | P1 |

## Known gaps and residual risks

- **Issue #246 is open at the preparation revision.** The note filter misses named health and
  absence remarks and some group health remarks through both app notes and MCP events. The six
  expected failures in `backend/tests/test_note_screen.py` are regression evidence of the gap,
  not passes. Use synthetic non-personal demo notes until repaired and reverified.
- A minimum of five reduces direct disclosure but does not prove anonymity against a supervisor
  with outside knowledge or repeated overlapping reports. Include differencing attacks in the
  final review; do not claim this is a differential privacy guarantee.
- A check-in identity itself conveys that an opted-in rule fired. Generic notifications cannot
  remove that disclosure to the authorized recipients. Consent and the one-hour stop window are
  substantive safeguards, not a statement that the signal is medically validated.
- Calendar counts can still reveal work patterns. Avoid exporting per-person rows when reporting
  test results. A missing sync must remain distinguishable from a day with no meetings.
- Disconnecting Calendar currently removes its connection and leaves synced days, as described
  in `backend/app/api/calendar.py`. Do not describe disconnect as data deletion. Retention,
  backups and end-of-pilot deletion need an operator decision and verification.
- A compromised authorized device, account or approved assistant can copy permitted information
  outside Patterns. Token revocation limits future access; it cannot retract a prior copy.

## Evidence and review

Existing starting points are `backend/tests/test_privacy_isolation.py`, `test_mcp.py`,
`test_mcp_oauth.py`, `test_mcp_postgres.py`, `test_hr_invite_postgres.py`, `test_checkin.py`,
`test_calendar.py`, `test_note_screen.py` and `test_observability.py` in that same directory.
They are pointers for the final review, not execution results for this draft.

Before sign-off, record the frozen commit, environment, configuration, case ids, actual outcome,
state after the request, sanitized evidence and unresolved risks. Jad owns the review; Karim
reviews product assumptions and any proposed change to access, consent or architecture.
