# Teams: a weekly report for a supervisor

A supervisor (a manager, a department head) invites a group of employees into a **team**. Every
week the system writes the supervisor a report on how the team's sleep, activity and recovery
changed, from the members' own data. The supervisor has their own view in the app; they need no
Fitbit, and if they have one they connect it like anyone else.

This sends health data toward an employer, so the design starts from what the supervisor may
**not** see. There are two layers. Joining a team shares only team aggregates. Showing your own
named levels is a separate switch that each person turns on and off themselves. Status: roles,
teams, joining, leaving, the levels switch, team statistics, weekly reports (templated or
model-written, checked), the app screens and the weekly email are built; the Monday schedule
comes with deployment.

## What the supervisor sees, and what they never see

| Sees | Never sees |
|---|---|
| The team's name, invite code and number of active members | Who joined or left, or who has not opted in |
| Weekly aggregates across members: median change per metric, how many moved up and down, a weekday pattern, the evidence behind each | A team figure built from fewer than 5 people |
| Which metrics had too little data to report | Anyone's daily values, other metrics, workouts, chats, check-ins or findings |
| **Only for people who opted in:** their name and this week's recovery, sleep, strain and stress, each as a level against their own baseline plus the week's average | Any named data about someone who has not opted in, or after they switch it off |

- **Minimum group of 5.** A figure is shown only if at least 5 members contributed to it; a metric
  with fewer is listed as "not enough data". With fewer than 5 active members no report is made.
- **Aggregates only, everywhere else.** Member ids and per-person values never enter team
  evidence records, the model's prompt, the report text or the email. Evidence holds counts,
  medians, quartiles and p values. Named levels appear only in the supervisor's view in the app,
  as a table, and the agent never writes about named people.
- **No medical or employment judgments.** The report describes patterns in the team's data; it
  does not diagnose, rank people, or suggest decisions about anyone. Wording stays neutral
  ("time asleep fell", not "the team is exhausted").

## Joining and leaving

1. The owner of the app marks an account as a supervisor: **Approve as supervisor** in Settings
   → Access requests, or `python -m app.auth set-role <email> supervisor` for an account already
   approved (`member` takes it back).
2. The supervisor creates a team and gets an invite code, which they can rotate at any time.
3. An employee enters the code in Settings and reads a consent screen: what is shared (weekly
   team aggregates with at least 5 people, no names, no daily values), with whom, and how to
   leave. Nothing is shared until they confirm.
4. **Named levels are a second, separate switch** ("Show my weekly levels to <supervisor>"),
   off by default, with its own consent screen. The screen shows exactly the row the supervisor
   would see. Not opting in changes nothing else: the person still counts in team aggregates.
5. Settings lists every team the person shares with, the switch, and a Leave button. Leaving
   takes effect from the next report; reports already made keep their aggregates, which identify
   no one, but named levels of someone who left or switched off are no longer shown, even for
   past weeks.

Creating a team, joining, leaving, switching named levels on or off and code rotation are written
to `team_events`, an append-only log of who did what and when (no health data). Every time a
supervisor opens named levels will be logged there too, with the report screens. Both consent
texts are versioned in `backend/app/teams/memberships.py`; each membership records the versions
the person agreed to.

## The API (built)

| Who | Endpoint | What |
|---|---|---|
| Supervisor | `POST /teams`, `GET /teams`, `GET /teams/{id}` | create a team; list and read one's own teams (name, code, a count of members) |
| Supervisor | `POST /teams/{id}/invite-code` | a new code; the old one stops working, members stay |
| Anyone approved | `POST /teams/preview` `{code}` | the team, its supervisor and the consent text, before agreeing |
| Anyone approved | `POST /teams/join` `{code, consentVersion}` | joins; refused if the version is not the current one, so the text was read |
| Member | `GET /me/teams` | the person's teams, with whether their levels are shared |
| Member | `POST /me/teams/{id}/levels` `{share, consentVersion}` | the second consent; turning it on needs the current levels text's version |
| Member | `POST /me/teams/{id}/leave` | leaves, which also turns sharing off |

