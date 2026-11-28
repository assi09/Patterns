# Weekly team metric explorer

A supervisor chooses a finished week, browses every team metric the live sync supports, and opens
any one for its evidence, including metrics the weekly report and briefing did not highlight.
MCP's `team_metrics` and `team_metric` tools return the same results with the same evidence ids.
Code: `backend/app/teams/explorer.py`. Tests: `backend/tests/test_team_metric_explorer.py`.

## 1. What production syncs (traced 2026-11-28)

The live path, verified against the code on this branch:

1. **Schedule.** The API process runs `app.background`, which calls `start_due_syncs`. Google
   Health is pulled for each connected person every 3 hours (`SYNC_EVERY`); Google Calendar
   every 30 minutes.
2. **Range.** `app.sync.connections.plan` pulls from the day after the last stored live day to
   today. It also rereads the last 3 days (`RESYNC_DAYS`) on every sync. A first sync goes back
   up to 5 years in 120-day chunks.
3. **Parsing.** `app.sync.pull.pull` calls `app.sync.daily.load_daily(health, start, end)`.
4. **Storage.** `app.db.daily.save_daily(session, user_id, "google_health", frame)` rewrites
   whole days for that source only. A `DailyMetric` row is (user, source, day, metric, value)
   and has no sync time.
5. **Team reads.** `app.teams.reports.member_frames` loads each current member's
   `google_health` days only (`reports.SOURCE`). `app.analysis.team.prepare` then adds Patterns'
   scores and blanks activity on days worn under 10 hours (`screen.without_low_wear`).

`docs/metrics.md` ("From the Google Health API") matches the code in every row checked. The
data types read are:

- daily roll-ups: `steps`, `distance`, `total-calories`, `active-zone-minutes`,
  `active-minutes`, `time-in-heart-rate-zone`;
- points: `daily-resting-heart-rate`, `daily-heart-rate-variability`,
  `daily-respiratory-rate`, `daily-sleep-temperature-derivations`, `sleep`, `activity-level`;
- 60-second `heart-rate` roll-ups over still minutes.

### Inventory: category → subgroup → metric

"Weekly" asks whether the synced data supports a weekly team comparison. **Shipped** means the
metric is in the explorer's first version.

**Sleep.** Main sleep only (the longest main sleep of a night), dated by the local day it ended.

| Subgroup | Metric (column) | Live field, unit | Stored or derived | Zero vs. missing | Weekly | Shipped |
|---|---|---|---|---|---|---|
| Duration | Time asleep (`sleep_minutes`) | `sleep.summary.minutesAsleep`, min | stored as read | a night without main sleep is missing | yes | yes |
| Duration | Time in bed (`time_in_bed`) | `sleep.interval` end − start, min | derived by Patterns | as above | yes | yes |
| Timing | Bedtime (`bedtime_hour`) | `sleep.interval.startTime` + `startUtcOffset` | derived: hours from local midnight, shown as a change in minutes (later is +) | as above | yes | yes |
| Stages | Deep, light, REM, awake in bed (`*_sleep_minutes`, `awake_in_bed_minutes`) | `sleep.summary.stagesSummary[type].minutes`, min | stored as read, only when `sleep.type == "STAGES"` | a CLASSIC night, or a stage absent from the summary, is **missing**, never 0 | yes; coverage is lower than for time asleep | yes |
| Efficiency | Sleep efficiency (`sleep_efficiency`) | none in the API | **Patterns-calculated**: `round(100 × minutesAsleep / time in bed)`; the change is in percentage points | missing without minutes asleep or with no time in bed | yes | yes |

**Movement.** Activity values are blanked on days worn under 10 hours.

| Subgroup | Metric (column) | Live field, unit | Stored or derived | Zero vs. missing | Weekly | Shipped |
|---|---|---|---|---|---|---|
| Totals | Steps (`steps`) | `steps` roll-up `countSum`, steps | stored | a day without a roll-up value is missing | yes | yes |
| Totals | Distance (`distance_km`) | `distance` roll-up `millimetersSum`, mm | stored ÷ 10⁶, km | as above | yes | yes |
| Totals | Calories burned (`calories`) | `total-calories` roll-up `kcalSum`, kcal (includes resting burn) | stored | as above | yes | yes |
| Activity intensity | Light, moderate, vigorous (`lightly_`, `moderately_`, `very_active_minutes`) | `active-minutes` roll-up by level `LIGHT`, `MODERATE`, `VIGOROUS`, min | stored | a level absent from a day's point is a **real 0**; a day without a point is missing | yes | yes |

**Heart.**

