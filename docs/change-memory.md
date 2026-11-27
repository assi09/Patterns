# Team change memory: plan (2026-11-27, not built)

**Goal.** Patterns remembers what a supervisor decided to try, whether the team tried it, and what
the team's data showed afterwards. A later assistant (another Claude or Codex chat, through MCP) or
the app can then answer: **"Have we tried anything like this before, and what happened?"**

**Who decides what.**
- **Assistant:** recommends a change from Patterns' findings and the team's events, in the chat.
- **Supervisor:** agrees in the chat. The assistant records that agreement in Patterns.
- **Patterns:**
  - holds it **waiting for confirmation**, and confirmation happens only in the Patterns app
    (option B, chosen 2026-11-27);
  - measures what followed;
  - returns the history.

Patterns never says a change "worked", and never ranks changes.

**Status: approved 2026-11-27, building.** Step 0 (below) has been run, and the three decisions
are made (end of this page). Build order: the outcome fix first, then the record and the history.

## Step 0: can the outcome be trusted? (done)

**Why it matters.** Changes are usually started right after a report shows a drop. If the drop
was temporary, the team recovers on its own. The outcome measure in use today
(`playbook.verdict` on `challenge_result`) compares the change's days with the 28 days just before
it. Those 28 days hold the drop, so recovery alone could read as "better".

**The test.**
- **Script:** `eval/change_outcome_bias.py`, on synthetic data where the truth is known; $0.
- **Results:** `eval/results/change_outcome_bias_2026-11-27.json`.
- **Teams:** 300 per cell, with 5, 6 or 8 members, on two metrics (time asleep and steps).
- **When a change starts:** the Monday after **two flagged weeks running** (a "Sustained change").
  It runs 14 days and, unless stated otherwise, **does nothing**.
- **Three kinds of everyday variation:**
  - independent days;
  - a slow personal drift;
  - team-wide weekly shifts, like deadlines and holidays.
- **Two measures compared:**
  - *Now*: the change's days against the 28 days just before it (in use today).
  - *Before the drop*: the change's days against the 28 days before the drop was first flagged.

**How often each measure reports a difference** (the change does nothing, unless stated; for these two metrics, "better" means above).
Percentages are of the **changes actually started** (the trigger fired), not of the 300 teams; the
counts are in the next table. They describe this failure mode under simulated conditions; they are
not error rates measured on users.

| Situation | Daily variation | Now says "better" | Before the drop: "above" | Before the drop: "below" |
|---|---|---|---|---|
| Random start, no drop | independent | 2–3% | – | – |
| | team-wide weekly shifts | 13–15% | – | – |
| **After a 2-week dip that ends on its own** | independent | **81–84%** | 2–3% | 1–2% |
| | slow personal drift | **39–40%** | 1% | 4–5% |
| | team-wide weekly shifts | **62–64%** | 12% | 16–18% |
| After a 3-week dip (still running into the change) | independent | 2–4% | 0% | 75–81% |
| A change that truly helps (0.5 SD), after a 2-week dip | independent | 100% | 84% | – |
| | slow personal drift | 93–94% | 39–40% | – |
| | team-wide weekly shifts | 98–99% | 66–69% | – |

Ranges cover both metrics. The 3-week dip's "worse" is correct: the team was still below its level
before the drop.

**Changes started, of 300 teams per case** (time asleep / steps):

| Situation | Independent days | Slow personal drift | Team-wide weekly shifts |
|---|---|---|---|
| Random start | 300 / 300 | 300 / 300 | 300 / 300 |
| After a flagged drop that was only noise | 1 / 3 | 0 / 6 | 64 / 65 |
| After a 2-week dip | 251 / 249 | 156 / 151 | 191 / 205 |
| After a 3-week dip | 256 / 252 | 166 / 156 | 210 / 217 |

Drops that were only noise rarely triggered a change; with so few, that row is not interpreted.

**What it shows.**
1. **The measure in use credits recovery.** After a temporary dip it says "better" for a change
   that did nothing in **4 to 8 of every 10 teams**.
   - This affects the follow-up result Patterns shows **today** for any change started after a
     drop.
   - Stored as memory, it would teach the next assistant that a useless change works.
