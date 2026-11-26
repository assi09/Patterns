# Evaluation audit of the team product (2026-11-26)

**The standard:** every claim the shipped app makes is accounted for, by a reproducible result, an
observed failure or a named gap. It is not "every possible behaviour is correct", which no finite
suite can show.

**Organising guidance.** The course's C9 lecture, *Evaluating and Monitoring AI Agents*:
- slides 8–12: levels (component, step, trajectory, end to end);
- slide 31: seven scenario categories;
- slides 39–50: monitoring.

**Sources and caveats:**
- **The C9 slides were not available on this machine.** The levels and categories below follow the
  course reviewer's summary of them. Check the mapping against the slides before citing slide
  numbers in the report.
- **The formal grading requirements** come from the project announcement (`503N_798S.pdf`, read
  2026-11-26):
  - Rubric 2, *Agent performance / evaluation*: 20%.
  - Rubric 3, *AgentOps & observability*: 15%.
  - Rubric 4, *Reliability, QA & security*: 15%.
  - "Evidence supporting their claims rather than relying only on prepared examples."
  - Baselines, held-out testing, adversarial and failure testing, failures turned into regression
    tests, a Failure Matrix and a threat model.
  - Cost per successful task.
  - A demo of edge cases, failures, invalid input and security challenges.