| Subgroup | Metric (column) | Live field, unit | Stored or derived | Zero vs. missing | Weekly | Shipped |
|---|---|---|---|---|---|---|
| Time in heart-rate zones | Below fat burn, fat burn, cardio, peak (`hr_zone_light_`, `_moderate_`, `_vigorous_`, `_peak_minutes`) | `time-in-heart-rate-zone` roll-up, zone `duration` s | stored ÷ 60: **actual minutes**, each counted once | a zone not reached on a day with a point is a **real 0**; a day without a point, or barely worn, is missing | yes | yes |
| Active Zone Minutes | Active Zone Minutes, weighted (`active_zone_minutes`) | `active-zone-minutes` roll-up: fat burn + cardio + peak sums; the API's cardio and peak sums already count double | stored | 0 when any sum is present; a point with **no** sum is missing (see gaps) | yes | yes |
| Resting and overnight | Resting heart rate (`resting_hr`) | `daily-resting-heart-rate.beatsPerMinute`, bpm | stored | missing without a reading | yes | yes |
| Resting and overnight | Heart rate variability (`hrv_ms`) | `daily-heart-rate-variability` (RMSSD during sleep), ms | stored | as above | yes | yes |
| Resting and overnight | Breathing rate (`respiratory_rate`) | `daily-respiratory-rate`, breaths/min | stored | as above | yes | **no**: not in the first set |
| Resting and overnight | Skin temperature (`skin_temp_variation_c`) | `daily-sleep-temperature-derivations`: nightly − baseline, °C | derived | missing until a baseline exists | yes | **no**: not in the first set |

**Scores.** These are existing team metrics, each computed by Patterns from live inputs.

| Subgroup | Metric (column) | Live inputs | Zero vs. missing | Weekly | Shipped |
|---|---|---|---|---|---|
| Patterns scores | Recovery (`recovery_score`, 0-100) | HRV, resting heart rate, time asleep (2 of 3 needed) | missing without enough inputs | yes | yes |
| Patterns scores | Strain (`strain`, 0-21) | heart-rate zone minutes, or AZM on a day without zones | as above | yes | yes |
| Patterns scores | Stress (`stress_score`, 0-100) | still minutes and their heart rate (from `activity-level` and `heart-rate`), HRV, resting heart rate, time asleep | missing under 4 still, awake hours | yes | yes |

**Synced but used only as an input or a quality signal** (not shipped):

- `wear_minutes`, from `activity-level` intervals;
- `still_minutes` and `still_hr_above_resting`, inputs of the stress score.

### Excluded, with the reason

| What | Why |
|---|---|
| `cardio_load`, `readiness`, `sleep_score`, `sedentary_minutes` | not in the API (`NOT_IN_API`); Takeout only |
| Fitbit's own sleep efficiency | Takeout only; the live figure is Patterns' own |
| Nutrition, water, weight, logged food and workouts | manual logs, not live device data; workouts are not daily metrics |
| SpO2, intraday heart rate as a metric, `sedentary-period`, floors, exercise sessions | advertised by Google but not ingested by the production sync (no new endpoints in this PR) |
| Breathing rate, skin temperature | synced and verified, but outside the first set asked for; candidates for a follow-up |

### Gaps, flagged separately

- **AZM on a day without zone minutes.** The parser stores 0 only when the roll-up carries at
  least one sum. If Google omits all three sums on such a day, the day is stored as missing, not
  0. No real response in this PR showed which Google does. The explorer says so in the metric's
  zero/missing note.
- **Late days.** Each sync rereads the last 3 days, and figures are made on the Monday after the
  week. A Sunday synced on Tuesday may therefore be absent from figures already made. The weekly
  report has the same timing.
- **Demo rows under the live source.** Locally, 6 people's `google_health` rows include
  `readiness`, `cardio_load`, `sedentary_minutes` and `sleep_score`. The live parser cannot
  produce these, so the synthetic and demo generators write under the live source label. The
  explorer never lists those columns, but such rows are not live data. Demo teams on production
  work the same way.

## 2. The calculation

For each metric, separately:

- **Eligible member:** at least 4 days of the metric in the week and 14 in the 28 days before.
  These are the report's coverage rules (`MIN_WEEK_DAYS`, `MIN_BASELINE_DAYS`).
- **Member's change:** the week's mean minus the mean of the member's own 28 days before
  (`app.analysis.team.member_raw_change`).
