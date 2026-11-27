# Final app QA checklist

**Prepared by Jad on 2026-11-27 against `2b31471`. Execution deferred. All cases: not run.**
Use this checklist after Karim identifies the final candidate. It covers setup, app behavior and
the review record for the team product. Pair it with [security scenarios](security-scenarios.md)
and [reliability checks](reliability-test-plan.md). Nothing checked here is a recorded pass yet.

## Before the final run

- [ ] Record candidate commit/tag, backend release and frontend release; verify they are the
  intended pair. Record API base URL and whether each checked flow uses real or mock data.
- [ ] Record OS, browser, phone/Expo environment, runtime versions, database migration head,
  feature flags and timezone. Record configuration names without copying secret values.
- [ ] Prepare disposable synthetic accounts for pending, member, supervisor and HR roles, plus
  a former HR contact. Create separate ready, withheld and no-data teams.
- [ ] Use synthetic Health and Calendar days, a historical week and a week still in progress.
  Include a pending harness submission, an active team change and a waiting check-in.
- [ ] Keep email in a test sink, Google writes disabled and model/provider calls fake. Agree a
  separate scope and budget before any real-provider rehearsal.
- [ ] Freeze expected outcomes before executing. Keep failures visible; log bugs with synthetic
  reproduction steps, severity, candidate revision and expected versus actual behavior.

## Fresh clone and setup

Follow the final [README](../README.md) in a new disposable checkout. Use its commands exactly
before trying a workaround. A workaround should become an issue or README correction, not an
unrecorded step in a claimed successful quickstart.

| ID | Check | Completion evidence |
|---|---|---|
| QA-01 | Clone and install from documented prerequisites | Runtime versions, dependency result and any undocumented prerequisite |
| QA-02 | Start the documented local stack and apply migrations | Health response and expected schema head; distinguish an API health response from a working database |
| QA-03 | Start frontend with the intended API | Captured configuration mode and one request served by the backend; mock-only operation labelled separately |
| QA-04 | Sign up, approve through the documented operator flow and sign in | Pending cannot enter protected views; approved account enters its permitted role |
| QA-05 | Use default team configuration and direct links | Personal features off in server and UI; direct URLs cannot bypass it |
| QA-06 | Stop and restart the disposable stack | Documented restart works; expected synthetic state persists without duplicated work |

Do not copy a coworker's `.env`, provider token or health export into a fresh clone. Use the
documented example configuration and test credentials created for this run. Record teardown and
remove only fixtures the run created; do not delete an existing database or a teammate's files.

## Manual app scenarios

| ID | Flow | Expected behavior |
|---|---|---|
| QA-07 | Signed out, sign-up, pending approval, invalid password and sign-out | Clear state/error; protected views do not open; logout removes usable local access |
| QA-08 | Member home, team join/leave and consent | Only permitted views; explicit consent options; leaving updates access and waiting check-ins |
| QA-09 | Supervisor ready team | Dated finding, baseline, contributor count and weekly comparison are distinct and understandable |
| QA-10 | Open finding and weekly-line evidence, then go back | Correct owned record and dates; no individual rows; navigation restores the right team/week |
| QA-11 | Withheld, empty, sparse and no-report teams | Explain missing coverage; no fake zeros, steady verdict or disallowed statistics |
| QA-12 | Calendar connect/disconnect and unavailable load using fakes | Separate from Health; missing is not zero; disconnect does not claim stored data was deleted |
| QA-13 | Plan a synthetic team change, approve/decline as applicable, then refresh | Only supervisor can decide; dates and state persist; no duplicate change or notice |
| QA-14 | Historical report and change follow-up | Requested week's as-of state, evidence and outcome caveats remain; no current-week substitution |
| QA-15 | HR invite, pending replacement, accept and invalid/expired link | Current HR stays until valid replacement; wrong account cannot claim role; old HR loses access |
| QA-16 | Member waiting check-in with controllable clock | Exact due time; Send now and Stop work; turning consent off withdraws the waiting alert |
| QA-17 | Supervisor and HR recipient views | Generic inbox/email notice; permitted identity only after role check; no health metric or reason |
| QA-18 | MCP connect/allow/deny, submission approval and revocation | Correct account scope; pending content has no effect; revoked connection fails next request |
| QA-19 | Backend offline, slow response, validation error and retry | Visible actionable error; no silent mock fallback or stale success; repeat action is safe |
| QA-20 | Refresh, deep link, back navigation and role change | Correct route and role; protected cached content is cleared or inaccessible after logout/role loss |

Use fake OAuth responses for local preparation and controlled integration checks. A real MCP
assistant or Google sign-in is a separately labelled final rehearsal with its client version,
candidate and provider configuration recorded. A scripted client does not prove the real
assistant flow, and a mocked UI does not prove backend authorization.

## Display and interaction coverage

For QA-07 through QA-20 record applicable combinations, not just one desktop screenshot:

- [ ] Web at wide and narrow widths, in light and dark themes.
- [ ] Supported phone platform, with keyboard open and closed, in both themes.
- [ ] Long team labels, long allowed context, empty lists, loading and disabled buttons.
- [ ] Keyboard focus order, readable labels, accessible button names and usable text scaling.
- [ ] Charts, evidence units, signed changes, local dates and the check-in deadline.
- [ ] Browser console and failed network requests reviewed; known noise distinguished from new
  defects. Screenshots and logs contain only synthetic data and no credentials.

Mark unsupported platforms or inapplicable states with a reason. Run every changed flow in both
themes; existing reports from [the rehearsal](rehearsal-2026-11-26.md) describe earlier revisions.

## Results and handoff

Use one row per case and applicable platform/theme combination:

| Case and variant | Candidate and environment | Expected | Actual | Status | Sanitized evidence | Issue and retest |
|---|---|---|---|---|---|---|
| QA case to execute | Fill at final run | Defined above | Not observed | not run | None yet | None yet |

Allowed statuses are `not run`, `pass`, `fail`, `blocked` and `not applicable`. Keep counts by
status and surface; never count a blocked flow as passed. For a fix retain the original failure
and record its retest on the new revision. Identify the area of change that needs rerunning.

- [ ] Link each defect to its focused fix and passing retest, or state an accepted limitation.
- [ ] Account for P0 privacy/integrity risks in [the threat model](threat-model.md), including #246.
- [ ] Attach setup reproduction, UI evidence and relevant contract/failure results to the PR.
- [ ] Obtain Karim's review and required green backend/mobile CI checks for the candidate.
- [ ] Merge only after the agreed review; tag or deploy only as a separately agreed release step.

This checklist does not authorize production fixture creation, provider writes, deployment,
destructive cleanup or a merge. Keep preparation commits on the documentation branch until
review; executing the final checks remains a later task.
