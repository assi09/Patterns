# The MCP server: Patterns for Claude, Codex and other harnesses

Status: **being built, 2026-11-25** (branch `feat/mcp-server`). Proposed by the instructor
([pivot.md](pivot.md)): a person who already works in an MCP harness (Claude Code, Claude
Desktop, Codex) connects it to Patterns. The harness can read what that person may see, and send
in what it knows that Patterns cannot read itself, such as calendar findings from its own
connectors. Patterns stays the one place that computes and checks; the harness never sees more
than the app would show the same person.

## Connecting

- In the app, **Settings → Connect a harness** makes a personal access token, shown once. The
  harness is configured with the server's address (`https://<api>/mcp`) and the token as a
  bearer token.
- Only a SHA-256 hash of each token is stored. A token can be revoked at any time; revoking or
  deleting the account stops it at once. Each use records when it was last used.
- Every call is checked against the token's account and its **current** role, as in the app.

## What each role may do

| Role | Reads | Sends in |
|---|---|---|
| **Supervisor** | their own teams: the observed readings, the latest weekly report's team figures, open team alerts, the team's meeting load; all built from at least 5 people, as on the Team tab | a team event (a launch, a deadline): title and dates, held for the supervisor to approve |
| **Member** | their own recent days (sleep, steps, resting heart rate, HRV), their own calendar counts | their own calendar days (meeting minutes, meetings, after-hours minutes, back-to-back, focus minutes), held for them to approve |
| **HR** | nothing through MCP | nothing |
| **Anyone** | **never** another person's data, another team, a figure from fewer than 5 people, or any check-in alert | |

Check-in alerts never pass through MCP, for any role ([escalation.md](escalation.md)).

## What a harness sends in

What a harness sends is **untrusted input**:

- checked against a fixed schema: ISO dates within the last 60 days or next 14, counts and
  minutes within bounds, short titles; anything else is refused with the reason;
- free text is stored as data, never shown to a model and never treated as instructions;
- labelled as coming from a harness, and **held as pending** until the person (or, for team
  events, the supervisor) approves it in the app. Nothing a harness sends changes a figure,
  an alert or a report before that.

## Why an MCP server and not more connectors

A harness already has the person's other tools (calendar, mail, tickets) and their consent to use
them. Reading through it means Patterns does not need a connector and a sign-in per provider, and
the person stays in control: they choose what the harness may read, and approve what it sends.