- **Figure:** the median of eligible members' changes, if at least 5 people qualify
  (`MIN_MEMBERS`; `team_metric_change`). Otherwise the metric is **withheld** ("4 of the 5 people
  needed"), or **unavailable** if no one qualifies. Neither state is ever shown as 0.
- **Coverage is per metric.** A team can have a time-asleep figure from 7 people while REM is
  withheld because only 4 have staged nights.
- **No spread is required.** The report's standardized change needs one, but a member whose
  peak-zone minutes were a genuine 0 every day still counts here, with a change of 0. For the
  report's metrics, the explorer's median can therefore include a member the report's test left
  out.
- **What is shown:** the median, the counts higher, lower and unchanged, and the contributors.
  There are no quartiles and no person's value. With 5 people, quartiles sit next to single
  people's values.
- **Unchanged report and briefing.** `TEAM_METRICS`, `team_statistics`, `build_report` and the
  briefing are untouched. An explorer figure is never tested, never adjusted and never a
  headline candidate.

### Storage, evidence ids and history

Evidence ids are random, so the app and MCP can share one only by reading one stored record.

- A team week's figures are computed once and stored in `team_metric_weeks` (migration 0042),
  with `made_at`. They are made by the weekly job right after the report, or on the first request
  for a finished week.
- **Whose figures.** A week's figures describe the people in the team when that week's report
  was made (`TeamReport.created_at`, the cutoff), less anyone who has left since. Membership rows
  keep their join and leave times (a rejoin is a new row), so that roster is on record. Someone
  who joined after the cutoff never counts, however much earlier data they bring. Someone who
  withdrew is left out of any snapshot made after they left. The roster stored is the count at
  the cutoff; the contributors are those eligible now with enough data.
- **No report, no roster.** A week without a report has no record of who belonged then, so it gets
  an explicit `roster_unavailable` state and nothing is stored. The weekly job makes the report
  first, then the figures, so a regular week always has both. A report made late for an old week
  uses the roster at the time it is made, as the report itself does.
- A stored week is never recomputed. A later sync cannot change a figure already shown.
- Every window ends on the week's last day, so nothing after the week is read.
- `as_of` (MCP) returns only figures stored by that day. With nothing stored by then the answer
  is "not available", and nothing is made from days synced since.
- A week in progress has no figures (`week_not_over`).
- A paused team (overlapping teams) gets no figures (`paused`), and they are not stored.
- Access is limited to the supervisor's own team. Another team, or an unknown metric, is not
  found. A member is not a supervisor.

## 3. App and MCP

- **App.** The Team screen's "Weekly report" part has **View all team metrics**. It opens
  `/team-metrics` at the week being viewed, with week choices, category tabs (All, Sleep,
  Movement, Heart, Scores) and rows grouped by subgroup. A row opens `/team-metric`, which shows
  the change and its unit, the week and comparison dates, contributors and roster, the method,
  the zero/missing rule, the derivation, limits, and the evidence id.
- **API.**
  - `GET /teams/{id}/metrics?week=` (`schemas.TeamMetrics`);
  - `GET /teams/{id}/metrics/{week}/{metric}` (`schemas.TeamMetricEvidence`).
- **MCP.**
  - `team_metrics(team_id, week?, as_of?)`;
  - `team_metric(team_id, metric, week?, as_of?)`.

  Each returns the dict the API serializes, built by the same function.

## 4. Verification

**With API-shaped fixtures** (`tests/test_team_metric_explorer.py`): made-up Google Health
responses go through `pull` (`load_daily` then `save_daily`), and the figures come back through
the app API and MCP. Every expected value is worked out by hand in the test:

- The report headlines time asleep (median −60 min), and REM is absent from it. REM is
  +20 min from 5 people, with the same evidence id in the app and MCP.
- 5 qualifying members give a figure. 4 withhold it, while the same team's time-asleep figure
  stands.
- Classic nights leave stages missing. Unreached peak-zone minutes are stored as 0 and give a
  figure of 0 from 7 people.
- Cardio-zone actual minutes go +10 while weighted AZM goes +20.
- Patterns' sleep efficiency comes out at −13 points.
- Takeout-only members give no figure, and Takeout REM does not fill classic nights.
- Another supervisor's team is not found.
- A later sync, the following week's data, an earlier `as_of`, and the week in progress reveal
  nothing.
- **Roster (after review).** Each case is opened for the first time through the app, then MCP,
  and the reverse:
  - four people at the report and a fifth joining later with qualifying earlier data: withheld
    from 4 in both;
  - five at the report: −58 min from 5, with the same evidence id in both;
  - one of five leaving after the report: withheld from 4, roster 5;
  - one of five leaving and a replacement joining, so the team still has 5: withheld from 4 in
    both;
  - no report for the week: `roster_unavailable` in both, and nothing stored.

  Without the fix, the late-joiner and replacement cases show a figure from 5.

**On a real live connection:** nothing in this PR. The local Google sign-in expired (Testing
mode, 7 days), and local `google_health` rows include synthetic demo data (see gaps), so they
were not used as evidence.
