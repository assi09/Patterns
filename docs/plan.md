# The last four weeks

The working plan from 2026-10-27 to the end of the project. **Everything planned is built and
evidenced by Sunday 2026-11-23**; the two weeks after (Nov 24 – Dec 7) are kept free for surprises,
rehearsal and only small fixes. The poster pitch is done; this plan covers the final submission:
live demo and presentation (with a final poster if the instructor asks for one), the repository with
setup and reproducibility, the evaluation and its results, traces and operational metrics, failure
and threat analysis, architecture and API documentation, and the final technical report. Every
applicable bonus practice is in it.

Each item is its own small PR, per [AGENTS.md](../AGENTS.md). Open issues are the numbered list in
[status.md](status.md#open-issues); they are referred to here as "issue n".

## Where we are and what is left (2026-11-11)

**Presentations are on 2026-12-05.** The finish target stays Sunday 2026-11-23; Nov 24 to Dec 4 is
buffer and rehearsal. What was built since this plan was written is in
[status.md](status.md#where-we-are-2026-11-11). The rest of this page is the original plan of
2026-10-27, kept for the record; this section replaces its week-by-week part.

### Each workstream now

| Workstream | State | Left |
|---|---|---|
| A. Chat and agent | built; hybrid experts kept (#149) | **the "why" investigation** (issue 33); the summary fallback is rarer but not gone (issue 28) |
| K. Memory | built and live (#115-#121) | an evaluation on real data: memory and follow-ups are untested there |
| B. Personal experiments | **on hold** since 2026-11-08 (Karim's call) | resume only if Karim asks; otherwise a synthetic experiment is not in the demo |
| C. Reminders and alarms | built and live (#100-#111) | phone push notifications (`expo-notifications`); `reminder_effect` |
| D. Teams | `team_scan`, daily alerts, team agent with chat, notes and approved actions (#145-#148) | the weekly report written by the team agent; checking the screens on the real backend (issue 37); an evaluation; the consent wording (issue 34) |
| E. Joining it up | Today, Ask, inbox, memory page exist apart | account deletion, email verification and reset, issues 18 and 21; the daily run and Today's note stay skipped unless Karim asks |
| F. Pilot | invitations go out 2026-11-12 to 10-12 people | their Google accounts added as test users; one team of at least 5 who sync (8 or more makes alerts likelier); the daily total cap checked against the number who join |
| G. Evaluation | real data, PHIA, three systems, experts decided ([evaluation.md](evaluation.md)) | blind grading; the "why" retest; the team agent; the router on a held-out set (issue 5) |
| H. Reliability and security | not in the repo yet | Failure Matrix, threat model, red-team set, chaos, load and contract tests (Jad) |
| I. AgentOps and bonus | cost, trace and thumbs per answer stored (#151); CI and auto-deploy | a metrics page (the pilot report, `python -m app.pilot_report`, is in #152); Dependabot, CodeQL, audits, coverage, Sentry (Jad) |
| J. Documents | status, evaluation, teams, costs and experiments current | `docs/api.md`, README quickstart, the final report, poster, demo script |

### What still has to be tested

Each test has its rule written before it runs, like the expert decisions in
[evaluation.md](evaluation.md). Paid runs are logged in [costs.md](costs.md).

| Test | How | Passes when | Cost |
|---|---|---|---|
| **"Why" fix** | the same 33 why questions with planted causes on real people, plus the no-cause controls; the data questions again to check nothing else got worse | why answers at least 10 points better, a cause named in at most 2 of 12 no-cause cases, data questions not worse | about $1 |
| **Team agent, scripted** | made-up teams with a planted change in one area, two areas, or none; asks whether the agent reports the right areas and directions and nothing on quiet teams | every planted change named in its direction; nothing reported on quiet teams | free (CI) |
| **Team agent, privacy attacks** | about 30 attempts: "who", "which member", differencing ("the team without the night shift"), names, medical questions, instructions hidden in notes, proposals aimed at one person | every one refused or answered only at team level | free, then one live run of about $0.30 |
| **Team alerts on real data** | PMData's 16 people as one team, with and without a planted change | false alarms and detection close to the made-up-team figures in [teams.md](teams.md) | free |
| **Team screens** | the Team tab against the local backend with a made-up team: alerts, chat, notes, approve and decline, light and dark | every flow works; no console errors | free |
| **Blind grading** | Karim and Jad grade `eval/results/phia_blind_2026-11-10.csv` (51 answers); about 30 grader readings checked by hand | agreement with the automatic score reported, whatever it is | free |
| **Memory on real data** | follow-ups and a remembered event across two questions, on real people | the event is used when its dates match, and not otherwise | about $0.30 |
| **Router held-out set** | labelled questions not used while building | accuracy, latency and cost for Jev, the keyword rule and an LLM router | under $0.10 |
| **Red team, chaos, load, contract** | Jad's sets (H) | each case blocked, or listed in the Failure Matrix with its behaviour | free |
| **Pilot** | about 10 real people, one team, about two weeks | usage, answer success, cost and latency per person; the recovery score against check-ins (issue 24); survey | live caps |

### Order of work to Dec 5

**Nov 11-16: fix and measure**
- The "why" investigation: code tests every likely cause before and after the change, and scores
  may not be explained by their own inputs in `compare_windows` either. Then the retest.
- The team agent's evaluation (scripted, privacy attacks, alerts on PMData) and the screens on the
  real backend. The consent wording, once Karim decides.
- Pilot: testers' emails, test users, the team created. Blind grading by Karim and Jad.

**Nov 17-23: evidence and documents**
- Stored traces and a metrics page (AgentOps); Jad's Failure Matrix, threat model, red team and
  bonus practices.
- The weekly report written by the team agent, if the evaluation above is done.
- `docs/api.md`, README quickstart, the final report's results chapter from
  [evaluation.md](evaluation.md); a `v1.0-demo` tag.

**Nov 24 - Dec 4: buffer**
- Pilot results; small fixes only; demo script with failure cases (Jev down, over budget, an
  injection, a medical question, someone else's data, a question about one team member); poster;
  two full rehearsals.

**Dec 5: presentations.**

## The goal: one agentic system, not a set of screens

Today the parts work one by one: Today shows numbers, Ask answers, logging drafts entries, teams
send a weekly email, Reminders is a mock. The last four weeks join them into **one loop the agent
runs with the person**:

```
        sync (every morning)
              │
     ┌────────▼─────────┐   notices: changes, missed check-ins, expired Google sign-in,
     │    daily run     │   experiment days, reminders due, its own earlier proposals
     └────────┬─────────┘
              │ investigates the one change worth it (verified claims, evidence)
              ▼
   Today note ─── proposes ──► reminder · experiment · fact to remember   (person approves)
              │                       │
              │                 acts: reminds, records adherence, logs drafts the person confirms
              ▼                       │
   follows up: "did the wind-down reminder change your bedtime?" · experiment results
              │
              ▼
   memory (findings, results, check-ins, facts) ──► every later answer, the weekly recap,
                                                     and (aggregated, k ≥ 5) the team report
```

What makes it one system:

- **One daily run** drives Today's note, reminders, experiment days and follow-ups; the weekly
  run adds a personal recap next to the team report.
- **One proposals inbox**: everything the agent wants to do (remember a fact, set a reminder,
  start an experiment, log a draft) arrives as the same kind of card, approved or declined the same
  way, with one audit trail. Nothing happens without approval (decision 10).
- **One memory**: findings, experiment results, reminder effects, check-ins and approved facts,
  used by every answer and shown in one "What Patterns knows about you" page the person can edit.
- **One voice** (`app/agent/voice.py`) and **one rule**: every number links to its evidence.
- **One way in**: onboarding that connects Google, sets the person's goal, offers a first
  experiment and explains what the agent will and will not do.

## Workstreams

### A. The chat and the agent: fix what is weak, give it more tools

Fixes, from what the deployed app and the open issues show:

1. **The summary fallback**: when the summary fails its check twice, the joined claims read like a
   report. Write a deterministic summary instead (steady metrics in one sentence, changes first),
   and allow one more repair round for summary-only problems.
2. **Verdicts that depend on how many tests ran** (issue 20) and **"no clear change" hiding a real
   one** (issue 14): a fixed family of tests per question type, and borderline results said as
   borderline.
3. **Consults not followed** (issue 23) and **tests the question did not need**; **quick depth
   running out** (issue 13): plan the tests first, then spend the budget.
4. **Recomputing instead of citing memory** (issue 9); **answers missing a part of the question**
   (issue 4); **overstating in generic words** (issue 11).
5. **The reaction dropping "or look at your data"**, and **facts never proposed** (issue 15) with
   the screen to approve them (issue 19).
6. The **advice guard** on a held-out set (issue 10); cosmetic quote marks (issue 7).

New tools, so the agent can do what the system needs:

| Tool | What it gives the agent |
|---|---|
| `design_experiment`, `experiment_status`, `analyse_experiment` | the experiment workstream (B) |
| `propose_reminder`, `reminder_effect` | reminders it can suggest and later judge (C) |
| `workouts` | the workouts in a period, with type, duration and zones, from the stored sync |
| `checkins` | morning check-in ratings and tags, for "on days I felt tired…" |
| `habit_impact` | a journal tag against matched days without it, corrected for the number of tags |
| `memory_lookup` | the person's findings, results and facts by topic, so it cites instead of recomputing |
| `team_aggregate` (supervisors only) | the team's weekly aggregates, never below 5 people (D) |

Each tool validates its input, raises `ToolError`, returns `Evidence`, and gets tests including the
unhappy paths. Prompt and tool versions are recorded on every trace (workstream I).

### K. Memory that listens: short-term, long-term, and "cognify"

**Status (2026-11-05):** built and live, in our own Postgres without Cognee or Letta (#115, #117-#119,
#121; see [architecture.md](architecture.md#memory-and-context)). What follows is the original brief.

Asked for on 2026-10-28: the agent should be **actively listening**. Today it mostly forgets what
people tell it:

- **Short-term memory** is the context builder (`app/agent/context.py`): the last four exchanges
  verbatim and older ones condensed, within a token budget. A long chat loses its early turns.
- **Long-term memory** is findings, check-in answers, approved facts and claims from other chats
  (`app/agent/memory`). New facts arrive only when the model calls `propose_fact`, which it has not
  done in a real run (issue 15), and there is no screen to approve them (issue 19).

What changes:

1. **A listener on every message.** After each answer, one cheap model call (small model,
   structured output, no tools) reads the person's message and pulls out what is worth keeping:
   lasting context ("night shifts since August", "training for a 10 km"), **events with dates**
   ("exams next week", "sick since Sunday", "travelling to Paris on the 12th"), preferences ("keep
   it short"), goals and commitments ("I'll be in bed by 23:00 this week"). Each item is typed,
   dated (start and end where it has them), linked to the message it came from, and checked like
   any stored text (length, no instructions, no health diagnoses). It runs after the reply is sent,
   so it never slows the chat, and it is skipped when the daily cap is reached.
2. **The person stays in control.** Items arrive in the proposals inbox as "Patterns noticed: …
   keep it?" (decision 10: nothing is remembered without approval), grouped so it is one tap, not a
   stream of questions; a "What Patterns knows about you" page lists, edits and deletes them.
3. **Short-term memory per conversation:** a running summary of the chat, updated by the listener,
   plus open threads (a question the agent asked, a draft waiting), so a long conversation keeps
   its beginning without carrying every message.
4. **Long-term memory in three kinds:** *episodic* (events on dates, and each conversation's
   summary), *semantic* (facts, goals, preferences) and *results* (findings, experiment and
   reminder outcomes). Retrieval adds time: an event whose dates overlap the window an answer looks
   at is pulled in, so the agent can say "this dip coincided with the exams you mentioned".
5. **Acting on what it hears.** A commitment can become a reminder or an experiment proposal;
   an event that lines up with a smart alarm's change is cited in it; the daily run asks about a
   large unexplained change only when no remembered event explains it.
6. **"Cognify": decide by measuring.** [Cognee](https://docs.cognee.ai) is an open-source memory
   engine (`add` → `cognify` → `search`) that builds a knowledge graph and vector index from text,
   which suits linking life events, habits and metrics. It is a heavy dependency (AGENTS.md: ask
   first), sends the text to a model for extraction (cost, and this is personal health context),
   and needs a graph store hosted next to the API. Plan: a half-day spike on made-up conversations
   in week 2, compared with our own extractor stored in Postgres on the memory evaluation below;
   adopt Cognee only if it clearly wins. Either way the step is called "cognify" in the docs: extract,
   link entities (dates, habits, metrics), store, retrieve.
7. **Evaluated** (plan G): made-up conversations with planted facts and events; recall and
   precision of what the listener keeps, wrong or stale memories, whether answers use the right
   memory, memory-poisoning attempts (red team), and cost per message.

### B. Personal experiments (the headline feature)

As designed in [product.md](product.md#personal-experiments-headline-agentic-feature-planned) and
[architecture.md](architecture.md#experiment-runner-planned), in the order of
[roadmap.md](roadmap.md#personal-experiments-workstream-planned). **The owner's real experiment must
start by Wednesday Nov 5** to have three weeks of data before Nov 23, so the statistics tools, state,
approval and daily recording come first and the report screen last.

### C. Reminders for real

**Status (2026-10-28):** built and live. Automatic syncing (#100), stored reminders (#101), delivery
in the app and by email every minute (#102), the Reminders tab with its inbox (#106), and reminders
set by asking the agent, with a card to confirm (this PR). Setting alarms on the watch itself is
not possible: the Fitbit Web API is switched off and the Google Health API has no alarm method.
Smart alarms, data side (this PR): a background sync every 3 hours for every connected person;
detectors for a day far outside the usual range, a three-day streak, a significant two-week change
and stale data or an expired sign-in; a cooldown per kind and metric, quiet hours and a daily limit
shared with suggested reminders; a templated text from the evidence, sent in the app and by email.
Tuned on calm synthetic people (about 0.5 single-day and 0.1 streak alarms a person a week before
the cooldown) while catching most planted changes (73% of 2.5-hour short nights, 83% of a 6 bpm
resting heart rate rise). The owning expert explains each alarm before it is sent (checked, with the template as fallback),
and the inbox asks whether each alert was useful; Alerts settings choose kinds and how many. Phone
push notifications are still to do.

Replace the mock ([ui-plan.md](ui-plan.md#reminders), step 5):

- Backend storage and API (kinds: wind-down before a bedtime, move after long sitting, planned
  workout, logging and check-in prompts, experiment assignments, "reconnect Google").
- The agent proposes reminders with their evidence; the person edits the schedule, quiet hours and
  daily cap, and approves.
- Delivery: phone notifications in the installed app (`expo-notifications`), web push for the home
  screen web app where the browser allows it, and the in-app list everywhere. Email only for
  "reconnect Google".
- Follow-up: `reminder_effect` compares the target metric before and after, with a test, and the
  result goes to memory ("since the wind-down reminder, bedtime moved 25 minutes earlier").

### D. Teams, improved

Built: memberships with consent, team statistics (never below 5), opt-in named weekly levels, the
weekly report with checked prose and figures, the supervisor's Team tab, the Monday email
([teams.md](teams.md)). Next:

- **Invite by link** (the code inside a link) and a first-run screen for people who join that way.
- **Participation** for the supervisor: how many members synced this week, as a count only.
- **Trends over weeks** in the report, not just last week against the one before.
- **Ask about the team** for supervisors: the agent answers questions about the team's report with
  `team_aggregate` only, under the same floor of 5 and the same verifier.
- **A team challenge** the supervisor proposes (for example, a sleep-before-midnight week), joined
  individually and reported only in aggregate.
- **A verified sending domain** for Resend, so the email reaches any supervisor.
- Tested in the pilot (F) with a real team of about 10.

### E. Joining it up (the united system)

- The **daily run** as a Railway cron after the morning sync, like `weekly-email`: screen,
  investigate the top change, advance experiments, queue reminders, write Today's note. No model
  call on quiet days. Today's note returns, switchable off in Settings (it was skipped earlier at
  the owner's request; now it carries experiments and reminders too).
- The **proposals inbox** and the **memory page** described above.
- **Onboarding** and a **weekly personal recap** (in the app and by email, opt-in).
- **Accounts for real users**: email verification and password reset now that email works
  (issue 16), "delete my account and data", the session cookie on the web instead of
  localStorage (issue 16), the OAuth code out of the access log (issue 21), `?google=` cleared
  from the address (issue 18).
- Smaller planned pieces only if time allows, in this order: the journal with habit impact
  (needed by `habit_impact`), the weekly workout summary, fitness age.

### F. A pilot with about 10 people

Friends who train and wear a Fitbit or Pixel Watch, one team, a supervisor (to be decided).

- **Before (week 1)**: their Google accounts added as test users (the OAuth app stays in Testing:
  at most 100, sign-ins expire after 7 days); a consent and privacy page; account deletion; caps
  raised for 10 people (`FA_CHAT_DAILY_CAP_TOTAL_USD` about 1.50); an invite message and a
  feedback form.
- **During (weeks 2–3)**: about three weeks, three Monday team reports; daily log checks; each
  problem a Failure Matrix row and a regression test.
- **After (week 3)**: a 5-minute survey and 3–5 interviews; usage, success, cost and latency per
  person from the traces; the recovery score against check-ins (issue 24). Reported only in
  aggregate; no tester's data enters git.

### G. Evaluation (deliverable, 20%)

Two kinds of testing, kept apart (decided 2026-10-27):

- **The data side** (ingestion, daily metrics, the analysis tools) is deterministic: unit and
  property tests over time series, and the verifier's rule that every number in an answer comes
  from Evidence. Already in CI; it grows with each new tool.
- **The agentic side** (does the agent pick the right things to test, conclude correctly, and
  answer the question better than the alternatives?) is evaluated on **real, public wearable
  data**, with reference answers to compare against, not only on our own synthetic people.

**Real data with clear provenance.** Each dataset is downloaded by a script with a checksum into the
git-ignored `data/` folder (never committed, like any health data), imported per participant as its
own source, and cited with its licence in the report:

- **[PMData](https://datasets.simula.no/pmdata)** (Simula, CC BY 4.0): Fitbit data from
  participants over several months, with self-reported wellness (fatigue, mood, readiness, sleep
  quality, soreness, stress), training sessions with their effort, and injuries. The main set: its
  Fitbit files are close to the export format the importer already reads, and its logs give
  independent events to ask about.
- **Fitbit Fitness Tracker Data** (Möbius on Kaggle, from a 2016 survey of about 30 people):
  a month each, for breadth.
- **[LifeSnaps](https://zenodo.org/records/6832186)** (4 months, 71 people, Fitbit Sense plus
  surveys) if its Zenodo access terms allow it; the record is marked restricted, so check first.

**What the agent's answers are compared with:**

1. **Reference answers from an independent oracle.** For each question in the set (changes between
   two windows, weekday patterns, relationships between metrics, one day against the usual), a
   separate, deliberately simple implementation (plain pandas and SciPy, not `app/analysis`) works
   out the answer: which metrics changed, in which direction, significant or not, and the values.
   Each verified claim is scored against it (right metric, right direction, right verdict, right
   value), and so are the claims the answer should have made but missed.
2. **The datasets' own logs as outside truth.** Questions about a participant's injury, a hard
   training block or low-readiness weeks: does the agent find what the logs say happened, and does
   it avoid inventing causes the logs contradict?
3. **Real data with a planted effect.** Real series with a known change added (a later bedtime, a
   lower HRV for two weeks) keep the real noise and give a known answer: detection and false
   alarms on real texture. The same method drives the experiment suite.
4. **The alternatives, on the same questions:** a plain LLM given the person's data table and no
   tools (what most AI coaches do), the templated statistics screen with no LLM, the general agent
   against the experts, and the experts without the verifier.
5. **Blind human grading of a sample.** Karim and Jad rate about 50 answers, shuffled so they cannot
   tell which system wrote them, for correctness, usefulness and clarity; an LLM judge is then
   checked against those ratings before it grades the rest.

| Suite | Data | Measures | Against |
|---|---|---|---|
| Real-data questions | PMData, Fitbit Kaggle (LifeSnaps if allowed) | claim accuracy against the oracle, missed findings, agreement with logged events, blind human ratings | plain LLM with the data, templated screen, general agent, experts without verifier |
| Planted changes | real series with a planted change; synthetic people | detection, false reports on unchanged series | the same baselines |
| Experiments | real series with a planted habit effect; synthetic people | detection, false alarms near alpha, effect bias and interval coverage, "too few days" honesty | habit yes/no association (WHOOP-style), before/after windows |
| Router | a labeled held-out question set (including chat and logging questions) | accuracy, latency, cost | Jev, LLM router, keyword rule |
| Claims | all of the above | unsupported-claim rate, overstatements, advice leaks | with and without verifier and guard |
| Red team | Jad's set (H) | refusals and blocks | expected outcomes |
| Cost and latency | all runs | cost per successful task, end-to-end and per-step latency | per depth and per expert |

The harness lives in `eval/` and anyone can rerun it (`python -m eval.run --suite …`), writing to
`eval/results/` the code and prompt versions, the dataset and its checksum, the seed and the cost;
results publish only aggregates. Scenarios and reference answers are checked before they grade
the agent (issue 6); the consult policy A against B (issue 2) and the thresholds (issue 5) are
settled by it. Paid runs are budgeted in [costs.md](costs.md); **top up OpenAI to about $10–15
before week 3**.

### H. Reliability and security (deliverables, 15%)

- **Failure Matrix** (`docs/failure-matrix.md`): each component × failure (OpenAI, Jev, Google,
  database, email down or slow; malformed responses; rate limits; expired sign-ins; bad input),
  the behaviour, the test that proves it.
- **Threat model** (`docs/threat-model.md`): assets (health data, tokens, keys), actors, entry
  points (chat, uploads, OAuth, team codes), STRIDE-style threats, controls, residual risk.
- **Chaos tests** (fault injection on each external call), **load test** (k6 or Locust against a
  staging copy), **contract tests** (backend schemas against `mobile/src/api/types.ts`).
- The demo shows failures on purpose: Jev down, OpenAI over budget, an injection attempt, a
  medical question, another user's data requested, an unsafe experiment.

### I. AgentOps and observability (15%) and the bonus practices

| Bonus practice | Now | To do |
|---|---|---|
| Engineering workflow | PRs, protected `main`, ~100 merged PRs | GitHub Project with weekly sprints, an owner per issue, one required review |
| CI/CD and deployment | Actions; Railway and Vercel deploy after CI | a smoke test after each deploy, a release tag per week |
| Code quality | ruff | coverage (pytest-cov, jest) to Codecov, SonarCloud, coverage floor in CI |
| Agent evaluation in CI | none | a free gate on every PR (scripted model, deterministic suites, red-team set); a paid suite by hand with stored thresholds |
| Advanced AgentOps | cost per answer, a trace in memory | traces stored and sent to Langfuse (or OpenTelemetry), per call: latency, tokens, cost, tool failures, retries; a metrics page |
| DevSecOps | secret scanning and push protection | Dependabot, CodeQL, pip-audit and npm audit, Trivy on the image, Semgrep |
| Reproducible deployment | Dockerfile, automatic migrations, Railway config | a full-stack `docker compose up`, the cron config as code |
| Advanced testing | unit and scenario tests | contract, load, chaos and red-team suites (H) |
| Production monitoring | Railway's metrics | Sentry on the API and the web app, with alerts |
| Controlled evolution | feature flags such as Google writes | prompt and model versions on traces, comparisons between versions in the evaluation, flags for new features in the pilot |

### J. Documentation and the final deliverables

README quickstart (local and Docker), [deployment.md](deployment.md) kept current,
`docs/api.md` (endpoints, schemas, authentication, errors, from FastAPI's OpenAPI), the
architecture diagram updated, reproduction commands for every number in the report, the final
technical report, the presentation and demo script (with the failure cases in H), and a final
poster if the instructor asks for one (the pitch poster updated with results).

## Week by week (original, 2026-10-27)

Replaced by [Order of work to Dec 5](#order-of-work-to-dec-5); kept to show what was planned.

**Week 1 — Oct 27 to Nov 2: measure, secure, prepare**
- AgentOps: stored traces, Langfuse, prompt versions; Sentry. DevSecOps bundle, coverage,
  SonarCloud, GitHub Project and sprint issues.
- Evaluation harness and the free CI gate; the PMData importer and the reference-answer oracle;
  the labeled router set started.
- Chat fixes A1 (summary fallback) and A5; experiment statistics tools with property tests (B).
- Pilot prerequisites: account deletion, consent page, email verification and reset, issue 21 and
  18; testers' emails collected and added as test users.
- **Done when**: every answer has a stored trace with cost and latency; CI runs the eval gate; the
  experiment statistics pass their property tests; testers can be invited.

**Week 2 — Nov 3 to 9: the agentic loop**
- Experiments: state, approval card, daily recording, screen. **Owner's experiment starts by
  Nov 5.**
- The daily run (cron), Today's note, the proposals inbox; reminders backend and agent proposals.
- New tools: `workouts`, `checkins`, `memory_lookup`; chat fixes A2–A4.
- **Pilot onboarding** (about 10 people, one team).
- Memory that listens (K): the listener, conversation summaries, dated events, the Cognee
  spike against our own extractor.
- **Done when**: a synthetic person goes through propose → approve → daily recording → result in
  tests; the pilot team exists; reminders are proposed and approved in the app.

**Week 3 — Nov 10 to 16: evidence**
- Reminders delivered as notifications, `reminder_effect`; team improvements (invite link,
  participation, trends, Ask about the team, challenge).
- Paid evaluation runs; red-team, chaos, load and contract suites; Failure Matrix and threat model.
- Pilot running; survey and interviews at the end of the week.
- **Done when**: the evaluation tables are filled with results; every red-team case is blocked or
  documented; the Failure Matrix covers every external dependency.

**Week 4 — Nov 17 to 23: finish and write**
- Experiment report screen and the owner's result; weekly personal recap; onboarding; memory page.
- Final report, API docs, README and reproducibility, demo script and presentation; poster update
  if needed.
- A dry run of the demo, including the failure cases; a `v1.0-demo` tag.
- **Done when**: someone outside the team can set up, run and reproduce the main results from the
  README; the demo works start to finish twice in a row.

**Buffer — Nov 24 to Dec 7**: surprises, rehearsal, only small fixes. No new features.

## Where every open issue goes

| Issue | Plan |
|---|---|
| 2 consult policy, 5 thresholds, 6 detectable scenarios, 20 verdict vs number of tests | evaluation (G), weeks 1–3 |
| 4 missing parts, 11 overstating, 13 quick depth, 14 hidden change, 23 consults | chat fixes A2–A4, week 2 |
| 7 quote marks | A5, week 1 |
| 15 facts never proposed, 19 facts screen, 9 recomputing instead of citing memory | memory that listens (K), weeks 2–3 |
| 10 guard misses implied diagnoses, 12 scope check when Jev is down | red team (H), week 3 |
| 16 no email check or reset, token in localStorage; 18 `?google=`; 21 code in the log | accounts (E), week 1 |
| 17 phones need the deployed backend | done: deployed on Railway and Vercel |
| 22 writes labelled "Cronometer" | investigate in week 3 if time allows; documented as a limitation otherwise |
| 24 recovery score not validated | pilot check-ins (F), week 3 |
| 25 workouts need a Google connection, 26 not seen in a real run, 27 old note wording | covered by the pilot; no work planned |

## Who does what

Agreed on 2026-10-27.

**Karim** (with Claude Code): the hard and core parts, and the people.
- The agent: chat fixes and new tools (A), personal experiments (B), reminders (C), team
  improvements including "Ask about the team" (D), the daily run, proposals inbox, memory page,
  onboarding and account security (E).
- **The pilot (F)**: the testers are Karim's, so he recruits, onboards and talks with them, runs
  the survey and interviews, and keeps the feedback log.
- The evaluation harness, its question sets and paid runs (G); stored traces and Langfuse (the
  AgentOps core in I).
- The final report, the presentation and the demo (J), with Jad's sections.

**Jad**: testing the whole app, security, and the bonus practices.
- **Testing**: a manual pass over every screen each week (phone and web, light and dark, empty and
  error states), filed as issues; the contract tests (backend schemas against
  `mobile/src/api/types.ts`); the load test (k6 or Locust) with its write-up; the chaos tests
  (each external call failing or slow); and a fresh-clone run-through of the README to prove it
  reproduces.
- **Security**: the red-team set (prompt injection, medical questions, other people's data, unsafe
  experiments, unauthorized writes) with expected outcomes, run against the app; the threat
  model; the Failure Matrix, with Karim adding the rows the pilot finds.
- **Bonus practices**: the GitHub Project board and sprints; Dependabot, CodeQL, pip-audit and npm
  audit, Trivy, Semgrep; coverage to Codecov or SonarCloud with a floor; Sentry with alerts; the
  full-stack `docker compose`; a smoke test after each deploy; the free evaluation gate in CI once
  Karim's harness exists.
- **Reviews**: one approving review on Karim's PRs (and Karim on Jad's), which the review bonus
  needs.

Both follow [AGENTS.md](../AGENTS.md): no tester or personal health data in git, no AI attribution in
commits or PRs, every change through a PR with green checks. Jad writes the red-team set without
reading the router and guard prompts, so it measures them rather than mirroring them.

## Risks

- **The experiment needs calendar time**: if it cannot start by Nov 5, the demo shows a synthetic
  experiment end to end and the owner's partial result.
- **Google Testing mode**: sign-ins expire weekly; the "reconnect Google" reminder and email cover
  it. Verification for production is out of reach.
- **Budget**: about $21 spent on real runs by 2026-11-10 ([costs.md](costs.md)); the credit was
  topped up that day (amount not recorded). The tests left need about $2, plus the pilot under the
  app's daily caps. Hard caps stay in code.
- **The healthcare exclusion** in the brief: Patterns is framed and built as performance and habit
  analytics for people who train; it never diagnoses or advises, and experiments exclude anything
  medical. Keep that framing in every deliverable.
- **Scope**: if a week slips, cut in this order: fitness age, weekly workout summary, team
  challenge, web push, the journal (keeping `habit_impact` on check-in tags).
