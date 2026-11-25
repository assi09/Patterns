# Product design

What the app does for its user and the decisions behind it. [architecture.md](architecture.md)
covers how it is built. Sections marked *open* are not decided yet.

> **2026-11-25: the product is now the team** ([pivot.md](pivot.md)). Its users are a supervisor
> and the team's HR contact; members connect their data and choose what to share. The sections
> below describe the individual app as designed and built until then; it is kept in the code
> behind `FA_PERSONAL_FEATURES` (off) and tagged `v0.9-personal`.

## Screens now (since 2026-11-25)

| Who | Screens |
|---|---|
| **Member** | Today (their own data), Inbox, Settings: Google Health, Your teams (join with a code, the three consents: team figures, named weekly levels, check-in alerts), and their own check-in alert page with Send it now and Stop this alert |
| **Supervisor** | Today, **Team** (briefing, team board, weekly report, invite, the HR contact), **Check-ins**, Inbox, Settings |
| **HR contact** | **Check-ins**, Inbox, Settings, and Today; Today goes away with the HR invitation work (planned, [plan.md](plan.md)) |

## User and problem

The user wears a Fitbit (Fitbit Air) and has months of data. The Fitbit app shows daily scores and
simple charts, but answering *"why was my recovery low this week?"* or *"did training more change
my sleep?"* still means scrolling through screens and comparing numbers by hand. The app never
connects one metric to another, or the present to the user's own past.

The app answers those questions from the user's own data, and every number it shows can be traced
to a computed statistic.

## Screens of the individual app (until 2026-11-25, kept behind the flag)

| Screen | What the user does |
|---|---|
| **Welcome, sign up, sign in** | Learns what Patterns does, creates an account, and gets access through a configured pilot invitation or the owner's approval. |
| **Today** | Sees today's recovery score with its breakdown, last night's sleep, activity compared with their usual, and the morning check-in. |
| **Findings** | Reads what changed recently and why, each finding with its evidence. Answers the agent's context questions. |
| **Ask** | Asks questions about their data; answers come from the expert that owns the topic and cite evidence. |
| **Reminders** | Approves, mutes or declines reminders the agent proposes. Nothing is sent without approval. |
| **Data** | Connects their Google Health account (whole history, then kept synced), sees data coverage, picks light or dark, signs out; the owner also approves sign-ups. Takeout upload is planned. An owner handles account deletion requests through the CLI. |

<a id="agent-assisted-logging-core-planned-capability"></a>

## Agent-assisted logging

The agent helps the person record workouts and food through conversation, alongside analysing
patterns. Activity owns workout proposals; Nutrition owns food proposals. The first local
implementation supports supplied-value food/workout drafts through Auto, review/edit/confirm
cards, cancellation and undo, plus saved entries on Data. Real Google writes are off by
default; one real food entry was created and undone on 2026-10-25. Food lookup scales nutrient values to supplied grams, and workout drafts can include tracker roll-ups for their interval. Photo input remains planned.

The shared flow is **collect missing details → propose → review/edit → confirm → execute → undo**.
The agent cannot grant approval or write to Google directly. Each confirmation applies to one
specific version of a proposal; edits require confirmation again. Cancellation writes nothing.

- **Workout:** collect activity, local start time/timezone and duration/end; ask for distance when
  relevant. A deterministic tool summarises available intraday heart rate and steps over that
  window, with coverage and evidence. Missing sensor data stays missing. Do not infer distance
  from an activity name or treat a workout log as extra steps/calories to add to device totals.
- **Food with supplied values:** collect meal/time, serving and provided energy/macros; retain
  their provenance as user-entered values, not independently verified measurements.
- **Food from photos or weights:** a later phase proposes food/portion and nutrient estimates,
  clearly labelled and editable before confirmation. A weight alone does not establish nutrient
  content. Model estimates are never represented as computed statistical Evidence or precise
  measurements; deterministic arithmetic may scale a known food's values to a serving.
- **Undo:** a person can request deletion of an entry this app created; show whether Google has
  confirmed the deletion. Never silently delete or overwrite another app's entries.

Validation catches malformed units, dates and unsupported fields. Unusual but possible entries
ask for clarification rather than imposing arbitrary medical or dietary limits. Logging gives no
medical, diet or energy-balance advice. Google write access is optional and requested explicitly;
existing read-only analysis must still work without it.

Confirmed records feed subsequent analyses through the normal source-aware sync. Store Google
record IDs and reconcile write-back echoes so each record is counted once, including existing
Cronometer/Apple Health duplication. Retain whether values were sensor-derived, user-entered,
food-database-derived or model-estimated.

