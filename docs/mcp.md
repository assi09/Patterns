# The MCP server: Patterns for Claude, Codex and other harnesses

Status: **built, 2026-11-26**: the server at `/mcp/`, its tools, tokens and approvals
(`backend/app/harness/`, `backend/app/api/harness.py`, migrations 0037-0039), OAuth sign-in
(`backend/app/harness/oauth.py`, the app's `/connect` page), each call recorded, and the Settings
card "Claude, Codex and other harnesses". Tested by direct tool calls, by the MCP SDK's own client
over HTTP for each role, by the SDK's OAuth client signing in through the real Allow page, and
by Claude Code itself (see [How it was tried](#how-it-was-tried)). Proposed by the instructor
([pivot.md](pivot.md)): a person who already works in an MCP harness (Claude Code, Claude
Desktop, claude.ai, Codex) connects it to Patterns. The harness can read what that person may
see, and send in what it knows that Patterns cannot read itself, such as calendar findings from
its own connectors. Patterns stays the one place that computes and checks; the harness never
sees more than the app would show the same person.

## Connecting

The server's address is `https://<api>/mcp/` (Settings shows it with a copy button). There are
two ways in, and both lead to the same kind of connection: listed in Settings with what it did in
the last 24 hours, revocable there, and reaching exactly what the person may see.

**Sign in (OAuth): claude.ai, Claude Desktop, Codex.** No token to copy.

| Assistant | Steps |
|---|---|
| claude.ai or Claude Desktop | Settings → Connectors → *Add custom connector* → paste the address. Claude opens Patterns; sign in if asked, read what it may do, press **Allow**. |
| Codex | `codex mcp add patterns --url https://<api>/mcp/`, then `codex mcp login patterns`. The browser opens Patterns' Allow page; press **Allow**. |

The assistant registers itself (RFC 7591), sends the person to `/authorize`, and the API sends
them on to the app's `/connect` page. The page is open whether or not the person is signed in, so
signing in there keeps the request. It names the assistant (its own claim), lists what it may do
for the person's role, says it can never read another person's data or a check-in alert, and
shows **where the answer goes back to**, the one detail an impostor cannot fake. Allow makes a
one-time code that works once, for 5 minutes, for that assistant only and only with its PKCE
verifier; Deny sends `access_denied`. HR can only say no.

**A pasted token: Claude Code or Codex in a terminal.** In Settings, name a token (one per device
or assistant) and press *Make a token*. The card then shows, filled in and with a Copy button
each, shown only this once:

```bash
# Codex: register once, and put the token where Codex reads it (never in its config file)
codex mcp add patterns --url https://<api>/mcp/ --bearer-token-env-var PATTERNS_TOKEN
export PATTERNS_TOKEN=pat_...          # in ~/.zshrc or ~/.bashrc

# Claude Code: one line
claude mcp add --transport http patterns https://<api>/mcp/ --header "Authorization: Bearer pat_..."
```

**What is stored and for how long.** Only SHA-256 hashes of tokens and codes. Pasted tokens do not
expire; at most 5 per person. A sign-in's access token lasts an hour and its refresh token 30
days, and both rotate on every refresh, so an old one stops working; signing in again replaces
that assistant's last connection. Revoking in Settings, the assistant's own `/revoke`, or deleting
the account ends a connection at once. Every call is checked against the account's **current**
role, as in the app; each token is limited to 60 tool calls a minute, and anyone may register an
assistant but at most 200 an hour.

**What is recorded.** Each tool call: which tool, whether it worked, when, and by which
connection. Never its inputs or results.

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

## Demo script (about 3 minutes)

Before: a team with at least 5 members with data. Locally, `python -m app.teams demo-members
<invite code>` fills one with made-up members (Fitbit and calendar data, a sleep drop and a busy
week in the last full week), then `python -m app.teams weekly --no-email` makes its report.

1. **Settings → Claude, Codex and other harnesses.** Show the address and the two ways in.
2. **Sign in from Codex** (`codex mcp login patterns`) or claude.ai: the Allow page names the
   assistant, what it may do and where the answer goes. Press Allow; the connection appears in
   Settings, marked *Signed in*.
3. **Ask:** "How is my team doing this week, and what does their meeting load look like?" The
   assistant calls `who_am_i`, `team_overview` and `team_meeting_load`, and answers from team
   figures, each from at least 5 people.
4. **Refusal:** "What is <a member>'s sleep?" There is no tool for it and the assistant says so.
5. **Send in:** "Add the release on Friday as a team event." It calls `send_team_event`; Settings
   shows *From your harness: Team event* waiting. Approve it; only then is it a team note.
6. **Settings** again: the connection lists what it did (`team_overview 1 · send_team_event 1`).
   Revoke it; the assistant's next call is refused.

## How it was tried

- **Tests:** `tests/test_mcp.py`, `test_mcp_postgres.py` (two approvals at once apply once) and
  `test_mcp_oauth.py` (the whole sign-in through the real routes: discovery, registration,
  Allow and Deny, code reuse, a wrong verifier, another assistant's code, an unregistered return
  address, expiry, refresh rotation, revoking from Settings and from the assistant, HR, the
  registration cap).
- **The MCP SDK's own OAuth client, end to end (2026-11-26):** a local API on a throwaway
  database and the web app pointed at it; the client registered, a browser signed in on the real
  Allow page and allowed it, the client called a tool, refreshed (the old token then failed),
  and revoking in Settings ended it; HR could only say no. 9 of 9 checks.
- **Claude Code itself (2026-11-26),** headless with an isolated configuration (`--mcp-config`,
  `--strict-mcp-config`) and a pasted token, against the same local API with a made-up team of
  6: it read the team's sleep drop and the busy week from team figures, and when asked for one
  named member's sleep it reported that no tool reads another person's data.
- **Codex 0.172:** the app's commands register the server as shown (`codex mcp list`: bearer
  token from `PATTERNS_TOKEN`, not in its config file). A tool call inside Codex needs a Codex
  model login, which was not available on the test machine; that run is still to do.
- **SDK quirk:** its `/revoke` form needs a `client_secret` field even from a public client
  (empty is fine).
