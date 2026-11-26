# Supervisor and MCP rehearsal (2026-11-26 to 27)

What was verified through each interface, how, and what was not. Every account and team here is
synthetic, except the read-only research page, which is built from public LifeSnaps data and
stays on this computer.

## 1. The supervisor screen, run locally end to end

**Setup** (app and API at `main` `0e8c5b2`):
- **Database:** a throwaway local PostgreSQL database (`fa_rehearsal`).
- **Supervisor:** a made-up account with a password.
- **Teams:** both demo teams made by the real command (`python -m app.teams demo-team`, eight
  members with `--lasting`, and three members).
- **The Monday job:** `weekly --no-email --agent` with a $0.10 cap and a deliberately invalid
  model key. One finding, so no model call: **$0**.
- **The app:** the web build (Expo, `EXPO_PUBLIC_API_URL` set to the local API), driven by a
  Playwright script and checked in light and dark mode.

| Step | Through | Verified | Result |
|---|---|---|---|
| Sign in, skip the tour, open Team | browser | the eight-person team opens with its briefing | ✅ |
| Read the finding | browser | "Time asleep has been lower for 3 weeks running: median change -46 min **against Sep 28 to Oct 25** (8 of 8 people)", then the calendar line and the suggestion | ✅ |
| The dates match the cited evidence | API response the screen renders | the item cites `team_scan` record whose baseline window is 2026-09-28 to 2026-10-25, the same dates as the sentence | ✅ |
| Inspect the evidence behind the finding | browser | **not possible**: the Team screen links to no evidence record, and `GET /evidence/{id}` returns 404 for team records (it serves personal evidence only) | ❌ gap |
| Approve the suggestion | browser | "Waiting for you" card ("Evening boundary, Nov 24 to Dec 7") → Approve; after reload it is approved, the button is gone, and 8 members got one notification each | ✅ (local copy only) |
| The withheld team | browser | "Not enough yet: Team figures need at least 5 people with data; last week 3 had some"; its report says "No report this week: 3 of the 5 people needed had data"; no figures, no evidence records, no briefing | ✅ |
| Console | browser | no errors except 404s from `/data/status` and `/days/latest`, the personal routes switched off in the team product | ◐ expected, but noisy |

**Seen on the screen and worth a sentence in the demo.** The same week shows two different sleep
figures:
- the briefing's −46 min against Sep 28 to Oct 25;
- the report's section, "Time asleep −20.6 min median, 6 lower, 2 higher", against the four weeks
  just before.

They answer different questions, and each now names its own period. But the summary also reads
"0 of 9 metrics changed" under a "Needs attention" headline. A supervisor needs one sentence
explaining that the first is the lasting scan and the second this week's check.

## 2. MCP, run locally with the MCP SDK's client

**Setup:** the same local API and made-up supervisor; a personal token from `POST /me/tokens`;
the SDK's `streamable_http_client` and `ClientSession`.

| Call | Verified | Result |
|---|---|---|
| `tools/list` | 7 tools: `who_am_i`, `team_overview`, `team_meeting_load`, `my_recent_days`, `my_calendar_days`, `send_calendar_days`, `send_team_event` | ✅ |
| `who_am_i` | role supervisor, both teams | ✅ |
| `team_overview`, eight-person team | headline and the nine section lines; each matches the app's section (e.g. time asleep −21 min, 2 higher, 6 lower; steps −330) | ✅ |
| `team_overview`, three-person team | withheld, the same reason, no readings, no figures | ✅ |
| `team_meeting_load` | eight members, figures at least 5 people; time in meetings +468 min (7 h 48 min), as on screen | ✅ |
| `my_recent_days` as the supervisor | empty, no error (the supervisor has no data of their own) | ✅ |
| The briefing's finding, its dates or its evidence | **not exposed**: `team_overview` returns the headline ("lower for 3 weeks running") and this week's section ("no clear change, −21 min") with nothing joining them | ❌ gap |