Build locally first. Photos remain part of the intended demo after supplied-value logging;
hydration is a later extension. Jev classifies topic and request intent, the experts prepare
drafts, and server code alone enforces approval and execution. See the task-based
[tool plan and provider findings](agent-actions.md) and
[roadmap.md](roadmap.md#agent-assisted-logging-workstream-planned).

## Personal experiments (headline agentic feature, planned)

**The problem.** People keep wondering whether a habit matters for them: does coffee after 2 pm
cost them sleep, do two rest days lift their HRV, does a late dinner lower their recovery? The
trackers answer with associations at best. WHOOP's Journal comes closest: its Behavior Insights
compare Recovery on days a logged habit was "yes" and "no" once there are at least five of each in
90 days, and say themselves that this is not causation; its "mini experiments" are a guide for the
person to run by hand. Those comparisons are confounded (people drink on weekends, train after
good nights) and nobody checks whether the result could be chance or how big an effect the data
could even detect.

**What Patterns does instead.** The agent runs the experiment *with* the person, from question to
answer, over weeks:

1. **Propose.** From a question ("does late coffee hurt my sleep?"), a finding the daily run made,
   or the agent's own suggestion after a large unexplained change. One behaviour, one main
   outcome metric (plus at most two secondary ones), stated before any data is collected.
2. **Design.** Deterministic code, not the model, sets the plan from the person's own history: a
   balanced schedule of "on" and "off" days (randomised in blocks so weekdays are spread evenly),
   the lag at which to measure (tonight's sleep, tomorrow's HRV), and how many usable days it needs
   to detect an effect worth knowing, from the metric's own day-to-day variation. If the history is
   too noisy for any sensible length, it says so instead of starting.
3. **Approve.** The person sees the plan in plain words (what to do on which days, for how long,
   what will be measured) and starts it or not. Nothing starts without approval (decision 10).
4. **Run.** Each morning after the sync the agent reminds them of the day's assignment, records
   whether they followed it (one tap, or a log entry), and checks the night: worn enough, not
   flagged sick or travelling. Days that do not count are excluded by fixed rules, and the plan is
   extended when too many are lost. A short note on Today says where the experiment stands.
5. **Answer.** At the end, the comparison runs as a deterministic tool (assigned "on" days against
   "off" days, with a randomisation test that respects the schedule, an effect size and an
   interval) and returns Evidence. The agent writes the answer from it: **"worked for you"**,
   **"no clear effect"** (with the smallest effect the experiment could have caught), or **"too
   few usable days"**. Every number links to its computation, as everywhere else.
6. **Remember.** The result becomes a finding in memory, so later answers can cite it ("your
   caffeine experiment in November found no clear effect on time asleep").

**What makes it agentic.** It is a goal pursued over weeks: the agent plans, acts (reminders and
records, with approval), observes each day, adapts the plan when days are lost, and concludes with
verified claims. A dashboard or a single chat answer cannot do that.

**Better than the commercial coaches on rigour.** Assignment is decided in advance, so the
comparison is not confounded by when people happen to do things; one main outcome is fixed
beforehand, so there is no hunting through metrics; adherence and data quality are tracked rather
than assumed; and "no clear effect" comes with what the experiment could and could not detect.

**Limits and safety.** Experiments are about everyday behaviour only (timing of caffeine, meals,
screens, bedtime, training and rest). Nothing involving medication, supplement dosing, fasting,
restriction or anything that could be risky is proposed or accepted; such requests are refused like
medical questions. Results describe the person's own data and are never advice. One experiment
runs at a time, so two cannot blur each other. The person can stop at any time; a stopped
experiment is reported with what it had, or not at all if too short.

See [architecture.md](architecture.md#experiment-runner-planned) for how it is built and
[roadmap.md](roadmap.md#personal-experiments-workstream-planned) for the plan and its evaluation.

## Morning check-in

One question each morning: **"How do you feel today?"** on a 1 to 5 scale, with optional tags
(hard training, alcohol, late meal, stress, travel, feeling sick). It takes one tap and can be
skipped or changed the same day.

- **Ground truth for the recovery score:** it is the only way to show that our score tracks how
  the user feels better than Fitbit's readiness does (see Evaluation).
- **Context for the agent:** tags explain changes the sensors cannot see (*"recovery dropped on the
  3 days after tagged hard training"*).
- **Fixed tags instead of free text:** tags carry the context without giving the model a free-text
  input to inject instructions into.

## Which data is trusted

Fitbit's metrics are used as measured, with two exceptions:

- **Calories burned** is treated as low-confidence. Experts may describe relative changes (*"about
  15% above your usual"*) but never claims built on the absolute value, such as a calorie deficit
  or surplus. The verifier rejects energy-balance claims.
- **Readiness** is not used as the recovery signal. We compute our own recovery score and show
  Fitbit's readiness next to it for comparison.

Fitbit's sleep score and readiness exist only in Takeout exports: the live Google Health API has
neither, so nothing in the app depends on them. Readiness stays useful as the comparison in the
recovery evaluation.

## Recovery score

A deterministic score from 0 to 100, modeled on the inputs Bevel uses for its recovery score.
50 means a typical day for this person.

1. **Personal baseline.** For each input, today's value is compared with the person's own recent
   history: a robust z-score against the median and spread of the previous 28 to 60 days.
2. **Direction.** Each input is signed so that positive means better than usual:

   | Input | Better when |
   |---|---|
   | HRV (RMSSD during sleep) | higher |
   | Resting heart rate | lower |
   | Respiratory rate | lower |
   | Skin temperature variation | closer to baseline, in either direction |
   | Sleep: minutes asleep and efficiency | higher |

3. **Combination.** A weighted sum, with HRV and resting heart rate weighted most, mapped to 0 to
   100. Weights are fixed in code and versioned (`recovery_v1`, ...). They are not fitted to the
   user's check-ins, because a few weeks of ratings are too few to fit weights without fitting
   noise.
4. **Breakdown.** Every score lists each input's deviation and its contribution in points, so the
   app and the agent can explain it.
5. **Missing data.** No HRV or resting heart rate from last night means no score that day, not an
   estimate. Too little history for a baseline also means no score.

## Experts

Questions are handled by a specialist that owns a set of metrics. **Only the owner makes claims
about a metric**; any expert may read other experts' metrics to explain something.

| Expert | Owns | Reads |
|---|---|---|
| **Sleep** | sleep duration, time in bed, efficiency, sleep stages, bedtime | activity, check-in tags |
| **Recovery** | recovery score and breakdown, HRV, resting heart rate, respiratory rate, skin temperature, Fitbit readiness (Takeout only, for comparison) | sleep, training load, check-ins |
| **Activity** | steps, distance, active zone minutes, activity minutes, calories burned (low-confidence); cardio load from Takeout only | recovery, sleep |
| **Nutrition** (*to build*) | intake logged in Cronometer and synced through Google Health: energy, macros and 34 nutrients | sleep, activity |

Wear time and data coverage are shared: every expert must account for low-wear days.

## Routing

A fast classifier (Jev, a typed decision model) answers two things about each question, in one
call. Its **topic**: a probability for each of sleep, recovery, activity, nutrition, general and
out of scope. And, separately for each expert, whether answering **needs** that expert's data
(yes/no, as a probability). A single topic distribution cannot mark a question as cross-domain: its
spare probability is uncertainty, not a second topic. Code decides what to do with the answers:

- **Clear topic:** that expert leads.
- **Needs other experts' data** (a cross-domain question such as *"did my late nights hurt my
  recovery?"*): the lead consults those experts as tools; one answer, one owner, verified once.
  **Consulting is the router's decision**, not the depth's and not the lead's.
- **Low confidence:** the general agent answers.
- **Out of scope** (medical questions, requests unrelated to the user's data): refused without
  calling the LLM.

Only the question text is sent to the classifier, never the user's data. If it fails or times out,
a keyword rule over metric names routes the question instead.

## Asking a question

The Ask screen opens as an empty page with a compact input; the conversation takes over once the
first message is sent. The input has three controls:

- **Expert:** *Auto* by default, which routes as above. A user who already knows the topic can pick
  an expert, and the question goes straight to it. The scope check still runs on every message,
  so picking an expert cannot get around the refusal of medical questions, and the router still
  decides which other experts it consults. Nutrition is listed but disabled until nutrition data
  exists.
- **Depth:** *Quick* (the default) gives the expert a small tool budget; *Deep* lets it test more
  windows. Consults the router allows add their own budget at either depth. This is the latency
  and cost trade-off made visible, and both settings are measured in the evaluation.
- **Attach:** a recent finding or a metric, shown above the input, which decides the topic: its
  owner leads unless the user picked an expert, and an attached finding's evidence can be cited.

Every answer says which expert gave it, whether the router or the user chose that expert, and
which experts it consulted.

## What the agent may do, and what it asks first

- **Explain:** findings and answers, every number from a tool, every claim verified.
- **Ask, when it is worth it:** only about a change that is large, lasting and still unexplained
  after the agent tested its hypotheses. Questions are short and multiple choice, always with
  "rather not say" and a skip; never about feelings or personal difficulties. A dismissed
  question is not asked again, and the agent backs off after dismissals.
- **Remember, leanly:** context answers, past findings, check-ins and preferences, stored as short
  structured facts; only facts relevant to the current question are loaded, and facts that never
  matter fade out. New facts the agent wants to keep are confirmed by the user first.
- **Propose reminders** and **personal experiments** (for example "no coffee after 2 pm on
  alternate days for three weeks"): the agent designs, tracks and analyses an accepted experiment;
  see [Personal experiments](#personal-experiments-headline-agentic-feature-planned).

Any user must approve before a reminder is scheduled, an experiment starts, a new fact is saved
to memory, or data is deleted.

All four experts (sleep, recovery, activity, nutrition) are part of the demo.

## Rules for every answer

- Numbers come from deterministic tools; the model only chooses what to compute and writes text
  that cites evidence.
- Nothing medical: no diagnosis, condition, treatment, medication, supplements, diets or "see a
  doctor". The app describes patterns in the user's own data and coaches everyday habits.
- **Coaching (since 2026-10-28):** asked how to improve, the agent suggests at most two everyday
  habits (bedtime and schedule, wind-down, evening screens or caffeine timing, naps, training load
  and rest, movement breaks), each a claim of kind `suggestion` that must cite a real pattern in
  the person's own data and be worded as an option; it then offers a reminder or a test. With no
  pattern to stand on, it says so and offers a test instead of generic tips. The advice guard
  flags only medical sentences.
- A claim the verifier cannot match to evidence is repaired once, then dropped.

## Evaluation tied to these decisions

- **Recovery score:** rank correlation of our score and of Fitbit readiness with the morning
  check-in over the same days, and the days where the two disagree most. With one or two people
  and a few weeks of data this is a pilot comparison, and is reported as such.
- **Routing:** accuracy, latency and cost of Jev against an LLM router and the keyword rule, on a
  labeled set of questions.
- **Experts:** the same evaluation suite run on the expert system and on a single general agent,
  to show whether the split is worth it.

<a id="teams-planned"></a>

## Teams

A supervisor can invite employees into a team and receives a weekly report on the team's
patterns: aggregates of each member's change against their own baseline, never anyone's own
values, and nothing built from fewer than 5 people. Employees join with a code after a consent
screen and can leave at any time. Separately, each person may opt in to showing the supervisor
their own weekly recovery, sleep, strain and stress levels, against their own baseline. See
[teams.md](teams.md) and, for the two new scores, [scores.md](scores.md).

## Open

- **Nutrition:** which daily nutrient columns to keep, and how to avoid counting Cronometer's daily
  total and its per-entry Apple Health copies twice (both arrive through the API). Takeout exports
  carry no nutrient values at all.
- **When the agent runs:** after each upload, on a schedule, or on demand.
- **History:** whether past reports and findings are browsable, or only the latest.

## Recorded routes and regions (optional, planned)

An extra after the logging flow: show where GPS-recorded walks/runs happened, or coarse map
regions, using Google Health exercise routes. This is not a reconstruction of every daily step.
A daily count alone carries no location. Fitbit Air uses the phone's connected GPS during
recorded exercise; without recorded coordinates the app must show location as unavailable.

Google exposes route coordinates through `exportExerciseTcx` (TCX), with separate
`googlehealth.location.readonly` consent in addition to activity access. The existing app does
not request this permission or sync routes. Start with recorded workout routes; only show step
counts for a route/region when the recorded session or a valid time-aligned step stream supports
that attribution. Keep the unlocated remainder explicit, and never distribute a daily total
across map regions by guessing.

Keep this optional and separate from the core agent milestone. Prefer coarse regions initially;
precise coordinates stay out of prompts and traces. Do not add continuous phone tracking or a
geocoding provider as part of this proposal. Validate GPS availability, gaps, denied permission,
time alignment and per-user access before implementing map UI.

Sources checked 2026-10-24: [Google workout routes](https://developers.google.com/health/data-types/workouts),
[TCX export](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/exportExerciseTcx),
[Fitbit Air connected GPS](https://support.google.com/googlehealth/answer/14225688?hl=en).