2. **Measuring against the level before the drop removes most of that.** False "above" falls to
   about 1–3%, but stays about 12% with team-wide weekly shifts.
   - It answers a different question: is the team **above, below, or not clearly different from**
     its level before the first flagged week?
   - "No clear difference detected" is **not** "back to normal". Calling it that needs a test that
     the difference is small enough to count as equal, which is not built.
   - A dip still running reads as "below". That is true, and it is not a judgement of the change.
3. **No measure here can separate the change from recovery or from a deadline that ended.** With
   5–8 people and one trial, Patterns can report what followed, never that the change caused it.
4. **The before-the-drop measure is less sensitive.** It finds a real 0.5 SD improvement in 40–84%
   of teams.
   - "No clear change" must read as "not shown", never as "did not help".
   - Several similar trials, retrieved together, are more informative than one.

**Decision (2026-11-27).**
- **A linked change:** the metric and the comparison dates are taken from its verified triggering
  finding **when the change is recorded**, and frozen. The comparison is the 28 days before the
  finding's first flagged week, shown as "before the first flagged week" with its dates.
- **A change with no linked finding** (every change made so far): the existing dated 28-day
  comparison, with a stated caveat that a preceding dip can make an ordinary rebound look like
  improvement. Results already stored keep their meaning (the same comparison and the same test);
  only the words change.
- **Four outcome labels, in the app and in MCP:**
  - "above the reference level";
  - "below the reference level";
  - "no clear difference detected";
  - "insufficient data".

  Each shows the observed difference and the contributor count when permitted. Nothing says
  "better", "worse", "worked" or "returned to baseline".
- The change's implementation status ("tried", step 4) is shown beside the observation. A fresh
  assistant should be able to say: **"You confirmed trying it; here's what followed; we can't
  determine how much the action contributed."**

## What is built on

