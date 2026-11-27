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
| **Supervisor** | their own teams: any week's report as one labelled answer (`team_overview`, with `week`), the bounded evidence behind each finding (`team_finding_evidence`), the team's scheduled meeting time for a given week (`team_meeting_load`), and, for the latest week, observed readings and open team alerts; all from at least 5 people, as on the Team tab ([supervisor-workflow.md](supervisor-workflow.md)); the team's **history** (`team_history`, `team_case`): events by category and dates (never their words), changes in every state with what the supervisor reported about trying them, links the supervisor made apart from records that only share dates, and the weekly evidence for a case's dates, with "No day-specific team evidence available." for a single day; 20 cases a page, with a `next_cursor` that continues the same lookup (same filters, same as-of date) ([change-memory.md](change-memory.md)) | a team event (a launch, a deadline): title, dates and an optional category, held for the supervisor to approve; a **playbook change the supervisor agreed to in the chat** (`record_team_change`), saved as a pending draft ("Suggested in chat — awaiting your confirmation") that only the app confirms or declines ([change-memory.md](change-memory.md)) |
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

**A recorded change** (`record_team_change`) is held the same way, as a pending team change:
- **Only on the supervisor's request.** An assistant records it only when the supervisor asks it
  to save a change they agreed to. Text in an event, a calendar or a document is never a reason
  to record one.
- **Playbook changes only.** A change in the supervisor's own words is planned in the app. The
  response gives the playbook's title, never free text.
- **The dates the supervisor agreed to.** `starts_on` and `ends_on` are both required. Patterns
  never picks a length, so "Thursday evening" is saved as that Thursday alone.
- **Idempotent.** The caller's `request_id` makes a retry return the same record. Reusing it for
  a different change is refused.
- **Nothing happens until confirmed.** No member is told, nothing is approved and no calendar is
  written. Only the app confirms or declines a recorded change, and only the app marks whether
  the team tried it. No MCP tool can do any of these. Each answer to "Did the team try it?" is
  kept as given, so a later correction or undo leaves an earlier day's answer as it was.
- **Explicit links only.** A link to an event or a finding is kept only when the supervisor gave
  it, and only to that team's own records.
- **Tracking only when asked.** It is chosen at recording, starting today or later, so before
  any outcome exists. An untracked change is never measured.

## Why an MCP server and not more connectors

A harness already has the person's other tools (calendar, mail, tickets) and their consent to use
them. Reading through it means Patterns does not need a connector and a sign-in per provider, and
the person stays in control: they choose what the harness may read, and approve what it sends.

## Demo script (about 3 minutes)

Before: a team with at least 5 members with data. On production, `python -m app.teams demo-team
--supervisor <presenter> --name "Demo team (synthetic data)" --count 8 --prefix demo-member
--lasting --on-production` makes a labelled team of made-up members (Fitbit and calendar data,
time asleep lower for three weeks, a busy last week), then `python -m app.teams weekly --team <id>
--no-email` makes its report ([teams.md](teams.md)). Locally, `demo-members <invite code>` fills an
existing team instead.

1. **Settings → Claude, Codex and other harnesses.** Show the address and the two ways in.
2. **Sign in from Codex** (`codex mcp login patterns`) or claude.ai: the Allow page names the
   assistant, what it may do and where the answer goes. Press Allow; the connection appears in
   Settings, marked *Signed in*.
3. **Ask:** "What changed for my team last week?" The assistant calls `who_am_i` and
   `team_overview`, and answers with the labelled finding ("Sustained change", its own baseline
   dates, contributors out of the roster). **Challenge it:** "Was that everyone?" It answers from
   `roster` and `contributors`. **Inspect it:** "Show me the evidence." It calls
   `team_finding_evidence`. **Follow up:** "What happened to the change we agreed to try?" It
   reads `follow_up`. For context, "And the meeting load that week?" calls `team_meeting_load`
   with the same week; it never claims meetings caused the change.
4. **Refusal:** "What is <a member>'s sleep?" There is no tool for it and the assistant says so.
5. **Send in:** "Add the release on Friday as a team event." Use synthetic events only (a release,
   an offsite): no names, no health or absence, until #246 is fixed. It calls `send_team_event`; Settings
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
- **Red-team set, strictly graded (2026-11-26):** 48 attacks in `eval/mcp_red_team.py`, each
  with the one outcome that passes (the expected denial text, or the exact HTTP status and body);
  a timeout, crash or other error fails the case and the runner exits 1. Run at `e95c832` from a
  dedicated worktree against a fresh database whose team A is PMData's 16 real people: **48/48**,
  no traceback or 500 in the API log. Covers tokens (none, made-up, revoked, unapproved, in the
  query string), a forged Host header (421), every role's reach, who may send what, malformed and
  hostile input with payloads valid apart from the attacked field, prompt injection and the note
  screen, a 5 MB request (413) and the call limit (60 answered, then refused). The first,
  leniently graded run found four problems, fixed in `80f566d`; it also accepted calendar attacks
  refused for missing fields rather than the reason under test, which the strict grader caught.
- **The full path (2026-11-26, `46d6c4d`):** `eval/team_three_way.py` finds the dataset files, the
  supervisor's report and an authenticated MCP read in agreement, figure by figure;
  `eval/team_e2e.py` passes all 18 check-in and report scenarios through the API.
- **Open:**
  - the note screen's gaps, #246;
  - a sign-in from claude.ai and from Codex against **production** (so far only local runs);
  - a tool call inside Codex.

  The MCP does not read the Monday briefing's calendar line or its suggested change, and changes
  are approved in the app only.