- **Revision:** app code at `main` `f314644` (#254). The tests in the matrix ran at
  `eval/varied-teams` `1956044` (same app code): **142 passed, 6 xfailed (#246)**.
- **What runs where:**
  - **Deterministic code:** every team figure, sentence, calendar line and suggestion.
  - **A model** only chooses the weekly highlights when a report has more than one priority, and
    matches a coming note to a past one.
  - **External assistants** (Claude, Codex) reach Patterns only through MCP.

## The varied-team experiment (real people)

**Run:**
- Command: `PYTHONPATH=backend:eval python eval/varied_teams.py run`.
- Frozen before the first run in `eval/varied_teams_spec.json` (commit `f0e8d81`).
- Results in `eval/results/varied_teams_2026-11-26.json`, at `e1bc5d1`.
- Free: no model call.

**Data:**
- **People:** 67 real people, nobody reused: LifeSnaps 51 (Yfantidou et al. 2022, CC BY 4.0) and
  PMData 16 (Thambawita et al. 2020, CC BY 4.0).
- **Teams:** 11 primary teams, formed by us at random with a fixed seed.
  - LifeSnaps: 3, 4, 5, 6, 9, 11 and 13.
  - PMData: 1, 4, 5 and 6.
- **Weeks:** 36 LifeSnaps weeks and 17 PMData weeks, so **320 team-weeks**.
- **Not in the data:** workplace relationships, wear time and calendars. The teams are not real
  teams, and no calendar line can appear.

**Corrections, all disclosed in their commits:**
- The run code was corrected three times before any outcome existed: two file-reading fixes and
  one grader fix.
- After the first full run, three grader bugs were found and fixed. The grader misread "−3,810" and
  bedtime units, counted an empty briefing as missing, and skipped nested weekly figures.
- The app's text matched its evidence in every case checked by hand.

| Team (roster) | Weeks | Withheld | Ready | of which quiet | Metric 1 short (4) | Activity reportable, sleep not | Most contributors to any metric |
|---|---|---|---|---|---|---|---|
| LifeSnaps 3 | 36 | 36 | 0 | – | – | – | 0 |
| LifeSnaps 4 | 36 | 36 | 0 | – | – | – | 0 |
| LifeSnaps 5 | 36 | 34 | 2 | 2 | 0 | 0 | 5 |
| LifeSnaps 6 | 36 | 15 | 21 | 21 | 6 | 0 | 6 |
| LifeSnaps 9 | 36 | 12 | 24 | 24 | 13 | 1 | 9 |
| LifeSnaps 11 | 36 | 2 | 34 | 33 | 11 | 7 | 11 |
| LifeSnaps 13 | 36 | 2 | 34 | 34 | 7 | 7 | 13 |
| PMData 1 | 17 | 17 | 0 | – | – | – | 0 |
| PMData 4 | 17 | 17 | 0 | – | – | – | 0 |
| PMData 5 | 17 | 0 | 17 | 12 | 10 | 3 | 5 |
| PMData 6 | 17 | 0 | 17 | 15 | 9 | 0 | 6 |
| **All** | **320** | **171** | **149** | **141** | – | **18** | – |

(Exact figures in the results file. "Quiet" is the pre-registered definition: no section changed
and no priority. "Partial" was 149/149, since physical stress signs never had readings in these
datasets and HRV rarely did. The breakdown of withheld sections by contributor count is in the
results file, marked as added after the run.)

**What it shows:**
- **Team size alone does not decide reporting.** Overlapping, readable data does:
  - LifeSnaps 5 reported in only 2 of 36 weeks, because its people joined the study months apart;
    PMData 5 reported in all 17.
  - Teams of 1, 3 and 4 were withheld every week, as designed.
- **The 4-to-5 boundary occurs naturally**, metric by metric. In 18 ready weeks steps could be
  reported but sleep could not.
- **Real weeks are mostly quiet:**
  - 9 changed sections in 1,341;
  - 2 priorities in 149 ready weeks;
  - 0 cases with more than one priority, so **a live model would never have chosen anything**.
- **Recompute:** time asleep, steps and resting heart rate, recomputed independently from the
  source files with the standard library, agree **134/134** (median and member count).
- **Objective checks: 149/149** for both the coach's briefing and the fixed-order report. The
  checks: numbers match evidence, references exist, evidence for the week, no causal wording, no
  member named, every figure from at least 5 people.
- **Briefings:** one for every ready report (149/149), and none for a withheld one (171/171).

**What the coach adds over the fixed-order report, measured:**
- On these 149 real cases, the briefing is the report's priorities in code order, plus nothing.
  It is the same deterministic path, with the same checks passing.
- The model was never reached.
- The coach's added value is the **calendar line and the playbook suggestion**. Neither can appear
  without calendar data, and only the synthetic demo team has it.
- **So the comparison that matters is still to be scored:** whether the highlighted finding and
  the suggested action are the right ones. That is the relevance and action rubric, with the
  doctors (below).
- The reserved teams (LifeSnaps 6 and 13, PMData 5 and 6) are kept for it.
- **Live-model consistency is not measured:** no real case reached the model. Measuring it would
  need multi-priority cases, which only synthetic data supplies.

## Coverage matrix

**Levels:**
- **C** (component): a calculation or rule on its own.
- **S** (step): one decision.
- **T** (trajectory): a sequence with state, such as approve before write or one write on retry.
- **E** (end to end): from the user's surface to the final state.

**Verdicts:**
- ✅ verified;
- ◐ partly verified;
- ❌ failed;
- ○ untested.

| # | Claim | Lvl | Evidence (test or run, revision) | What it asserts | Result | Verdict | Gap and risk |
|---|---|---|---|---|---|---|---|
| 1 | A team figure is the median of members' own week-minus-usual changes | C | `test_team_stats` (boundary fixture), varied-teams recompute | hand-calculated medians; independent recompute from source files | 1/1; 134/134 | ✅ | recompute covers 3 of 9 metrics |
| 2 | No figure from fewer than 5 people, per metric | C | `test_fewer_than_five_people_give_no_figures_at_all`, boundary fixture, `test_a_metric_with_too_few_readings_is_left_out_alone`; varied teams | withheld metric has no stats; other metrics still reported | pass; 149/149 reports | ✅ | — |
| 3 | Missing stays missing, never zero | C | boundary fixture; `real_data.NEVER_ZERO` | a missing night adds no contributor | pass | ✅ | — |
| 4 | False alarms stay near alpha | C | `test_false_alarms_stay_near_alpha_when_nothing_changed` | rate over many seeds | pass | ✅ | synthetic noise only |
| 5 | The report's text matches its evidence | S | `test_a_report_holds_aggregates_with_every_figure_from_its_evidence`; varied teams | numbers and counts in each sentence | pass; 149/149 | ✅ | — |
| 6 | **The baseline a sentence names is the one its figure used** | S | read by hand, 2026-11-26 | — | priority lines say "against the four weeks before" for a fixed baseline 7 to 4 weeks back | **❌** | **wrong finding wording, on the production demo; fix proposed below** |
| 7 | A lasting change is found and said to be lasting | C | `test_a_lasting_drop_in_sleep_is_found_and_said_to_be_lasting`, `test_a_lasting_change_is_not_absorbed_by_its_own_baseline` | planted 3-week drop | pass | ✅ | — |
| 8 | Briefing: once a week, never for a withheld report | T | `test_once_a_week_and_never_for_a_withheld_report`; varied teams | — | pass; 149/149, 171/171 | ✅ | — |
| 9 | Briefing never says "no change" beside its own finding | S | `test_beside_a_finding_of_the_briefing_it_never_says_nothing_changed` (#254) | — | pass; seen fixed on production | ✅ | found in production first (historical failure) |
| 10 | Calendar line: "in the same week", never a cause; quiet weeks stay quiet | S | `test_coach` (200 made-up teams) | 0/200 quiet mentioned, 200/200 busy | pass | ✅ | synthetic calendars only |
| 11 | The suggestion targets the calendar signal that fired | S | `test_the_calendar_signal_picks_the_change_that_targets_it` | — | pass | ◐ | appropriateness unrated (doctors' rubric) |
| 12 | Nothing is suggested without a reason | S | `test_nothing_is_suggested_without_a_reason` | — | pass | ✅ | — |
| 13 | A suggestion waits for approval; a decision is made once | T | `test_a_proposal_waits_for_approval_and_then_reaches_every_member`, `test_a_decision_is_made_once` | approve before write; retry leaves one | pass | ✅ | through the retired agent's path; the app's approve route is covered by `test_team_changes` |
| 14 | Whether a change was followed is read from the calendar | C | `test_a_meeting_free_day_*` (#251), `test_the_calendar_shows_whether_a_change_was_followed` | moved vs shorter meetings; already-kept counts | pass | ✅ | holidays not marked out of office count as free |
| 15 | An ended change says how the team went | T | `test_an_ended_change_says_how_the_team_went_during_it` | — | pass | ◐ | no real before/after: datasets have no actions |
| 16 | Only a team's supervisor reads it; consent before joining; leaving withdraws | C/T | `test_teams` (4 tests), `test_privacy_isolation` | — | pass | ✅ | — |
| 17 | Check-in: only who agreed, told first, exact hour, no double send, demoted/former HR get nothing, no model | T | `test_checkin` (6 tests) | — | pass | ✅ | real detection 31–53% (`current.md`) |
| 18 | HR invitation: current contact stays until accept; expiry; no conversion | T | `test_hr_invite` (3), `test_hr_invite_postgres` | — | pass | ✅ | — |
| 19 | Calendar: own sign-in, rows never mixed with health, failures contained | C/T | `test_calendar` (4) | — | pass | ✅ | — |
| 20 | MCP: auth, roles, refusals, OAuth | S/T | `test_mcp`, `test_mcp_oauth`; red team 48/48 at `e95c832` | — | pass | ✅ | no production sign-in from claude.ai or Codex; no Codex tool call |
| 21 | Notes with a named health or absence remark are refused | C | `test_note_screen` | — | **6 xfail** | **❌** | **#246, open: could expose a person** |
| 22 | Same figures in dataset, report and MCP | E | `eval/team_three_way.py` at `46d6c4d` | one team-week | 6/6 | ◐ | one week only |
| 23 | Check-in and report scenarios through the API | E | `eval/team_e2e.py` at `46d6c4d` | 18 scenarios | 18/18 | ✅ | — |
| 24 | Supervisor flow in the app: finding → evidence → approve → saved | E | rehearsal on production (pending); `mobile` evidence and team-briefing unit tests | — | not run end to end | ○ | **no scripted UI run; rehearsal and a Playwright pass needed** |
| 25 | Personal features off; team routes stay | C | `test_personal_features` | — | pass | ✅ | — |
| 26 | Deleting an account deletes everything about the person | C | `test_account_deletion` | — | pass | ✅ | — |
| 27 | Demo teams: labelled, removed by recorded ids only | T | `test_team_demo`; throwaway PostgreSQL run; production rebuild | — | pass; removed 8 → 0, recreated | ✅ | — |
| 28 | Errors reach Sentry without personal data; metrics name nobody | C | `test_observability`, `test_prometheus` | — | pass | ✅ | — |
| 29 | Monitoring: errors, latency, spend, sync failures alert | E | Grafana alerts (10) in `monitoring/grafana/provisioning/alerting/patterns.yml` | defined | not fired in a test | ◐ | **no metric for weekly reports made or withheld, or for briefing failures** |

## The seven scenario categories

Each category has at least one executable case with a pass criterion. All of them ran on
2026-11-26.

| Category | Case | Levels | Pass criterion | Result |
|---|---|---|---|---|
| Normal | Varied teams, 149 ready real team-weeks | C, S, E (report) | every objective check passes; independent recompute agrees | 149/149; 134/134 ✅ |
| Edge | Exactly 4 vs 5 contributors per metric (hand-calculated fixture); teams of 1, 3, 4 | C | the metric is withheld at 4 with no stats, reported at 5 with the known median; small teams withheld every week | pass; 106/106 small-team weeks withheld ✅ |
| Adversarial | MCP red-team set (48 attacks: tokens, roles, injection, oversize, rate limit) | S, T | each attack gets its exact expected refusal | 48/48 at `e95c832` ✅; note screen **6 known misses (#246)** ❌ |
| Historical failure | (a) briefing contradiction (#254); (b) meeting-free day scored by total minutes, and an already-kept day scored unfollowed (#251); (c) demo cleanup by email pattern (#252) | S, T | each regression test fails on the old code and passes on the fix | all pass; (a), (b) and the shared-prefix case of (c) shown failing on the old code ✅ |
| Ambiguous / abstain | A busier calendar with too few readings; a week not over; a request for one person's data through MCP | S | says "too few team readings to tell", refuses the unfinished week, refuses the person | pass (`test_with_no_readings_to_tell_it_says_so`, `test_reports_are_for_the_teams_supervisor_and_full_weeks_only`, `test_mcp`) ✅ |
| Long-horizon | 36 consecutive weeks per LifeSnaps team; a lasting 3-week change; an ended change measured afterwards | T | lasting found and said to be lasting; no state leaking across weeks (each week briefed on its own) | pass ✅; real before/after of an action ○ (no action data) |
| Tool failure | Calendar sync fails; note matcher outage; email provider refuses; one team's daily pass fails; briefing model fails | T, E | the report stays readable, the alert stays in the app, other teams run, the email still goes | pass (`test_a_failing_calendar_sync_is_contained`, `test_note_matcher_outage_…`, `test_a_mail_failure_…`, `test_the_daily_pass_runs_once_…`, `test_the_weekly_command_briefs_and_still_emails_…`) ✅ |

## Gaps, most important first

1. **Wrong baseline in the briefing's wording (row 6). Risk: a wrong supervisor finding.** The
   number is right for its own definition, and the production demo shows the line.
   - **Proposal:** name the baseline's dates ("against Oct 5 to Nov 1"), in the API and in the four
     app screens that say "four weeks before".
   - **To decide:** the wording, which also needs the rubric.
   - After the fix, rebuild the demo once more.
2. **#246: the note screen lets named health and absence remarks through. Risk: exposes a
   person.** Open, owner Jad. The demo uses synthetic notes only.
3. **No end-to-end UI run of the supervisor flow (row 24). Risk: an incorrect write or a wrong view
   not seen.** The production rehearsal is pending. Add a scripted browser run against the demo
   team: open finding → evidence → approve → saved decision, and the withheld team's explanation.
4. **The coach's relevance and action are unrated.** Nothing yet shows that the highlighted
   finding and the suggested action are the right ones. Needs the doctors' rubric, then scoring
   of the reserved cases by named raters.
5. **MCP on production:** no sign-in from claude.ai or Codex, and no Codex tool call.
6. **Monitoring of the weekly job:** no metric for reports made, withheld or briefed, or for
   briefing failures. The cron prints counts only.
7. **Live-model consistency** (repeat runs, latency, cost per task) is not measured for the team
   product. On real data no case reaches the model; it needs synthetic multi-priority cases.
8. **The datasets cannot establish** workplace relationships, wear time, calendar load or an
   action's effect. Every real-data claim is about readings and reporting only.