Another supervisor's team answers like one that does not exist. Wrong codes count like wrong
passwords: 10 in 15 minutes and the person must wait, so codes cannot be guessed. A supervisor
cannot join their own team. Codes are 8 characters without look-alikes (0/O, 1/I/L).

## How the numbers are made

All deterministic, in `backend/app/analysis/team.py` (built); the language model computes nothing.

1. **The week** runs Monday to Sunday, against the 28 days before it.
2. **Each member on their own history.** A member's days come from one source, as everywhere
   else, with the app's scores added and activity left out on barely worn days. For each metric
   (time asleep, bedtime, steps, Active Zone Minutes, resting heart rate, HRV, recovery, strain,
   stress): the week's mean minus the mean of the 28 days before, and the same in units of the
   person's own spread over those 28 days. A member counts for a metric with at least 4 days of
   the week and 14 of the 28; otherwise they are left out of that metric, not guessed.
3. **Only changes are pooled.** People differ in device, baseline and habits, so raw values from
   different people are never averaged; each person's *change* against their own baseline is.
4. **Team change per metric.** A one-sample t-test of whether the members' changes, in their own
   units, are centred on zero; so one person with a wide spread cannot decide the team. (A rank
   test was planned, but with 5 people its smallest possible p-value is 0.0625: a small team
   could never show a change.) The report shows the median change in the metric's units, its
   quartiles and the counts up and down. Benjamini-Hochberg across metrics, as in the personal
   screen; a change is reported at an adjusted p below 0.05.
5. **Weekday pattern** (sleep, steps, stress), descriptive only: each member's deviation from
   their own mean over the five weeks, by weekday, and the median across members.
6. **Privacy floor:** with fewer than 5 active members there are no figures at all; a metric with
   fewer than 5 contributors carries only its count, no median and no counts up or down; a
   weekday with fewer than 5 is left out.

Tests, over hundreds of made-up teams whose members each have their own level, spread and
day-to-day carry-over:

| Check | Result (1000 or 500 teams) |
|---|---|
| False alarms when nothing changed, at the 5% level | 5.9% with 5 members, 3.4% with 8, 3.9% with 20 |
| A whole-team shift of 1 SD found | 79% with 5 members, 97% with 8 |
| A shift of 0.5 SD found | 64% with 10 members, 93% with 20 |

Plus: one person's raw scale does not decide the team, a planted drop in sleep across 8
synthetic members is reported, and nothing below 5 people carries figures.

## Named weekly levels (opt-in)

For each person who opted in, the Team tab shows one row for the past week:

