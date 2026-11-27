# The supervisor workflow (2026-11-27)

What Patterns does for a supervisor. It is built for one question, asked in the app or through an
MCP assistant:

> **What changed for my team, what evidence supports it, and is there anything from our last
> check-in worth following up?**

The demo is four steps: ask what changed, challenge the finding, inspect its evidence, and follow
up on an earlier decision. Fitbit data alone is enough; the calendar adds context but is never
needed.

## Decisions

| Decision | What it means |
|---|---|
| **One meaning per claim** | The app and MCP share one representation (`app/teams/view.py`), built from computed fields and fixed labels, never from a stored sentence |
| **Two comparisons, each labelled** | A **priority** comes from the four-week scan and is measured against one *fixed* baseline (the 28 days before the first scanned week). It is a **"Sustained change"** when it held for at least 2 weeks running, a **"New change"** otherwise. A **weekly line** is **"This week vs. the previous four weeks"**. Each carries its own dates, so the −46 min (sustained, against Sep 28 to Oct 25) and the −20.6 min (this week against the four weeks before) no longer look contradictory |
| **Counts are scoped** | "0 of 9 metrics changed" now reads "metrics changed this week vs. the previous four weeks"; MCP says "*n* of *m* reportable metrics …; *k* had fewer than 5 people with data" |
| **Team size and contributors are separate** | `roster` is the team's size; `contributors` is how many people had enough data for that figure; `minimum` is 5 |
| **Evidence is opened only through its own report** | MCP: `team_finding_evidence(team_id, report_id, evidence_id)`. App: `GET /teams/{id}/reports/{week}/evidence/{evidence_id}` and the **Evidence** screen. The caller's current role and team are checked; the record must be cited by that report. A guessed id, another team's report or a record of another report gets "not found" and nothing else |
| **Records are bounded** | What was measured, target and comparison dates, method, unit, the team median, how many people were higher or lower, coverage and limits. Never a person's value, a quartile (with 5 people a quartile is close to one person), a note, a member, or a check-in |
| **No free text through MCP** | Every MCP response is built from computed fields and fixed labels. A change's title is the playbook's own title, or "Custom team change" for one the supervisor wrote. The latest week's compatibility keys (`weekly_report`, `open_alerts`) are rebuilt from fields, not from stored headline, section or alert sentences. **One free-text label remains:** the team's name, which the supervisor chose |
| **No automatic scheduling proposals** | The Monday briefing reports the team calendar beside the Fitbit findings and **proposes nothing itself**. A change is started by the supervisor ("Plan a change"). The old behaviour is kept behind `brief(..., suggest_changes=True)` for its tests and old evaluations; nothing in the app passes it |
| **Calendar is context, not a cause** | `team_meeting_load(team_id, week)` takes an explicit week and returns that week only, with its comparison dates and a state. It never falls back to the current week, and never says meetings caused a change |
| **The calendar counts the report's group** | For any week, the calendars counted are those of the members behind that week's Fitbit report (joined by the exact moment it was made) who are still in the team. Someone who joined later, even the same day, is not counted, so a same-day joiner cannot lift a withheld figure over the minimum. Someone who has left is not counted either, because leaving withdraws their data. The response gives the counts (`cohort`), and says so when people in the report have left since, or when the week has no report to match. With no report, the group is the members at the start of the day after the week, and `cohort.basis` says so |
| **A clear change in either direction** | `clear_change` is `higher`, `lower`, `none` or `not judged` (the number of meetings), by the coach's bar in both directions; `heavier_load` says whether that direction adds load. A clearly lighter week is a fall, not "none" |
| **Follow-up as it stood then** | A historical week's answer is as of the day after that week: a change still running shows *in progress* without a result; later results, today's readings and open alerts are left out |
| **MCP stays read-only for decisions** | MCP cannot approve or decline a change and cannot write to anyone's calendar |

## The proposal already waiting on production

The eight-person demo team on production has one **evening boundary** proposal (Nov 24 to Dec 7).
The old briefing made it during the approved rebuild (Nov 26), dated from the report's Monday,
Nov 23.

- **What this change does to it:** nothing. It is not approved, declined, deleted or rewritten. It
  still appears under **Waiting for you**, and only the supervisor can decide it.
- **Its start date is now in the past.** Approving it today runs it from Nov 24 as recorded and
  tells the 8 made-up members. Declining changes nothing for anyone.