**Not verified:**
- No real assistant (claude.ai or Codex) signed in, locally or on production.
- No MCP call reached production.
- The red-team run (48/48 at `e95c832`) remains the evidence for refusals.

## 3. Production (assikarim10@gmail.com, approved rebuild)

**Approved:** rebuild only the eight-person synthetic team, after the fix was live (production at
`0e8c5b2`, deploy smoke test passed).

**What was done, all through `railway ssh` on the API service:**
1. `demo-team --remove` removed only the recorded team and its 8 made-up accounts.
2. `demo-team --count 8 --prefix demo-member --lasting` created team
   `db48f4b2-b00b-4e94-a6aa-22c430e71781`.
3. `weekly --team <id> --no-email`, then the same with `--agent` and a $0.10 cap: briefed for
   **$0.0000** (one finding, so no model call).

**A first attempt passed the team name with literal quotes.** Removal answered "No such team" and
creation refused, because the accounts still existed. A read-only check confirmed nothing had
changed before the retry.

**Verified read-only on production afterwards:**

| Check | Result |
|---|---|
| Team under assikarim10@gmail.com, 8 recorded members | ✅ |
| Report for the week of Nov 16 ready, emailed: no, cost $0 | ✅ |
| Briefing: change, calendar, proposal | ✅ |
| The finding names "against Sep 28 to Oct 25"; its cited record (`team_scan` `07e4ef19ca63`) has baseline window 2026-09-28 to 2026-10-25 | ✅ match |
| The evening boundary is still `proposed`, and no member has been told | ✅ left for the rehearsal |
| The three-person team: withheld, no evidence records, no briefing | ✅ untouched |
| Other teams ("test", "MCP Test"): still there, 4 teams in total before and after | ✅ untouched |

**Not verified on production:** the screen itself. It needs the supervisor's own sign-in. The
dates were checked in the stored report the screen renders, and the same code was checked on
screen locally (section 1).

**For the rehearsal:**
- The suggested change runs Nov 24 to Dec 7. It starts the day after the report's week, so a
  proposal approved on Nov 27 starts in the past.
- Approving it tells the 8 made-up members only.

## 4. The read-only research page

`python eval/research_page.py` writes `data/eval/varied_teams/research_page.html` from the local
experiment database. Nothing goes to production and nothing is uploaded.

**What it shows:**
- **Group A** (LifeSnaps 11, 11 people, week of 19 Jul 2021):
  - the finding "Steps fell across the team: median change −696 steps (0 of 5 higher, 5 lower)";
  - 5 contributors, compared with 21 Jun to 18 Jul 2021;
  - each section with its contributor count, comparison period and its aggregate evidence record
    (opened on demand).
- **Group B** (LifeSnaps 4, 4 people, the same week): only "No report this week: 3 of the 5
  people needed had data". A withheld report keeps no team figures, so none are shown.

**Labels and data:**
- The page says the groups are constructed from real research participants, not real teams.
- It credits LifeSnaps (Yfantidou et al. 2022) with the dataset link and the CC BY 4.0 licence.
- Reserved teams are refused by the script.
- Checked: no participant id, account or daily value on the page, and no browser console errors.
  It was viewed in light and dark mode.

## Still open

- **#246 (privacy, open):** the note screen lets a named health or absence remark through (6
  known misses). The demo uses synthetic notes only. This stays the top privacy issue.
- **Supervisor evidence view:** closed on the branch of 2026-11-27 (not yet deployed). Each finding
  and weekly line opens its record on an Evidence screen ([supervisor-workflow.md](supervisor-workflow.md)).
- **MCP:**
  - The dated finding and its evidence: closed on the same branch (`team_overview` with `week`,
    `team_finding_evidence`).
  - No real assistant sign-in has been tested.
- **The weekly job is unmonitored:** no metric for reports made, withheld or briefed, or for
  approvals and declines.