| Score | Weekly value | Level |
|---|---|---|
| Recovery | mean of the daily [recovery score](product.md#recovery-score) | below / usual / above |
| Sleep | mean time asleep | below / usual / above |
| Strain | mean daily [strain](scores.md) | below / usual / above |
| Stress | mean daily [stress](scores.md) | below / usual / above |

- **Each level is measured against the person's own previous four weeks.** "Usual" is the middle
  half of their weekly means (the same idea as Today's usual range), so a level says "unusual for
  them" and never compares people; at least three earlier weeks with 4 days are needed. Rows are
  listed alphabetically, never ranked. Computed by `member_levels` (built).
- A score with fewer than 4 days of data that week shows "not enough data" instead of a level.
- Weekly values only, no days, and only these four scores.
- The person sees their own row in Settings, exactly as the supervisor sees it.

## The weekly report

**Built so far** (`backend/app/teams/reports.py`, table `team_reports`, migration 0010):

- `python -m app.teams weekly [--week <day>] [--team <id>]` makes every team's report for the
  last full week (Monday to Sunday) from each active member's live data. A team and week are made
  once, so reruns are safe; a week still in progress is refused.
- `python -m app.teams demo-members <code> [--count 6] [--sharing 3]` fills a team with made-up
  members (`demo-member-N@example.com`, data from `app.synthetic`, time asleep down an hour in the
  last full week), to try a whole report before real people join. Local databases only; the
  accounts cannot sign in; running it again replaces their data.
- A report stores a headline and one section per metric ("Time asleep fell across the team:
  median change -32 min (1 of 7 higher, 6 lower)."), a weekday line for sleep, steps and stress,
  and the aggregate evidence each sentence cites. The text is templated: every number in it is
  read from that evidence. With fewer than 5 members with data it is **withheld** and says how
  many people it had.
- Named levels are **not stored**: they are read each time the report is opened, for the members
  sharing at that moment, alphabetically, and each opening that shows any is logged as
  `levels_viewed`.
- API, supervisor only, for their own teams: `POST /teams/{id}/reports` `{week?}` (makes it if
  needed), `GET /teams/{id}/reports`, `GET /teams/{id}/reports/{any day of the week}`.

- **The model's prose** (`backend/app/teams/narrative.py`, built): with `FA_TEAM_REPORT_NARRATIVE=true`
  (or `python -m app.teams weekly --narrate`), one call, plus one repair round, writes a headline
  and paragraphs over the aggregate evidence only. Each paragraph says whether it reports a change,
  no change or a weekday pattern, about which metric, citing evidence ids. It is checked like an
  agent's claim: a change must rest on a team change that held after correction, in its
  direction; numbers, dates and metric names must come from the cited evidence; no individual
  ("one member", "she"), diagnosis or cause; every change found must be covered. On any failure
  the templated text stands, and the report records why. The prose is stored beside the figures,
  never instead of them. Cap `FA_TEAM_REPORT_CAP_USD` (default $0.02); a passing synthetic run
  cost $0.0037 ([experiments.md](experiments.md#the-weekly-team-report-written-by-a-model-2026-10-26)).

**Planned (as designed):**

- **Text.** One language-model call per team per week receives only the aggregate evidence and
  writes the narrative, citing evidence ids. The claim verifier checks every number against the
  evidence it cites. On a model error, an exceeded budget or rejected claims, a templated text
  (the same style as the personal report) is used instead.
- **Cost.** A cap of about $0.02 per team per week (`FA_TEAM_REPORT_CAP_USD`); each report stores
  its cost.
- **When.** `python -m app.teams weekly` makes every team's report for the past week; the deployed
  platform's scheduler runs it on Mondays. A team and week are made once, so reruns are safe. The
  supervisor can also ask for one on demand, rate-limited.
- **Delivery.** In the app, a Team tab for supervisors with this week's report and past weeks.
  By email, the headline, the counts and each metric's people-lower/people-higher bar, and a link
  to the app; never named levels, even for people who share them (an email is easily forwarded).
  `python -m app.teams weekly` emails each report once (`emailed_at`) to the team's report address
  or the supervisor; `--no-email` skips it. Emails go to `data/outbox/` (an .html to open and a
  .txt) unless `FA_EMAIL_BACKEND=resend`, which sends through Resend with `FA_EMAIL_API_KEY` (a
  sending-only key, in `.env` only) from `FA_EMAIL_FROM`. Without a verified domain Resend only
  delivers from `onboarding@resend.dev` to the Resend account's own address. A failed send keeps
  the report and is retried on the next run.

## Build order

Small PRs, each green and verified:

1. This document.
2. Roles, teams and memberships (migration 0009), join and leave, the team API, access-control
   tests. **Done.**
3. Strain and stress for everyone ([scores.md](scores.md)): the daily inputs at sync, the
   scores and their tests, then Strain and Stress among Today's key numbers. **Done**, and in
   Ask. This step is useful
   on its own, before any team exists.
4. Team statistics with calibration tests, and the named weekly levels behind the opt-in.
   **Done.**
5. The weekly report: templated, stored, the CLI and the API; then the language-model text with
   its checks and the templated text as fallback, with real runs on a synthetic team, logged in
   [costs.md](costs.md) and [experiments.md](experiments.md). **Done.**
6. Email: an outbox mailer for development and Resend for real sending (`app/teams/email.py`).
   **Done.** The link points at `FA_APP_URL`, so it only opens the report from elsewhere once the
   app is deployed.
7. App, employee side: join, consent, leave, the named-levels switch. **Done** (Settings ->
   Teams).
8. App, supervisor side: Team tab, report, named levels, team settings. **Done**: a Team tab
   after Today, shown to supervisors only; create a team, copy or renew the code, make last
   week's report, the headline with the checked prose and the figures, shared levels, past
   weeks. One team per supervisor in the app for now.
9. Scheduling, with the deployment.

## Next

Invite by link, participation counts, trends over weeks, "Ask about the team" for supervisors
(aggregates only, the same floor of 5), a team challenge, a verified sending domain, and a pilot
with a real team of about 10: see [plan.md](plan.md#d-teams-improved).

## Open

- A verified sending domain for Resend, so reports can reach any supervisor's address.
- Whether 5 is the right floor for a demo team; it can only go up, never down.
- Whether a supervisor can run more than one team (the model allows it; the first UI shows one).

## The Monday check across every area (built, no agent on it yet)

`team_scan` in `backend/app/analysis/team.py` looks at every team metric for the last four weeks, each
against one fixed baseline, the 28 days before those weeks, so a lasting change is not absorbed by its
own baseline. One correction covers every metric and week. A metric is **lasting** when it changed the
same way two weeks or more in a row up to the latest, and **new** after one week. `areas` groups what
moved into sleep, activity, recovery, load and stress, so several areas moving together for one team
can be seen at once. Groups are fixed (everyone with data), never chosen, so nobody can be isolated by
comparing two of them; a week with fewer than 5 contributors carries no figures.

Tests over made-up teams with all six plain metrics: under 8% of 200 teams of 8 where nothing changed
showed a lasting change, and at least 80% of 60 teams of 10 had a lasting 1.2 SD drop in sleep found.

## Alerts when the team changes (built)

`app/teams/alerts.py`, once a day after 06:00 UTC, from the background loop. Each team's last seven
full days are compared with the 28 days before. A metric is raised when it moved the same way, after
correction across metrics, in four daily checks in a row. Code writes the alert, with team figures
from at least five people; no model is involved. The supervisor gets it in the inbox and by email.
Each change is raised once, closes when it ends, and cannot return for 14 days, so there is no daily
series from which one person's day could be worked out.

Measured on made-up teams:

| Setting chosen | Result |
|---|---|
| Nothing changed, teams of 8 | an alert in 7 of 60 teams over 30 days (12%) |
| Sleep down 1.2 SD, 12 people | found in 24 of 24, typically on day 7 |
| Sleep down 1.2 SD, 8 people | found in 20 of 24, typically on day 8 |
| Sleep down 0.8 SD, 8 people | found in 10 of 24 |
| Sleep down 1.2 SD, **5 people** | found in only 4 of 24 |

A smaller team needs a bigger change, so five-person teams will rarely get an alert. Stricter settings
cut false alarms but miss far more; looser ones raised false alarms in up to 26 of 60 teams.

## What the scores can be claimed to mean

Checked against PMData's morning self-reports, each person against themselves (`eval/stress_check.py`,
`eval/results/stress_check_2026-11-10.json`; 13 to 16 people; rank correlations, medians across people):

| Team metric | Compared with | Result |
|---|---|---|
| Time asleep | Reported hours slept | 0.75, positive in 15 of 15: strong |
| Time asleep | Reported sleep quality | 0.26, positive in 14 of 15 |
| Recovery score | Reported fatigue | 0.20, positive in 13 of 14 |
| Recovery score | Reported readiness | 0.11, positive in 10 of 13: not clear |
| Strain, day before | Reported fatigue | 0.04: no link |
| **Stress score**, day before | **Reported stress** | **-0.03, positive in 4 of 13: no link** |
| One team of 16, week by week | Stress score against reported stress | -0.06 over 20 weeks: no link |

So stress is never presented as how stressed a team feels: supervisors read "physical stress signs".
(The consent text still says "stress" and is versioned, so changing it means asking members again.) Limits: one dataset of recreational athletes; the score was rebuilt without HRV and with
"no steps" standing in for Fitbit's still minutes; which end of the rating means stressed is inferred
from its link with mood.