- **What we recommend:** decline it in the rehearsal, or leave it. Show "Plan a change" for a
  change the supervisor chooses.
- **Older history is kept as it was:** approved changes, declines, their results and the evidence
  they cite.

No new proposal is created by the briefing from this version on. That holds on production only
once this code is deployed; nothing on production was rebuilt or changed for it.

## MCP tools for a supervisor

| Tool | Answers | Notes |
|---|---|---|
| `who_am_i` | Role and teams | Team discovery; counted apart in the evaluation |
| `team_overview(team_id, week?)` | The week in one call: `report.state` (`findings`, `no_priority_finding`, `withheld`, `no_report`), the report and week ids, `roster` and `with_enough_data`, each priority (label, metric, direction, signed change with unit, the weeks it held, its fixed baseline, contributors and how many moved that way, the rule that fired, `evidence_id`), `this_week_vs_previous_four` (label, dates, scoped summary, changed / steady / withheld metrics), and `follow_up` | `week` is any date in the week. Without it: the latest report, plus the first version's keys (`readings`, `weekly_report`, `open_alerts`), with an alert's note removed. With it: nothing current |
| `team_finding_evidence(team_id, report_id, evidence_id)` | The bounded record | The same representation as the app's Evidence screen |
| `team_meeting_load(team_id, week?)` | Scheduled meeting time that week against each member's previous four weeks: `state` is `observed`, `below_minimum`, `unavailable` or `week_not_over`, with week and baseline dates, coverage, figures, `cohort`, and `clear_changes` in either direction with `heavier_load` | The definition is in the response: scheduled meeting time, working hours 8:00 to 18:00 on weekdays, a synced day without meetings is 0, a day never synced is missing |

**Questions the tools do not answer.**
- **"When is my next team check-in?"** Patterns does not read the supervisor's own calendar. The
  assistant uses its own calendar connector; the meeting-load response says so.
- **"Were meetings responsible?"** No tool claims a cause. The calendar shows what else happened
  that week.

## Follow-up of a change

Each team change in `follow_up` shows:
- its lifecycle: `proposed`, `declined`, `approved, not started`, `in_progress` or `ended`, with
  its dates and `as_of`;