| Exists today | Used for |
|---|---|
| `TeamAction` (`proposed` → `approved` / `declined`; a playbook change or "custom"; metric; dates) | The change record |
| `actions.decide` (the app's **Waiting for you**: approval tells the members) | Confirmation, unchanged: only in the app |
| `view.follow_up` (lifecycle as of a date; stored result from the report) | The history's states, with `as_of` |
| Held MCP submissions (`send_team_event`: held, screened, approved in the app) | The pattern for an MCP write that changes nothing until confirmed |
| Report evidence ids (`team_finding_evidence`) | Linking a change to the finding that prompted it |

## The record: four facts, kept apart

| Fact | Set by | Stored |
|---|---|---|
| **Recommended and agreed in a chat** | The assistant, through MCP | Which playbook change, the metric (fixed now, so no number is picked afterwards), dates, the prompting finding (`report_id`, `evidence_id`, checked against the team's reports), an event type from a fixed list, which connection saved it, when, and a `request_id` so a retry makes no duplicate |
| **Confirmed or declined** | The supervisor, in the app only | `approved` / `declined`, when. Approval tells the members, as today |
| **Tried or not** | The supervisor, in the app ("Did the team try it?" yes / no), after it starts | A separate field, never inferred from approval; not answered means **unknown**. Where the playbook has a calendar check, that is shown beside it as its own observation |
| **What followed** | Patterns, deterministically, after it ends | The outcome above with its dates, contributors, measure and evidence id, **stored once** so a later answer is the same answer |

## MCP

| Tool | Does | Never |
|---|---|---|
| `record_team_change(team_id, request_id, play, starts_on, prompted_by?, event_type?)` | Saves the change as **waiting for confirmation**; the app shows **"Suggested in chat — awaiting your confirmation"**. A repeat of the same `request_id` returns the same record. Refused for a team the caller does not supervise now, a past start, an unknown change, or an evidence id not in that team's reports | Approve, decline, mark tried, edit, delete, notify anyone, or write a calendar |
| `team_change_history(team_id, metric?, play?, event_type?)` | Every recorded change for that team, including declined, not tried and inconclusive ones. For each: controlled title, the four facts with dates, the outcome and its evidence reference, `as_of` | Return free text, a person, a note or a check-in; rank changes; say one "works" |

The weekly `team_overview` follow-up keeps working, with the same states and the corrected
outcome.

## Risks and how each is handled

| Risk | Handling | Tested by |
|---|---|---|
| "The supervisor agreed" is wrong (a misunderstanding, or an instruction hidden in an event title) | Nothing reaches the team until a tap in the app; the record says "agreed in chat, not confirmed" | Scripted: a record made through MCP notifies nobody. Live: an injected event title |
| Approval through MCP | No tool can do it; `record_team_change` only ever writes `proposed` | Scripted and red-team |
| A duplicate on retry | `request_id`, unique per team | Scripted |
| Another supervisor's team, a former supervisor, a guessed evidence id | The same checks as today ("No such team", not found) | Scripted |
| Free text naming a person or health (#246) | Playbook changes only through MCP in this version (see decision 1); controlled labels in every response | Regression test, as for #259 |
| Choosing the metric after the fact | Fixed when recorded; the outcome is computed only on it | Unit test |
| Calling recovery a success | The before-the-drop measure; fixed wording; "observed, not caused" on every result | Step 0's simulation, kept as a statistical test over many seeds |

## Frozen tasks (before any code)

`eval/change_memory_tasks.json`: scripted tasks for the MCP SDK client, and live tasks for a real
assistant, frozen now. The baseline is `main` today, which has neither tool, so it is expected to
fail the memory tasks. The point of the scripted run is coverage and safety; the live run is
reported apart.

## Build order (each a focused PR, after the open decisions)

1. **This plan**, the step-0 result and the frozen tasks.
2. **The outcome fix:** the before-the-drop measure for linked changes and the caveat for the rest.
   Stored on the change; the follow-up shows it. Tests: step 0 as a many-seed property test.
   Without this step the memory would teach the wrong thing.
3. **The record:** a migration (new columns on `team_actions`) and `record_team_change` with its
   checks. In the app, **Waiting for you** says "agreed in chat with <assistant connection>".
4. **"Did the team try it?"** in the app, and `team_change_history`.
5. **The gate:**
   - every frozen scripted task passes, at least as well as on `main`;
   - an MCP red-team pass, covering approval, another team, duplicates and injected text;
   - full checks;
   - then one live run (Claude or Codex) in a fresh chat, on the synthetic team, reported apart.

   If any part fails, it does not ship.

**Production.** Nothing is written there before the gate. Deploying needs your approval, and the
live run needs your sign-in (the same as today's Codex connection). Recording a change on the
synthetic demo team in the live run is a write; it is asked for at that point. The waiting evening
boundary proposal is left alone.

**Dec 5.** A change needs 1–2 weeks to run before it has an outcome. A demo of "what happened"
therefore uses a labelled synthetic history, the way the demo team does.

## Decisions (owners, 2026-11-27)

1. **Playbook-only submissions through MCP** in this version.
   - A supervisor can still write a custom change in the app.
   - MCP returns a custom change's metric, dates, state and permitted outcome under "Custom team
     change", and says the assistant cannot tell exactly what it involved.
   - Recording through MCP leaves the change pending and notifies no one.
   - The history keeps the sequence clear: proposed; approved or declined; reported tried or
     untried (unknown when not reported); the measured outcome.
2. **Fixed event categories, optional.**
   - The categories: deadline, launch, travel, holiday, reorganisation, onboarding, other.
   - "Other" is for an event that is known but does not fit the list. The category is left unset
     when no event was given.
   - A shared category helps retrieval. The history also shows each change's type, metric and
     dates, so the supervisor judges relevance, and it includes untried and inconclusive changes.
3. **The outcome correction applies to both the app and MCP**, as described in step 0's decision.

**Acceptance.**
- **A fresh chat asks "Have we tried anything like this before?"** It must retrieve the right
  team's change, tell approval from implementation, and cite the dated result. It must handle an
  inconclusive or untried case as accurately as a favourable one.
- **The pre-deploy live test** runs on local or staging data.
- **Production** deployment and writes each need separate approval.
