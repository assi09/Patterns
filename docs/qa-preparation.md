# Jad security and QA preparation

**Prepared 2026-11-27 against `2b31471`. Owner: Jad. Status: drafts ready for review.**
These drafts prepare the reliability, security and evaluation work assigned in
[plan.md](plan.md). Final app testing is deferred until the candidate is frozen with Karim.
Application code, test runners, feature flags and deployment settings are unchanged.

## Deliverables and status

| Deliverable | Prepared content | Execution status |
|---|---|---|
| [Threat model](threat-model.md) | Assets, roles, trust boundaries, 14 threats and residual risks | Draft; final candidate review pending |
| [Failure Matrix](failure-matrix.md) | 24 failures with detection, required behavior and evidence | All rows planned for final verification |
| [Security scenarios](security-scenarios.md) | 30 cases, fixtures, benign controls and grading | Not run; expand variants before freezing the denominator |
| [Reliability test plan](reliability-test-plan.md) | 10 fault cases, 5 load stages and 10 contract cases | Not run; load targets proposed for agreement |
| [QA checklist](qa-checklist.md) | 20 setup/UI cases, platform/theme coverage and result template | Not run |
| [Evaluation checklist](evaluation-checklist.md) | 6 human-evaluation assignments, rubric and agreement protocol | Not run; final product relevance to be agreed |

Case ids make each future result traceable. `TM` identifies a threat, `FM` a failure mode and
`SEC`, `CHAOS`, `LOAD`, `CONTRACT`, `QA` and `EVAL` their planned verification records. Counts
describe preparation coverage, not executed tests or release accuracy.

## Prepare now and execute later

Now: review the product assumptions, case coverage, proposed load targets and document quality.
Use small commits, each focused on one deliverable. Review local links and references without
starting the app or calling external providers. Documents can be reviewed independently.

After the final version is identified: reconcile these drafts with any scope or API changes,
freeze candidate/configuration/fixtures and expected outcomes, implement the free runners in
focused commits, then execute and record actual results. Provider sign-ins, paid model runs and
any production rehearsal require their own agreed scope. Do not treat an older run as evidence
that a new candidate passed.

## Open issues and limits

- Note-screen privacy issue #246 remains open at the preparation revision. These drafts do not
  fix it or turn its six expected failures into passes. See [current.md](current.md) and
  [the audit](evaluation-audit.md).
- [The supervisor workflow](supervisor-workflow.md) records newer behavior than some earlier
  rows in [current.md](current.md), including evidence access and supervisor-started changes.
  Verify the actual deployed revision when planning the final run.
- [The rehearsal](rehearsal-2026-11-26.md) and [monitoring](monitoring.md) are starting points,
  with their stated gaps and dates. Defined alerts and historical tests need execution evidence
  before being described as checked on the release.
- The latest assignment covers teams, Calendar, MCP and check-in alerts. Personal features stay
  deferred behind their flag; older chat and evaluation assignments retain their own scope.

## Review and merge

Jad prepares the drafts and later records the runs. Karim reviews product boundaries and
proposed behavior. Track each failure through an issue, a focused fix and a dated retest. Keep
preparation and final execution distinct in the report. Use a branch and PR with required green
backend/mobile checks; review and agree the merge separately. No release sign-off, deployment
or final-app test result is implied by completing this preparation.