- a controlled title (the playbook's, or "Custom team change") and who started it;
- whether it was tried. That is the calendar check when the change has one; otherwise "approved
  by the supervisor; whether the team did it is not measured here";
- for an ended change, `result`: what was measured, the `outcome` ("above the reference level",
  "below the reference level", "no clear difference detected" or "insufficient data"), the
  reference days and their label, contributors and the bounded figure, and the stored record of
  the report that covered it (`report_id`, `evidence_id`), so it opens like any finding.

When no report has covered the change yet, the result is measured on request and marked
`measured_now`.

**Why no "better" (since 2026-11-27, [change-memory.md](change-memory.md) step 0).** A change is
compared with the 28 days before it started, and changes usually start right after a drop. In a
simulation, an ordinary rebound made a change that did nothing read "better" in 39–84% of the
changes started. So results are named without a judgement, and each carries two caveats:
- it cannot show how much the change itself contributed;
- a preceding dip can make an ordinary rebound look like an improvement.

**Stored results keep their meaning.** The comparison and the test are the same as before; only
the words describing them changed. The app API still sends the old `verdict` for older app
versions, and nothing shows it.

## Evaluation

Frozen tasks are in `eval/supervisor_tasks.json` (11 scripted tasks and 1 that needs a real
client), frozen before the read path changed.

**Instance** (`eval/supervisor_instance.py`, local, git-ignored, under `data/eval/`):
- the varied-team run's **LifeSnaps 11 and LifeSnaps 4**, from the rubric-development set, under a
  made-up supervisor;
- labelled synthetic teams: calendar plus Fitbit; a team of 3; a team with an approved change;
  another supervisor's team;
- reserved research teams are never read; nothing is uploaded.

**Runner** (`eval/supervisor_eval.py`): the MCP SDK's own client, a fixed plan of calls, and checks
on the tool outputs only. A failed task gets no efficiency credit. Free: no model.

**How the comparison was kept fair.**
- The **baseline is `dc45e4e`** (main before this work). It was rebuilt from scratch in its own
  worktree: its own instance, made by its own weekly briefing, and its own server.
- Both versions were scored by the same checker, on the same date, questions, teams and weeks.
- **One check was corrected after the first development run:** the pattern for a finding's
  baseline dates did not allow the indentation the server's JSON has. The baseline has no such
  field, so the correction cannot favour either version.
- **One check accepts a renamed key (2026-11-27):** a measured follow-up result was marked by
  `"verdict"` and is now marked by `"outcome"`. The check accepts either, so the change of key
  favours neither version. This work still scores 11/11.
- **The instance builder was corrected in the review round:** reports were dated the day after
  their week, before the made-up members had joined. They are now made at build time, as the demo
  command does. Both instances were rebuilt and both versions rescored; the results did not
  change.

| Scripted MCP SDK run | Baseline `dc45e4e` | This work |
|---|---|---|
| Tasks passed | **2/11** | **11/11** |
| Checks passed | 15/44 | 44/44 |
| Tools | 7 | 8 |
| Task calls (team discovery apart: 1 each) | 13 | 14 |
| Failed calls, as planned (another supervisor's team; a guessed evidence id) | 2 | 2 |
| Response size, all task calls | 11.4 kB | 36.8 kB |
| Server time, all task calls (local, varies run to run) | 0.24 s | 0.60 to 0.73 s |
| Cost | $0 | $0 |

**Reading it.** This shows **better task coverage**: the tools now supply information the old
interface lacked. It does not show that a real assistant answers better or that a supervisor saves
time; both are still to be measured.
- **The baseline's 2 passes are partly hollow.** "Unavailable evidence is an error" passed because
  the evidence tool did not exist.
- **The baseline answered no historical question.** Without `week`, every call returned the latest
  report: January 2022 for LifeSnaps 11. Its 13 calls produced answers about the wrong week.
- **Efficiency.** This work answers "what changed that week" in 1 call and "show me the evidence"
  in 1 more. Responses are about 3 times larger, because each finding carries its own dates,
  coverage and rule. No efficiency comparison is meaningful while the baseline fails 9 of 11.
- **What this measures and what it does not.** Facts reachable through the tools, in a fixed plan
  of calls. It does not measure what a real assistant writes. That needs a real Claude or Codex
  run, reported apart (still to do). The before/after usefulness review with the doctor and timed
  supervisor runs also remain to do; the reserved cases are untouched.

## What was observed, and how

| Scenario (frozen task) | Through | Observed |
|---|---|---|
| LifeSnaps 11, week of Jul 19, 2021 (`ls11_what_changed`, `ls11_all_eleven`, `ls11_evidence`) | MCP SDK; browser | Steps −696, 0 higher and 5 lower, 5 contributors out of a roster of 11 (6 had enough data, minimum 5), compared with Jun 21 to Jul 18, 2021; the record opens with method and limits. On screen: the weekly line and its Evidence page show the same figures and dates. No priority finding that week; sleep withheld (4 of 5) |
| LifeSnaps 4, same week (`ls4_withheld`) | MCP SDK | Withheld, "3 of the 5 people needed", no figure |
| Quiet week, May 24, 2021 (`quiet_week`) | MCP SDK | Ready, no priority finding, no weekly change, the withheld metrics named |
| A week with no report (`no_report_week`) | MCP SDK | `no_report`, no other week substituted |
| Historical calendar, Jul 19, 2021 (`historical_calendar`) | MCP SDK | `unavailable` for that week: no figures, no zero |
| Synthetic Fitbit and calendar (`synthetic_both_sources`) | MCP SDK; browser, light and dark | "Sustained change", time asleep −46 min against Sep 28 to Oct 25, Nov 2 to 22; calendar for the same week with its comparison dates; no proposal made by the weekly job; nothing causal |
| Follow-up over time (`action_follow_up`) | MCP SDK | In progress, with no result, as of the week it ran; ended, with its result and stored evidence, now |
| Scope and authorization | MCP SDK; tests | Another supervisor's team: "No such team"; a guessed evidence id: not found, nothing revealed; a revoked token: 401 |
| Insufficient data and unknown records on screen | browser, light and dark | A withheld metric's record says "4 of the 5 people needed … no team figure"; a guessed id shows "There is no such evidence in that report" |

**Not observed yet:**
- A real Claude or Codex client on the new tools.
- The two-connector question ("when is my next check-in?"), which needs the assistant's own
  calendar connector.
- Production: nothing was deployed, rebuilt or written there.
