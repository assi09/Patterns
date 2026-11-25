# The team product (scope change of 2026-11-25)

On 2026-11-25 the instructor asked us to narrow the project: **the app is now built around the
team feature**, for the person responsible for a group of employees. The individual side (Ask,
Findings, Reminders, logging) is kept in the code but hidden behind a flag; members still connect
their own Google Health account, because the team figures come from it. More of the product may
be deterministic than model-based; what matters is that it solves the supervisor's problem.

## User and problem

A supervisor or department head, with HR, is responsible for a team's workload. Today they learn
that a team is overloaded late and indirectly: surveys, sick days, people leaving. They cannot see
whether a launch, a run of late meetings or a new rota is wearing the team down while it happens,
and they cannot see that one person is in serious trouble unless that person says so.

## Two gateways

| Gateway | Who sees it | What | Decided by |
|---|---|---|---|
| **1. Team** | the supervisor | weekly aggregates with at least 5 people, daily team alerts, the Monday briefing written by the coach, with the team's calendar load beside its sleep and recovery | code computes; the coach writes and is verified ([teams.md](teams.md)) |
| **2. One person** | HR and the supervisor | "please check in with X" when the person's own data shows a sustained, extreme change; only for people who opted in, who are told first | code only, no model ([escalation.md](escalation.md)) |

## The coach

The Monday briefing becomes a coach for the department: what changed in the team, what the
calendar shows around it (meeting load, after-hours meetings, deadlines), and one team-level
change from the playbook to try, for the supervisor to approve. Every number cites evidence from
deterministic tools; the coach never sees a person's values or the check-in alerts.

## The calendar

Two ways in, both kept:

- **Direct:** each person connects Google Calendar or Outlook (Microsoft Graph), read-only. Code
  reduces events to daily counts per person (meeting hours, meetings after hours, back-to-back
  meetings, focus time); titles, attendees and descriptions are never stored. Team calendar
  figures follow the same 5-person rule as everything else.
- **Through a harness (MCP):** a person who already uses Claude, Codex or another MCP client
  connects it to our MCP server. The harness has its own access to their calendar (and more), so
  it can send calendar findings into the app, and read back what it is allowed to.

## The MCP server

Every call carries a personal access token made in Settings; the server checks the role on every
call.

| Role | Reads | Sends in |
|---|---|---|
| Supervisor | their own teams' reports, alerts and briefing: aggregates with at least 5 people only | team context (a deadline, a launch, an event) |
| Member | their own data only | their own calendar findings |
| Anyone | **never** another person's data, another team, or check-in alerts | |

What a harness sends in is untrusted input: checked against a fixed schema (dates, counts, event
kinds), free text never treated as instructions, labelled as coming from a harness, and kept apart
from measured data until the person or supervisor approves it.

## Plan

Features **Wed 25 to Fri 27 November**; **Saturday and Sunday are for testing only**; then the
report, demo and rehearsal for 5 December. Jad works on the failure matrix, threat model and red
team throughout, now including the MCP server and the check-in alert.

| Day | Features |
|---|---|
| Wed 25 | this page and [escalation.md](escalation.md); the flag that hides the individual side, with today's `main` tagged `v0.9-personal`; the check-in alert's backend |
| Thu 26 | the check-in alert's screens (HR inbox, the member's consent); calendar direct, Google and Outlook; team calendar figures |
| Fri 27 | the MCP server; the coach using calendar load; documents |
| Sat 28 – Sun 29 | testing only |
