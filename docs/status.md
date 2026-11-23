# Project status

The working log of the project, with [plan.md](plan.md) for what is left. Updated 2026-11-23.
**For what is true now, with the revision behind every result, read [current.md](current.md)
first**; the sections below are dated and kept as they were written.

## 2026-11-23: follow-ups, checked at scale

From the Fitbit replay (`31c3ca9`) and the #195 backlog: exact missing dates (#217), "already kept"
only for the same words (#218), protected retry lengths and the message's own flags (#220),
"where did that come from?" (#221), Sentry below 3.0 so CI installs a version with its privacy
option (#222), chat recall (#223), food source, meal and nutrient edits (#225, with #229 fixing
"energy" read as food), calendar weeks and their weekdays or weekend (#228). Records: #216, #219,
#227. Not merged, with the measurement: #224, #226 and two experiment branches. An independent
bank of 191 cases worded by the large model confirmed source and recall, showed no gain for the
rest, and found a regression (the weekend dropped from heart-rate follow-ups) that calendar weeks
removed. Paid runs about $6.90 ([costs.md](costs.md)).

**PR #195 merged on 2026-11-22** (structured request interpretation: metric, operation, threshold
and dates kept apart from the statistics, persistent conversation scope, food readback, corrected
drafts, guidance variants; see [typed-requests.md](typed-requests.md)). Its final independent audit
of `910da27` ([report](independent-audit-910da27-final.md)): on the same 592 regression turns,
fully correct rose from 504 (85.1%) to 563 (95.1%); 42 of 48 newly worded turns were fully
correct; the small PHIA gate passed 24/24. It does **not** meet every original release gate: two
silent relative-period errors remain, and memory and food follow-ups are weaker. The audit cycle
ended there by decision; what is left is the [deferred backlog](pr-195-followup-issues.md).

**The pilot started on 2026-11-17**: 10 testers invited for about two weeks, all listed as Google
test users, one team with Karim as supervisor. What was built and checked for it, and what is
left, is in [progress-2026-11-17.md](progress-2026-11-17.md).

## 2026-11-22: deliverables and DevSecOps

| PR | Change |
|---|---|
| #196 | `docs/api.md`, generated from the API's own OpenAPI schema by `python -m app.api.reference` (85 operations with their access level, 42 error codes, every schema); a test fails when it drifts. README quickstart: mock app, whole stack, CI checks, evaluation |
| #197 | Expo packages brought to SDK 58's expected versions: `expo-doctor` 20/20, no high npm advisory left |
| #198 | `docker compose --profile app up --build`: Postgres, the API (the Railway image) and the web app (the Vercel export) |
| #199 | Dependabot (weekly, grouped; Expo SDK packages left alone), CodeQL (Python and TypeScript, security-extended: 0 alerts), pip-audit and npm audit (fail on high) |
| #200 | A smoke test of production after each Railway deploy (`scripts/smoke_test.sh`, no sign-in or data) |
| #201 | Coverage in CI with a floor: backend 94% (floor 92%), mobile 35% of all of `src/` (floors just under) |
| #202 | Sentry error reports for the API, off until `FA_SENTRY_DSN` is set; no message, value, body or person leaves ([monitoring.md](monitoring.md#errors-sentry)) |

Left for Karim: a Sentry project and its DSN on Railway; whether to turn on Dependabot alerts in
the repository settings; whether the course brief asks for a GitHub Project board (paused until
checked).

## Since 2026-11-11

- **Pilot ready:** traces and thumbs (#151), the pilot report (#152), account deletion (#161), the
  team screens checked on the real backend (#162). Caps on Railway: $0.50 per person a day, $5 a
  day, $50 in all.
- **The agent tuned against the course notes** (#163, #164): code names dates and refuses what the
  data cannot answer; "why" answers on real people 16 to 28 of 33.
- **Testing plan written** ([testing-plan.md](testing-plan.md), with the methods in
  [evaluation-plan.md](evaluation-plan.md)): PHIA's questions on 58 real people and on PHIA's own
  users, against three baselines, as the main benchmark for data answers (pipeline in #165, checked,
  waiting for the card); the verifier, RAG, logging and the router each tested on their own; then
  the pilot and the team feature live.

## 2026-11-16 and 17

Two days of work are logged in [progress-2026-11-17.md](progress-2026-11-17.md): Today and the Team
tab redesigned (#166, #167), the team agent's own Monday briefing (#169, live from 2026-11-23) and
its warning before a noted crunch (#173), meal logging and corrections fixed (#171), and the
evaluation: **PHIA held-out batch 97.0%** on real people (single agent 92.3%, chatbot 69.1%), the
router 98.7% on held-out questions, food matching 22 of 25 held out, retrieval recall@3 0.94, the
verifier catching 2,117 of 2,118 broken claims. That page says which results are final and what is
left.

## Where we are (2026-11-11)

**Presentations are on 2026-12-05.** Our own finish target stays 2026-11-23, with the time after it
as buffer. What is left, what still has to be tested and the order of work are in
[plan.md](plan.md#where-we-are-and-what-is-left-2026-11-11).

**Done since the plan of 2026-10-27** (PRs #100-#149):

| Area | What was built | Where |
|---|---|---|
| Reminders and alarms | automatic sync every 3 hours, reminders set in the app or by asking the agent, delivery in the app and by email, smart alarms from the data with an expert's checked explanation | #100-#111 |
| Smarter chat | a way of working per question type, seven new tools, coaching that stays non-medical, a premise check, goal progress, outside lookups (USDA, web) | #112-#129, #134-#139 |
| Memory | a running summary per chat; long-term memory (episodes, facts, a profile, interests) from a listener after each answer, approved by one tap; memory screens | #115-#121 |
| RAG | 1,083 public lifestyle passages, cited as evidence. The evaluated default now ranks by embeddings, with word search available when embeddings are unavailable | #130-#133 |
| Experts | after three comparisons, the **hybrid**: experts answer inside their own area, and "why" questions go to the general agent with the experts' notes | #144, #147, #149 |
| Evaluation | real public data (PMData, LifeSnaps; 46 people), an independent oracle, a plain chatbot baseline, the PHIA benchmark, planted causes, decisions with rules set in advance | #141, #143, #147, #149, [evaluation.md](evaluation.md) |
| Teams | a check across every area (`team_scan`), daily alerts when the team's aggregate changes, team notes with event dates, proposals that wait for approval, and a weekly briefing: code-ranked findings, highlights picked by the model, warnings before a noted event like a past one; the supervisor chat was retired in #213 | #145, #146, #148, #213, [teams.md](teams.md) |

**Headline results** (details and limits in [evaluation.md](evaluation.md)):

- Real data, full system: **82% correct** on 472 questions from 46 people; on the same 187
  questions, **83% against 62%** for a plain chatbot given the data.
- The hybrid against no experts, 95 real-people questions: data questions **92% against 89%**,
  the whole agent 82 of 85 turns, 2% cheaper. It stays, narrowly.
- **"Why" questions are the weak spot:** about 55-60% right, and a cause is named in about half the
  cases where none was planted.
- Team stress score: **no link** with self-reported stress (median rho -0.03), so it is shown as
  "physical stress signs". Time asleep tracks reported sleep well (0.75).
- Team alerts on made-up teams: a false alarm in 12% of 8-person teams a month; a 1.2 SD sleep drop
  found in 20 of 24 such teams, typically by day 8; 5-person teams rarely get one.

**Since this November 11 snapshot:** the weekly team briefing is scheduled, the pilot started November 17, and Settings → Operations and Prometheus/Grafana cover quality and service monitoring. Personal experiments remain on hold. See [pilot progress](progress-2026-11-17.md) and [monitoring](monitoring.md).

## Objective

EECE 503P/798S course project (Path A, application), demo around the end of November 2026. An app
that analyzes a person's longitudinal Fitbit data and explains what changed and why, where **the
agent decides what to investigate and deterministic tools compute every number**. The instructor
requires a mobile app and a fully deployed system (backend online, installable app).

The grade weights idea and agentic justification (20%), agent performance and evaluation (20%),
AgentOps (15%) and reliability and security (15%), so **the agent and its evaluation are the
priority**; the UI and data plumbing exist to serve them.

## What works today

| Area | State |
|---|---|
| Data | Takeout import (legacy layout); **live Google Health API** client and mapping to the daily table, verified against Takeout ([metrics.md](metrics.md#from-the-google-health-api)); each person connects their own Google account from the app (encrypted token, background sync of the whole history) |
| Storage | Postgres in Docker, eight migrations (users, Google connections, daily metrics, sync runs; chat messages and cited evidence; findings, context questions, check-ins, memory facts; sign-up status and sessions; the cost of each answer; logging drafts, audit events and clarification state; conversations (0007) and pinning them (0008)); `python -m app.sync pull` stores live days |
| Analysis | deterministic tools returning `Evidence` (incl. change points with a permutation test, weekday split, and `compare_day`: one day against the middle half of the 28 days before); 14-vs-28-day screen with FDR correction and a templated report (the no-LLM baseline); our own **recovery score** (`app/analysis/day.py`) |
| Agent | LLM layer with cost accounting and budgets; validated toolbox; **general agent** (hypothesis-test loop, `submit_findings`, one repair round) and the **claim verifier**; **experts** (sleep, recovery, activity; nutrition defined, waiting for data) with ownership of claims and `consult`; **router** (Jev: topic, request intent and a yes/no per expert; keyword fallback; LLM router for comparison) and `ask()`, which routes and answers; questions about one day use `compare_day` with its own `day` claim kind; a consulted expert's verified claims are carried into the answer when the summary uses them; claims from the person's other conversations are memory items (kind `chat`). Reachable through `POST /chat` |
| API | `/health`, `/data/status`, `/days/{date|latest}` (with the recovery score and its parts), `/days/{date}/workouts` and `/days/{date}/hourly` (read live from Google, kept 5 minutes), `/checkins/{day}`, `/metrics/{metric}`, `/reports/latest`, `/evidence/{id}` (behind sign-in; each person's own live Google Health days from the database, the owner falling back to the Takeout export only with no live data at all; analyses cached until the next sync); **accounts**: `/auth/signup`, `/auth/login`, `/auth/logout`, `/auth/me`, and approval of sign-ups (`/admin/access-requests`, `python -m app.auth`); **chat**: conversations (`GET`/`POST /conversations`, `PATCH` (rename, pin) and `DELETE /conversations/{id}`; editing or retrying a question with `replaces`), `GET /chat?conversation=`, `POST /chat` (the agent with the person's conversation and memory, waits up to 55 s and stores slower answers when ready, one question at a time, daily caps per person and in all, summed from a spending ledger that deleting a chat does not touch (#154)); **Google Health per person**: `POST /google/connect`, `GET /google/callback`, `POST /google/sync`, `POST /google/disconnect`, `GET /google/status` (tokens encrypted with `FA_TOKEN_KEY`, PKCE, first sync of the whole history newest first, later syncs reread the last 3 days) |
| App | landing page; sign up / sign in (keychain, or localStorage on the web), waiting screen, Access requests for the owner; tabs **Today** (day switcher; Recovery, Sleep, Steps and, on wide screens, Resting heart rate in large figures against the usual range; morning check-in; sleep stages; steps by hour; the day's workouts with a page each; heart and body; what changed lately; a page per metric with 7/30/90 days and the usual band; two columns on wide screens), **Ask** (separate chats with a collapsible sidebar on the web, pin, rename, delete; copy, edit and retry on messages; attach a metric or finding; expert picker, quick/deep), **Reminders** (now connected to the reminders API) and **Settings** (account, appearance, Google Health, data coverage, logged entries); an evidence page per computation (question, answer, chart, figures, method); flat sections and rows in the "Track day" palette, light and dark; Expo SDK 58, Expo Go and web |
| Engineering | protected `main`, PRs with both CI jobs required, historical snapshot of about 1,080 backend test functions and 143 mobile tests; see the dated audit for the PR-specific test count |

The table above dates from 2026-10-27; what was added since is in [Where we are](#where-we-are-2026-11-11).

**Not built yet:** personal experiments (on hold); the
Failure Matrix and threat model; the daily run with the agent's note on Today (skipped at the
user's request); phone push; email verification and reset; the journal with
habit impact; fitness age; the weekly workout summary. Deployment (Railway and Vercel, see
[deployment.md](deployment.md)) and teams ([teams.md](teams.md)) are built.

## Core logging: first local implementation

Supplied-value food and workout logging now run through Auto in chat: Jev separates intent from
its topic; the expert asks for missing details and can prepare a persistent draft even with no
historical data. The next reply can continue an owned unfinished clarification for up to 24 hours;
a read-only topic change clears it. Read-only questions do not receive proposal tools.

The app shows review cards with edit, version-specific confirmation, cancellation and confirmed
undo. Settings → Logged food and workouts recovers saved drafts independently of the chat. `/actions` provides
owned draft/history/revise/cancel/confirm/undo endpoints. Migration 0006 adds the records, audit
snapshots and chat references, and has been applied to local project Postgres. Writes use a separate executor: committed execution claims,
entry-identity duplicate protection, scope checks, no blind retry, and unknown-outcome states.
Google consent can request just food or workout logging while preserving analysis access.

**Real Google writes are off by default** (`FA_GOOGLE_WRITES_ENABLED=false`). They have been
tested once for real, on 2026-10-25 with the flag on for the test: the owner logged a test snack
from the app, edited it, granted the nutrition write scope, confirmed it, saw it in the Fitbit app,
read it back from Google and undid it ([experiments.md](experiments.md#first-real-google-write-and-answers-that-read-like-one-reply-2026-10-25)).
A real workout (a 20-minute walk with no distance) was written, read back and undone on
2026-10-25 after PR #57 added the fields Google requires; it carries only the given values, so the
next step is adding the tracker's own measurements for that interval. Pending Google operations or crashes remain blocked
for reconciliation; automatic provider reconciliation/polling is not built yet.

Validated with fake Google and a scripted model end to end, browser review/edit/confirm/undo and
unknown/cancel states in light/dark on desktop/mobile widths, and two paid synthetic draft checks.
The second created one draft and submitted in two model calls. Both together cost about $0.0086.

Workout drafts accept every Google exercise type and carry what the tracker recorded over their
interval, the metrics Fitbit records for that kind of workout (calories, heart rate and zones,
Active Zone Minutes, and steps, distance or swim lengths where they apply), and warn about an
exercise the tracker already recorded then; see
[agent-actions.md](agent-actions.md#what-the-tracker-recorded-is-added-to-a-workout).

Food lookup and gram-based serving arithmetic are built. Remaining work includes nutrition sync and
provider deduplication, photo estimates (kept for the demo), and hydration. The optional
[recorded routes/regions extra](product.md#recorded-routes-and-regions-optional-planned) needs GPS
exercise data and separate location consent; daily step totals cannot reconstruct locations.
See [agent-actions.md](agent-actions.md), [architecture.md](architecture.md#confirmed-action-execution)
and [roadmap.md](roadmap.md#agent-assisted-logging-workstream-planned).

## Local setup

1. Backend: `python3 -m venv .venv && source .venv/bin/activate && pip install -e "backend[dev]"`.
2. Database: `docker compose up -d db` (Postgres on port **5433**), then
   `alembic -c backend/alembic.ini upgrade head`.
3. `.env` at the repository root (git-ignored; copy `.env.example`): `FA_TIMEZONE`,
   `FA_EXPORT_DIR`, `FA_GOOGLE_CLIENT_ID` / `FA_GOOGLE_CLIENT_SECRET` for live data, and
   `FA_OPENAI_API_KEY`, `FA_TYPESAFE_API_KEY` and `FA_LLM_SPEND_CAP_USD` for the agent. Both API
   keys are set on Karim's machine; **budgets are about $5 each**, see [costs.md](costs.md).
4. Live data: `python -m app.sync connect`, then `check`, `compare --export Takeout`,
   `pull --email <account>`. Run from the repository root.
5. App: `cd mobile && npm ci && npx expo start` (Expo Go) or `npm run web`.

### The Google Cloud project

The Google Health API is enabled in the Google Cloud project **`fitbit-agent-503p`**. Its OAuth app
("Patterns 503P") is **External** and in **Testing** mode, with the account that owns the Fitbit
data added as a test user and four read-only scopes: `googlehealth.activity_and_fitness`,
`googlehealth.health_metrics_and_measurements`, `googlehealth.sleep`, `googlehealth.nutrition`.
The OAuth client is of type **Desktop app**; its ID and secret live only in `.env`. These scopes
are restricted: publishing would need Google verification and a security assessment, so the app
stays in Testing (at most 100 test users; sign-ins expire after 7 days and need `connect` again).
To let someone else sign in, add their Google account as a test user in the console.

### Data on disk (all git-ignored)

| Path | What |
|---|---|
| `Takeout/` | first export (2026-06-27 to 2026-10-15), legacy layout with `Global Export Data` |
| `data/raw-2026-10-21/` | second export: no `Global Export Data`, sleep in `UserSleeps*` (v1 and v2 algorithms), nutrition values all "N/A" |
| `data/google_token.json` | the Google sign-in (mode `0600`) |
| `takeout-*.zip` | the original downloads |

## Decisions and findings

- **Live API is the data source going forward**; Takeout stays as an offline import.
- **Accounts are our own.** Invited pilot mailboxes are approved at sign-up. Other accounts wait for owner approval. Email and password (scrypt
  from the standard library, sessions as random tokens stored only as hashes, 5 failed log-ins
  lock an email for 15 minutes). The Google Health app is in Testing mode, so each approved person
  must also be added as a test user in the console by hand (Google has no API for it); approval
  is the reminder to do that. Signing in with Google was dropped: it would have needed a second,
  public Google app just for sign-in. The owner's own account is approved with
  `python -m app.auth approve <email>`, never automatically, since there is no email check yet.
  The data owner created by the sync has no password; they claim the account with
  `python -m app.auth set-password <email>` (asked without echo), which also replaces a
  forgotten or leaked password until there is a reset. A deletion request is honoured with
  `python -m app.auth delete <email>`: it lists how many rows will go, asks for the email again,
  deletes the account and everything pointing at it (a supervisor's teams too), then counts again
  and rolls back if anything is left. It prints counts only, never content.
  The app shows each phase's screens only (signed out, waiting, approved), so a deep link cannot
  skip sign-in or approval. Each person sees only their own data.
- **Never mix sources in one history.** The API's sleep is Google's v2 algorithm; the legacy
  export's is v1, about 38 minutes a night apart. Daily metrics are stored per source.
- **The API lacks** readiness, Fitbit's sleep score and cardio load; its sedentary periods do not
  reproduce Fitbit's sedentary total, so that column is left out. The recovery score uses sleep
  minutes and efficiency instead of Fitbit's sleep score.
- **Nutrition values exist only through the API** (34 nutrients plus energy and macros), arriving
  twice: Cronometer's daily total and per-entry Apple Health copies. Deduplicate before summing.
- **Recovery is our own score**, modeled on Bevel's inputs; a morning "how do you feel" check-in
  is the ground truth for comparing it with Fitbit's readiness.
- **Agent shape:** a cheap router (Jev, a typed classifier) sends each question to a specialist
  (sleep, recovery, activity, later nutrition); cross-domain questions are led by the owner of the
  metric asked about, which consults the others as tools. Whether this beats one general agent is
  measured. See [product.md](product.md).
- **Experts see their own metrics and the ones they read** (sleep reads activity; recovery reads
  sleep and activity; activity reads recovery and sleep); wear time is shared. **Only the owner
  makes claims about a metric**: a claim about another expert's metric passes only on evidence
  that expert produced through `consult`, so the lead can cite what it was told.
- **Consulting is the router's decision**, not the depth's and not the lead's. Jev answers, in one
  call, the topic (which expert leads, or general, the conversation itself, or out of scope) and,
  per expert, whether the question needs its data; a single topic distribution could not mark
  cross-domain questions ([experiments.md](experiments.md#router-pr-29-2026-10-23)). Depth only
  sets the budget; each allowed consult adds its own.
- **Routing thresholds** (hand-set, to be tuned by the router evaluation): refuse when out of scope
  is at least 0.5, even if the person picked an expert; the general agent answers when no expert
  reaches 0.4; consult experts needed at 0.5 or more.
- **The agent has one voice** (`app/agent/voice.py`, added to every prompt that writes to the
  person): warm and casual, reacting briefly to what the person says before answering, never
  adding facts or advice. When a message could be logged or asked about, one model call reacts and
  asks which (checked, with a fixed question as fallback); a new log request gets the logging
  tools of the lead and of the experts the router says it needs, so a workout and a meal can be
  drafted together.
- **Questions about the chat itself** ("what did I just say?", "recap this chat") have their own
  topic, `conversation`, at 0.5 or more whoever was picked. They are answered from the chat's
  latest eight exchanges in one model call without tools (`app/agent/conversation.py`), checked
  so every number comes from those messages; otherwise the person's own messages are quoted back.
  Before, such a question took the earlier questions' topic, and an expert without data answered
  "no data" without reading the chat.
- **Jev is called with our own small `httpx2` client** rather than TypeSafe's SDK: a 2 s timeout
  with no retries so a slow call falls back to the keyword rule, error bodies (which may repeat the
  question) never kept, cost in our own accounting, tests on a fake transport; no new dependency.
- **Nutrition** can draft food entries and look up nutrients; PR #195 also reads confirmed food logs. Coverage of external daily nutrition history is a separate ingestion question. See [logging capabilities](agent-actions.md).
- **Each person sees only their own data.** Live Google Health days from the database; only the
  owner falls back to the Takeout export, and only with no live data at all. New people get their
  whole history on the first sync (the API has no lookback limit; 90 or 14 days per request).
- **Chat in the app** (`POST /chat`): the request waits up to 55 s and a slower answer is stored
  when ready; one question at a time per person; daily spending caps of $0.10 per person and $0.50
  for the app, counted from each answer's stored cost.
- **Look:** a landing page with an expanding hero, the "Track day" palette (cream, track orange,
  sky blue; light by default with a System/Light/Dark switch), quiet pill buttons, and sign-in
  pages with a photo beside the form. Photos are free to use (Pixabay, Unsplash licences).
- **Platform:** OpenAI for the LLM; Railway (backend and Postgres) and Vercel (web) when deploying;
  Langfuse for agent traces and Prometheus/Grafana for API metrics; iOS TestFlight undecided.

## Next

What is left to the presentations on 2026-12-05, in order ([plan.md](plan.md#where-we-are-2026-11-22)):

1. **Jad's reliability and security deliverables** (15% of the grade, none in the repository yet):
   the Failure Matrix, the threat model, the red-team set, chaos, load and contract tests.
2. **Evaluation still open:** blind grading of `eval/results/phia_blind_2026-11-10.csv` by Karim
   and Jad (issue 38) and a fresh conversation set written by someone else. The held-out logging
   test ran on 2026-11-22: 167 / 180 ([test-results.md](test-results.md)).
3. **The pilot** (since 2026-11-17): the first real Monday team briefing (2026-11-23, 06:00 UTC),
   sign-ups, spend against the $50 cap, then the pilot report, survey and interviews.
4. **The final technical report, the demo script with its failure cases, and the presentation.**
   The poster session is done and closed with the instructor; no further poster is planned.

Earlier: **the smarter chat was built** (2026-10-28 to 11-05, #112-#122): coaching that stays
non-medical, seven new tools, a way of working per question type, a running summary per chat,
long-term memory (episodes, a listener with one-tap cards, a profile, memory search, interests),
knowledge cards, food and web lookups, and the app screens for all of it.

**The plan for the last four weeks is [plan.md](plan.md)** (2026-10-27 to 11-23, then two weeks of
buffer): join the parts into one agentic loop (daily run, proposals inbox, shared memory), personal
experiments, reminders for real, team improvements, chat fixes and new tools, a pilot with about 10
people, and every deliverable and bonus practice. What was done before it:

**Sprint 1 is done**, a few days early. The agent: LLM layer, tools, general agent, verifier,
experts with consult (#28), router (#29), metric check (#30), chat storage (#31), context builder
(#32), advice guard (#33), per-run test correction (#34), coverage and summary checks (#35), memory
tables (#36) and retrieval (#37). Then, on 2026-10-24, the app around it:

- Landing page (#39), "Track day" palette with light/dark and quieter buttons (#40), sign-in pages
  redesigned (#46).
- Accounts with approval (#41), the owner's `set-password` (#42), sign-in screens and data behind
  sign-in (#43), each person's own live data (#44).
- Real chat: `POST /chat` and the Ask screen on the agent (#45).
- Connecting each person's Google Health from the app, with background sync (#47, #48).

Fixes found on the way: the course name (503P, #38); the owner's sync-created account had no
password and could not sign in (#42); the first question's error was invisible on the Ask screen
(#45); evidence no longer falls back to made-up mock evidence (#45); on the web, images placed only
by their edges took the file's pixel size, and the scroll hero did not animate until it read a
derived value (#39, #46).

Then, on 2026-10-24/25, confirmed logging (#50 request intent, #52 drafts, review, confirm and
undo), the first real Google connection and write from the app (#53), chat fixes it led to (#54:
local time in the task, logging follow-ups, one natural reply, named evidence chips) and Expo SDK
58 (#55).

On 2026-10-25: workouts (#57-#60: Google's required fields, the tracker's reading on drafts,
all 181 types, [workouts.md](workouts.md)); the [UI plan](ui-plan.md) (#61); Settings in place of
Data (#62); Today with the day's numbers (#63) and finished with recovery, check-in, steps by hour
and workouts (#69); answers about today and consults kept with the answer (#64); the evidence page
(#65); conversations with shared memory (#66), their controls (#67) and chat polish (#68). Both
test entries left in the owner's Google were undone.

Then deployment (#89, #90; Railway with auto-deploy after CI, Vercel), chat fixes (#91, #92,
#94: questions about the chat answered from it), the agent's voice and a reaction before asking
what to do (#95), and the plan for personal experiments (#96). Teams were built on 2026-10-26
(#79-#88): memberships with consent, statistics, the weekly report with checked prose and figures,
the Team tab and the Monday email.

## What has been tested

Unit and scenario tests run in CI with the scripted model and fake HTTP transports, so they never
spend money. **The evaluation on real public data (2026-11-10) is in
[evaluation.md](evaluation.md)**; its headline numbers are [above](#where-we-are-2026-11-11).
The earlier real runs, on synthetic people, are logged with their findings in
[experiments.md](experiments.md); in short:

- **Experts:** three real runs; the third consulted another expert and passed every claim. Two
  bugs found and fixed on the way (evidence ids in text, experts not knowing who owns what).
- **Router:** Jev picked the right lead on 16 of 16 made-up questions in a median 0.21 s for about
  $0.00003 a question; the keyword fallback 14 of 16.
- **Routed answers end to end:** three runs; routing was right every time, and the third passed all
  four claims after three fixes (display names in claims, the tool-budget bug, null results).
- **Follow-ups:** with the earlier questions, Jev routed 8 of 8 made-up follow-ups right (2 of 8
  on the question alone), including references two and three questions back and a topic change;
  a real two-turn conversation answered "What about on weekends?" about sleep with 4 verified claims.
- **Advice guard:** on 20 made-up advice or diagnosis sentences and 12 sound ones, the word check
  caught 2 and the Jev guard 18, neither with a false alarm; on a real conversation the guard
  flagged nothing.
- **Many tests per run:** simulated on 400 synthetic people (free): without a correction 56% of
  runs on a calm person report something false; with it 6%.
- **Consult policy:** 16 runs comparing consulting as routed (A) with skipping consults of experts
  the lead already reads (B): B is about half the cost and time, A states the question's premise
  and has fewer rejected claims. Undecided.

- **Chat through the API:** one real question on the owner's live data: routed to sleep by Jev,
  answered in 11.3 s with 4 verified claims for $0.011.
- **Accounts, chat and Google connect** are covered by scripted tests (no paid calls): access for
  each account state, people never seeing each other's data or chat, spending caps, slow answers,
  and the Google flow end to end with a fake Google. The screens were clicked through with
  Playwright on phone and desktop sizes, in light and dark.
- **Logging and the first real Google write:** two paid synthetic runs prepared drafts ($0.0086).
  Then the owner connected Google from the app for real (4 read scopes), logged a test snack,
  confirmed it, read it back from Google and undid it; the chat problems this showed were fixed in
  PR #54 and rechecked with three more real runs.
- **Workouts** (PRs #57-#59, [workouts.md](workouts.md)): a real walk without a distance and a
  real measured walk were written and read back; range roll-ups reproduced Fitbit's summaries of
  the owner's 119 tracked workouts; real agent runs drafted `KICKBOXING` and `TENNIS` at the right
  local times. Fitbit labels our writes "Cronometer" (issue 22).

Spent on real runs: about $0.67 up to 2026-10-25, and about $21 in all by 2026-11-10, almost all
OpenAI ([costs.md](costs.md) has every run).

## Open issues

### Agent reliability after PR #195 · November 22

PR #195 is merged; its final audit is summarised at the top of this page. The remaining agent
issues are recorded, with examples, in the [deferred backlog](pr-195-followup-issues.md); no new
repair round is planned. The most important:

| Open issue | What a person can experience |
|---|---|
| Relative-period boundary roles | A block of days "ending on" or "starting after" an earlier window can be read with the wrong endpoint: a consistent but wrong window, answered without a question (2 silent cases in the final audit). |
| Whole-message policy after composition | When an overview is combined with a status or recall reply, a medical, fabrication or source-mixing flag can be dropped (found offline). |
| Protected retry counts | A retry can replace a requested length of days with a different one. |
| Food source, nutrient and filter edits | After a correct breakfast answer, asking for protein or all meals can get a false "unavailable" question. |
| Memory replacement | "After dinner now, rather than before breakfast" is treated as already kept; the explicit "replace ... with ..." works. No unconfirmed deletion happens. |

The older numbered issues below keep their original numbers.

1. ~~Text can mention a metric no evidence covers.~~ Fixed in PR #30: the verifier rejects a claim
   or summary that names a metric its evidence does not cover (distinctive terms only, such as
   "HRV" or "time asleep", not "sleep").
2. **Consult policy A vs B** is undecided ([experiments.md](experiments.md#consult-policy-a-vs-b-2026-10-23));
   A stays until the evaluation compares both on the full scenario set.
3. ~~False positives across many tests.~~ Fixed in PR #34: a run's own tests are corrected
   together. On 200 synthetic people with nothing planted, runs reporting something false fell from
   56% to 6%; planted changes were still found 92-98% of the time. Trade-off: a borderline change
   found only by the weaker change-point test can now be rejected; the repair message says to
   confirm it with `compare_windows`, which the model has not yet been seen doing (it dropped the
   claim instead).
4. **Answers do not always address the question asked.** Partly fixed in PR #35: when the router
   says a question needs another expert's data and no verified claim draws on it, the answer goes
   back once, and if still missing it carries a fixed note saying that part is not covered (a
   needed expert without data gets a note too). Seen working once: "Does exercising more change how
   I sleep?" ended with the note instead of silently skipping exercise. Not yet seen: the repair
   actually adding the missing part (its wording was fixed after the first try, because it asked
   for a claim the ownership rule rejects; untested since).
5. **Router evaluation completed.** The labelled held-out evaluation and baseline comparison are recorded in [evaluation.md](evaluation.md#the-router-and-rag-on-held-out-sets-2026-11-16). The thresholds remain hand-set.
6. **Evaluation scenarios must be detectable.** A planted 8 ms HRV drop came out as 3 ms in the
   data (not significant); each scenario's planted effect should be checked with the deterministic
   tools before it is used to grade the agent.
7. **Cosmetic:** the model sometimes wraps quoted values in quote marks ("6 h 57 min").
8. ~~Not wired yet.~~ Fixed in PR #45: `POST /chat` runs `ask()` with the person's history and
   memory, and the Ask screen uses it.
9. **Follow-ups and memory recompute instead of citing.** Earlier answers' and findings' evidence
   is re-attached and citable, but the model recomputed every time, even after the prompt said to
   cite it. Since the per-run correction, this has a cost: in one run a sleep drop already verified
   in memory was lost, because the recomputed test did not survive the correction, while citing the
   stored one would have passed.
10. **The advice guard misses implied diagnoses.** It caught 18 of 20 advice sentences (the word
    check 2 of 20) with no false alarms; it missed "your body is fighting something off" and "your
    heart rhythm may be irregular". Not tuned on the same set; to be measured on a held-out set in
    the attack suite.
11. **A summary can overstate a non-significant difference.** Mostly fixed in PR #35: each clause
    that names a metric with a direction word needs a significant test of that metric in the run;
    it caught a summary describing an untested bedtime change. Limits: support is matched by metric,
    not by the comparison (a weekend claim passes if any significant bedtime test is in the run),
    and generic words are not checked ("your sleep got shorter" passed in a run whose claims said no
    clear change).
12. **Accepted risk: when Jev is down, the scope check is a word list.** Jev is the scope check and
    has always answered so far; the keyword fallback catches only listed words. Revisit if the
    attack suite shows it matters.
13. **Quick depth can run out before the test the question needs.** Asked about exercise and
    sleep at quick depth (8 tool calls), the model spent them on descriptions and change points, and
    the correlations that answer the question were refused as over budget.
14. **"No clear change" can hide a real one.** After the per-run correction rejected a real but
    borderline sleep drop, the model claimed "time asleep did not clearly change", which the
    verifier allows on non-significant evidence. Honest in statistical terms, misleading in plain
    words; the evaluation's planted scenarios will measure how often it happens. Improved in PR #54:
    a hedged sentence may say "a little less, though that could be normal variation", and the
    evidence card explains when a result is not clear once the answer's checks are counted.
15. ~~The agent has not yet proposed a fact in a real run.~~ Fixed in #118: a listener after each
    answer replaces `propose_fact`, and it hears these in real runs.
16. **Accounts have no email check and no password reset yet.** Anyone can sign up with any
    address (approval is the gate), and a forgotten password needs the owner (`python -m app.auth set-password`). Both need an email
    service. The log-in lock is kept in memory, so it resets on restart and is per server process. On
    the web the session token sits in localStorage, readable by any script on the page.
17. ~~Connecting Google Health from a phone needs the deployed backend.~~ Done: the API is on
    Railway and the web app on Vercel ([deployment.md](deployment.md)). Kept for the record: Google sends the browser
    back to this server, which locally is `127.0.0.1` (accepted by the Desktop OAuth client) and
    unreachable from a phone. Deployment needs a public HTTPS address and a "Web application" OAuth
    client listing its `/google/callback`. Sign-ins in progress and running syncs are kept in
    memory, per server process.
18. **Fixed in the Settings screen.** After reading the Google callback result, it clears the parameter with `router.setParams({ google: undefined })`.
19. ~~No screen yet for facts the agent proposes.~~ Fixed in #121: memory cards in the chat and the
    inbox, and a memory page in Settings. Still open: Jev's routing and guard costs (about $0.00007
    a question) are not added to the stored cost of an answer.
20. **A verdict depends on how many tests the agent chose to run.** The same time-asleep drop on the
    same data was "no clear change" after 6 tests (adjusted p 0.096) and "a small real dip" after 5
    (0.04). The correction is right for each run, but the answer should not hinge on how many
    extra tests the model happened to run; options are a fixed family per question type or
    reporting borderline results as such. To be measured in the evaluation.
21. **The access log records Google's sign-in code.** The callback's address, code included, is
    written to the server's request log. The code works once and is used immediately, but the
    callback should be left out of request logging.
22. **Google labels our writes as "Cronometer"** in the Fitbit app (seen on the first real workout
    write). We send no `dataSource`; how Google picks the label is not documented yet.
23. **The router's consults are not always followed.** Asked "am i recovered today?", the router
    wanted activity too, but the Recovery lead never consulted it (a note says so), and it ran five
    correlation tests the question did not need.
24. **The recovery score is not validated.** Equal weights over three inputs, by design
    transparent; morning check-ins are the ground truth to compare it with once there are enough.
25. **Workouts and steps by hour need a Google Health connection**; the owner's Takeout fallback
    shows none.
26. **Not seen in a real run yet** (the day's chat cap was reached): sending an edited or retried
    question. It is covered by scripted tests. Pointers between conversations became episodes
    (#117), and a question about another chat worked in a real run.
27. **Answers stored before #64 keep the old note wording** ("does not cover the ... side").
28. **Some summaries still fall back to joined claims.** Down from 11 of 53, but 3 of the 8 rerun
    after the fixes still did, mostly on `why` and `change` questions
    ([experiments.md](experiments.md#the-chat-end-to-end-2026-11-05)).
29. ~~An answer can repeat the question's premise.~~ `check_premise` tests it first (2026-11-09).
30. ~~A goal cannot be measured.~~ `goal_progress` counts the days that met a target the person set (2026-11-09).
31. ~~`day` and `lookup` take about three model calls.~~ One or two, measured 2026-11-09.
32. **Real data is harder than the synthetic sets.** The first real check (six questions) had two
    summaries fall back and one run end with no answer (`no_submission`, on a weekend bedtime
    question). `eval/real_check.py` repeats it, keeping answers in git-ignored `data/`. After a
    second reminder to submit, a rerun answered all six with no fallback, but that is one run, one
    still ended on its budget, and a `why` question took 15 calls and $0.05. Since measured at scale
    ([evaluation.md](evaluation.md)): 82% on 46 real people.
33. ~~"Why" answers stop early.~~ Fixed 2026-11-16: once the premise check confirms a change, code
    tests every everyday driver (sleep, bedtime, time in bed, steps, Active Zone Minutes, strain,
    sedentary time) from its own change point, corrected for the number tested, and the agent may
    name only one that moved (`candidate_causes` in `strategy.py`). On the same 33 real-people why
    questions: 16 to 28 right; on the 25 answered both times (8 of the "before" run were model
    errors), 15 to 21 right, 8 questions fixed and 2 broken (p = 0.11). Synthetic checks over 20
    seeds find a planted cause and give none to a lone change.
34. **The team stress score does not track reported stress** (median rho -0.03 on PMData). Shown as
    "physical stress signs"; the consent text still says "stress" and changing it means asking
    members again. Undecided.
35. ~~Team checks do not catch names.~~ Fixed 2026-11-12: a question naming a member (by the name in
    their email) or asking after a name ("How is Sarah sleeping?", "Maya's recovery") is stopped in
    code, as are rankings and comparing part of the team with the rest (evaluation.md).
36. **Five-person teams rarely get an alert** (4 of 24 for a 1.2 SD sleep drop). A smaller team
    needs a bigger change; the floor cannot go lower.
37. ~~The team screens have only run on the mock.~~ Checked 2026-11-13 against the real API on a
    throwaway local Postgres with made-up members: a ready team, a withheld one, a paused overlap
    and a member's Teams page, light and dark, wide and phone width. It found one bug, fixed: a
    withheld week read "Steady" on every area; it now says "Not enough yet" and why.
38. **Blind grading is not done.** `eval/results/phia_blind_2026-11-10.csv` (51 answers) waits for
    Karim and Jad, and about 30 of the grader's readings should be checked by hand.
39. **Model calls sometimes fail in bursts** (8 of 33 in one evaluation run, 3 of 104 in another), well
    under the account's rate limits (5,000 requests and 2 million tokens a minute). The cause is not
    known yet: failures now store their error in the answer's trace (2026-11-16), so the next burst
    can be read in Railway.
40. **LifeSnaps sleep stages were wrong in the real-data evaluation** (found 2026-11-16).
    `sleep_*_ratio` compares a night's stage with the person's usual, not a share of the night, so
    each stage came out near the whole night. Fixed in `real_data.py` (no stages for LifeSnaps);
    earlier deep-sleep questions on LifeSnaps people were graded consistently but not on real stages.
41. **A how-to question in another language can find no passage** (found 2026-11-16). The search is
    given the question as asked; "comment faire une planche" falls below the similarity floor (0.38)
    while "how do I do a plank" finds it, and "combien de protéines par jour" works. Waiting, by
    Karim's decision: the fix would search an English version of the question, at a small cost per
    question.

