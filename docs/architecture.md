# Architecture

This document covers the parts of the design that are settled. Components marked *planned* are
not implemented yet.

## Principle

The agent decides **what to investigate**; deterministic code does **all the computing and checking**.
Every statement in a report or chat answer must cite an `Evidence` record produced by a tool, and a
verifier rejects statements it cannot match to one.

## Components

```
 Mobile app (Expo) ──── HTTPS + bearer session ────► API (FastAPI)
                                                       │
     ┌──────────────────────┬──────────────────────────┼─────────────────────────┐
     ▼                      ▼                          ▼                         ▼
 Google Health API     Takeout export          Agent                       Postgres
 (live sync) ──┐       (offline import) ─┐     router → experts            users, daily metrics,
               ▼                         ▼     over analysis tools         sync runs, accounts,
          daily table (same columns from either source)                    chat, memory; later traces
               │                                   │
               ▼                                   ▼
        Analysis tools (deterministic) ──► Evidence ──► Verifier ──► report / answer
```

| Component | Location | Status |
|---|---|---|
| Takeout ingestion | `backend/app/ingest/takeout.py` | done (legacy layout; newer exports lack `Global Export Data`) |
| Google Health sign-in | `backend/app/sync/google_auth.py`, `connections.py` | the owner's CLI (loopback OAuth, token file `0600`), and each person's web sign-in from the app (PKCE, token encrypted in `google_connections`) |
| Google Health API client | `backend/app/sync/client.py` | done: paging, roll-up windows, retries |
| API data → daily table | `backend/app/sync/daily.py` | done, verified against Takeout ([metrics.md](metrics.md#from-the-google-health-api)) |
| Database | `backend/app/db/`, `backend/migrations/` | users, Google connections, daily metrics, sync runs, chat messages, cited evidence, findings, context questions, check-ins, memory facts |
| Live data → database | `backend/app/sync/pull.py`, `connections.py` | `python -m app.sync pull`, and background syncs started from the app (whole history first, then the last 3 days) |
| Analysis tools and `Evidence` | `backend/app/analysis/` | describe, coverage, compare_windows, trend, correlate |
| Screen and templated report (the no-LLM baseline) | `backend/app/analysis/screen.py`, `report.py` | done |
| Synthetic data with planted effects | `backend/app/synthetic.py` | done |
| General agent, verifier, readable findings | `backend/app/agent/` | done |
| Experts and consult | `backend/app/agent/experts.py` | sleep, recovery, activity; nutrition defined, waiting for its columns |
| Recovery score | `backend/app/analysis/` | planned, see [product.md](product.md#recovery-score) |
| Router and the ask flow | `backend/app/agent/router.py`, `ask.py` | Jev with keyword fallback; LLM router for the evaluation |
| Context builder | `backend/app/agent/context.py` | conversation and attachments; other memory planned |
| Accounts | `backend/app/auth/`, `backend/app/api/auth.py` | email and password (scrypt), sessions as hashed tokens, approval of each sign-up by the owner, `python -m app.auth` |
| API | `backend/app/api/` | auth, `/data/status`, `/reports/latest`, `/evidence/{id}`, `/chat`, `/google/*`; every data endpoint serves the signed-in person's own data |
| Mobile app | `mobile/` | landing, sign-up and sign-in, waiting for approval, Access requests (owner); Today, Ask (real agent), Reminders (mock), Data (Connect Google Health) |
| Advice guard and the Jev client | `backend/app/agent/guard.py`, `jev.py` | checks shown text by meaning |
| Evaluation suite | `eval/` | started: the advice sentence set; the rest planned |

### Ingestion

Reads a Google Takeout ("Google Health") export into one row per local calendar day and one column
per metric (see [metrics.md](metrics.md) for every column and its Fitbit source). Intraday data is
bucketed by the user's timezone; profile and account files are never opened. Malformed exports
raise `IngestError` instead of producing partial data silently.

### Live sync (Google Health API)

The Fitbit data comes live from the Google Health API (v4). Sign-in is Google's loopback OAuth
flow for desktop apps, with four read-only scopes (activity and fitness, health metrics, sleep,
nutrition); the refresh token is stored in `data/google_token.json`, readable only by its owner.
The Google Cloud project's OAuth app stays in **Testing** mode, because health scopes are
restricted: only listed test users can sign in, and Google expires the sign-in after 7 days, which
surfaces as `ReconnectNeeded`. Each person connects from the app instead: the browser signs in to
Google and returns to the API's `/google/callback`, which stores the token encrypted with
`FA_TOKEN_KEY` and syncs in the background. Locally the callback is a loopback address; from a
phone it needs the deployed backend on a public HTTPS address.

The client lists data points across pages and fetches daily roll-ups in the windows the API
accepts; rate limits, server errors and network failures are retried with backoff. The mapping
fills the same columns as Takeout, so everything downstream is source-independent, with one rule:
**a history comes from one source**. The API's sleep is Google's current algorithm, the legacy
export's is the old one (about 38 minutes a night apart), so mixing them would fake a change.

### Storage

Postgres (Docker locally, managed when deployed), schema changes as Alembic migrations, SQLite in
tests. Daily metrics are stored one row per user, source, day and metric, so new metrics (such as
nutrition) need no migration. Every table holding a person's data has a `user_id`, and every query
filters on it. Tables for later features are added by migration when the feature is built.

The conversation is one thread per person (`chat_messages`): each question with its attachment,
and each answer with its verified claims, who answered, whether the router chose them, whom they
consulted, whether it was refused, and the run id that links it to its trace. **Only evidence a
verified claim cites is stored** (`evidence`, once per id), so the app can show it and a follow-up
can cite it without recomputing; everything else a run computed can be recomputed from the data.
Both are deleted with the person. Each answer also stores its cost, which the daily spending caps
add up.

Accounts are `users` (email, scrypt password hash, `pending`/`approved`/`rejected`) and
`auth_sessions` (only a SHA-256 hash of each session token). A person's Google token is in
`google_connections`, encrypted, never in plain text.

### Analysis tools

Pure functions over the daily table. Each validates its arguments (`ToolError` on bad input),
computes on non-missing days only, and returns an `Evidence` record with:

- a unique `id` that claims cite,
- the tool name, metrics and date windows used,
- the sample size `n` and a `sufficient` flag (false below a per-tool minimum number of days),
- the computed statistics.

Methods are chosen for short, noisy personal data: Mann-Whitney U with Cliff's delta for window
comparisons, Theil-Sen slopes with Kendall's tau for trends, and Spearman correlation across lags
with a Bonferroni adjustment for the lags tried.

### Screen and report

The screen compares the last 14 days of every metric with the 28 days before (Mann-Whitney U,
Cliff's delta), leaving low-wear days out of activity totals. Because about twenty metrics are
tested at once, p-values are adjusted with Benjamini-Hochberg (FDR 5%), and only changes with at
least a medium effect are reported. The adjusted p-value is stored in the evidence, so the app
shows the value the decision was made on. The report turns each change into templated text whose
numbers all come from its evidence. It is what the app shows until the agent exists, and the
"statistics only" baseline the agent is evaluated against.

### Agent

`backend/app/agent/`: the general agent (`agent.py`), the experts (`experts.py`), the router
(`router.py`) and the ask flow that joins them (`ask.py`).
A run starts either from the screen's changes (`investigate`; when nothing changed, no model is
called) or from a question (`answer`). The model records hypotheses, tests them with the toolbox
(`tools.py`: validated calls over the analysis tools, limited to the metrics in scope), and calls
`submit_findings`. Text shown to people uses the names and formats in `present.py`; the data keeps
its raw units. The LLM layer (`llm.py`) prices every call and enforces a per-run budget and a spending
cap; tool calls past the budget are refused one by one, so a turn that asks for too many loses only
the excess. `ScriptedLLM` stands in for the model in tests. Each run keeps a trace of every step.

**Experts** run the same loop with their own prompt and a toolbox over the metrics they own plus
the ones they read ([product.md](product.md#experts)); wear time is shared. One rule is added to
the verifier: **only the owner makes claims about a metric**. A claim about another expert's metric
passes only when all its evidence came from that expert through `consult`. The router decides
which experts may be consulted; `consult` runs one as a *quick* answer on a budget carved out of
the lead's (leaving the lead enough calls to submit and repair), at most twice per answer and once
per expert, and lends the lead the evidence behind its verified claims. Consulted experts cannot
consult. An expert with no data (nutrition, for now) answers without calling the model. Budgets:
quick 6 model calls, 8 tool calls, $0.02; deep 12, 20, $0.05; each allowed consult adds 5 model
calls and $0.015.

**Router** (`router.py`). One Jev call asks a *choice* (the topic: an expert, general or out of
scope) and one *yes/no* per expert (does answering need its data). `decide` turns them into an
action with fixed thresholds: out of scope at 0.5 or more is refused, even when the person picked
the expert; a lead below 0.4 (or `general` on top) goes to the general agent; other experts needed
at 0.5 or more are consulted. Jev is called over `httpx2` with a 2 s timeout and no retries; on any
failure the keyword rule answers and the reason is kept. Only the cleaned question text (control
characters removed, at most 500 characters) is sent, and error bodies are never kept, since they
may repeat it. An LLM router with the same output exists only for the evaluation's comparison.
`ask` routes, then refuses without a model call, or runs the general agent or the expert, and
records the routing decision as the first step of the trace.

Planned: the evaluation comparing the experts with the general agent, and the routers with each
other on a labeled question set.

### Verifier

Deterministic (`verifier.py`). Each claim must cite existing, sufficient evidence; a change or an
association must be significant and point the stated way, where **significance is judged after
correcting for all of the run's own tests together** (Benjamini-Hochberg, the screen's method;
evidence from the screen, a consult or an earlier answer keeps its own run's correction); every number, duration, time of day and
date in the text must come from the cited evidence; every metric the text names must be covered by
that evidence (distinctive terms such as "HRV" or "time asleep"; generic words such as "sleep" do
not count); and the text must not use internal metric names, diagnose, state causation or reason
about calorie balance. The summary is checked too.
Failing text goes back to the model once with the reasons, then is dropped. Two checks look at the
answer as a whole: the summary may describe a metric as changing only if a significant test of it is
in the run, and **coverage**: when the router says the question needs another expert's data and no
verified claim draws on it, the answer goes back once, then carries a fixed note saying that part is
not covered.

**The advice guard** (`guard.py`) checks by meaning what the word rules check by words. The router
only judges the question, and an in-scope question can still get an answer that advises ("cutting
caffeine should help") or names a condition, worded so no listed word appears. So every sentence
that passed the deterministic checks, the summary included, goes to Jev in one call, with one
yes/no per sentence: does it diagnose, name a condition, or tell the person what to do for their
health? A flagged sentence is rejected like any other. If Jev is down, the word rules alone apply
and the trace says so. Consulted runs are not checked, since only the lead's text is shown. The
Jev HTTP client (`jev.py`) is shared by the router and the guard.

## Confirmed action execution

Local-first delivery and researched tools: [agent-actions.md](agent-actions.md). The router
classifies read/log/mixed/manage/clarify intent in its existing Jev call. Read-only requests get
no proposal tools. Log/mixed requests can prepare one food or workout draft for the owning expert;
the general agent uses the same logging instructions if the topic is unclear. A server-held
unfinished clarification can continue on the next reply for up to 24 hours, without treating
older questions or a conversational confirmation as execution permission. Manage requests point
to the entry's controls rather than letting the model delete anything.

**Implemented:** `backend/app/actions/` validates supplied-value food/workout logs, builds provider
payloads and prepares owned drafts. `/actions` exposes review, revision, cancellation, confirmation
and undo; the app contract, HTTP client and mock match it. Chat returns `actionIds` for review
cards, and Data lists saved entries so a lost answer cannot orphan a draft. Migration 0006 adds
`health_actions`, append-only application audit snapshots and chat state. Draft values are inputs
with provenance, not statistical claims or Evidence.

Execution commits a version/status compare-and-set before any remote request. It preserves Google
record/operation IDs, checks the granted write scope, prevents duplicate entry identities (food
name/time or workout type/interval), and never blindly retries a create. Food names and timestamps
are not put in proposal-tool trace metadata; SQL errors are handled without logging bound values.
Unknown/pending operations and interrupted execution stay blocked; automatic reconciliation is
still planned. The provider writer is tested with fake HTTP, and one real food create and delete went through on
2026-10-25, and one real workout create and delete after PR #57. Real writes are gated by
`FA_GOOGLE_WRITES_ENABLED`, off by default.

A workout draft also carries the tracker's reading for its interval (`measured`), read by the
server with Google's range roll-ups whenever the draft is created or saved again. It is never
taken from the model or the app, and it never blocks a draft: without a sign-in or on any Google
error it is marked unavailable and only the given values are sent. Which metrics are read depends on
the kind of workout; see [workouts.md](workouts.md).

**Conversations.** A person's chats are separate conversations (migration 0007 filed the earlier
single thread as the first). A run is given its own conversation's recent turns and summary; only long-term memory crosses
chats: facts, findings, answers, and episodes. An episode (memory kind `episode`, 90 days) is one
dated line that code writes from a chat's verified claims when it has been idle for an hour, with
their evidence, so an answer can point to what another chat found. Nothing a chat merely said
reaches another chat. Deleting a conversation deletes its messages and episode; facts and findings
stay. Conversations can be renamed
and pinned (migration 0008). Editing a question, or retrying an answer, sends the new text with
`replaces`: that question and everything after it in the conversation are removed, only once no
other answer is running for the person, and the new text is answered as usual.

**Today.** `GET /days/{date}` returns every daily metric with the person's usual range (the middle
half of the 28 days before, at least 7 days; low-wear days left out of activity) and the last 14
days. The **recovery score** is our own: each of last night's HRV, resting heart rate (counting
down) and time asleep gets the share of the 28 days before that it beat, and the score is their
mean (0-100, at least two inputs); it is computed from the daily table, never stored, and its parts
are returned with the day. The day's workouts and steps by hour are not in the daily table: they
are read from the person's Google Health when asked (range roll-ups, the exercise list) and kept
five minutes. The morning check-in (1-5 and tags) is stored per day; only today's can be set.

Questions about one day use `compare_day` (one day against the middle half of the 28 days before,
the rule the Today screen uses). Its claims have their own kind, `day`, whose direction must match
where the day sits (up above the range, down below, none within); it describes the day and is
never treated as a test of a change.

The following requirements also cover the remaining capabilities:

Workout and nutrition logging are a core planned extension; see
[product.md](product.md#agent-assisted-logging-core-planned-capability). Reuse accounts, expert
routing, chat and encrypted Google connections. The current analysis toolbox remains read-only;
add proposal tools and a separate deterministic executor, never unrestricted model write access.

Persist per-user action proposals, immutable confirmed payload versions, status transitions,
provider IDs and an audit of execution/undo. Add a migration and evolve the backend schemas,
`mobile/src/api/types.ts`, HTTP client and mock together. Status must distinguish drafts,
awaiting confirmation, cancelled, executing, succeeded, failed, unknown outcome and undone.
Only an authenticated owner can confirm, execute or undo their own proposal. Model text and
imported text cannot authorize actions. Routing must recognise logging requests and missing-detail
follow-ups without weakening the medical refusal rules.

Execution checks approval, payload version and granted scopes server-side. Idempotency and
concurrent confirmation handling must survive process restarts. A timeout after Google's write
may mean success: reconcile before retrying; never blindly replay a create. Reconcile remote
success with local persistence failures, and deletion failures with the displayed undo status.
Persist Google IDs and provenance so sync echoes and provider duplicates do not double count.

Request the activity/nutrition write scopes only for enabled logging features, handle reconnect
and denied permissions, and preserve read-only connections. Verify exact create/update/delete
payloads, ownership restrictions, idempotency support and reconciliation semantics against the
provider before enabling writes. No Google console or deployment change is made by this plan.

Workout summaries require a new intraday fetch and deterministic aggregation layer: daily totals
cannot establish a workout's heart rate or steps. Define time boundaries, timezone handling,
sensor gaps and zone thresholds explicitly; return evidence with coverage and omit unsupported
summaries. Keep raw samples out of prompts. Photo input is a deliberate later privacy extension
to the current aggregates-only model boundary: explicit upload, bounded file validation, no
photo content in traces, a defined retention/deletion policy, and estimates labelled separately
from statistical evidence. Provider nutrition lookup should precede model estimates where feasible.

Verify with fake Google transports and scripted models: clarification, edit/reconfirm, cancellation,
unapproved and cross-user writes, denied scopes, duplicate/concurrent confirmation, ambiguous
network outcomes, restart recovery, sync echoes, undo and partial failures. Test deterministic
workout calculations on synthetic samples and photo provenance without paid calls. Real write
validation requires explicit approval for the exact entry and any cleanup; photo model runs follow
[costs.md](costs.md). These are acceptance gates, not results already observed.

Provider references checked 2026-10-24: [supported data types and scopes](https://developers.google.com/health/data-types),
[nutrition guide](https://developers.google.com/health/data-types/nutrition),
[data point reference](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints).

### Experiment runner (planned)

The personal experiments of [product.md](product.md#personal-experiments-headline-agentic-feature-planned).
The model proposes, explains and writes; every design choice that needs a number and every result
comes from deterministic code, as for answers.

- **State** (new tables, one migration): `experiments` (owner, behaviour text, main and secondary
  outcome metrics, lag in days, status `proposed → approved → running → finished | stopped |
  abandoned`, planned and minimum usable days, seed, timestamps); `experiment_days` (date, assigned
  on/off, followed yes/no/unknown, usable yes/no with the reason, from wear time and check-in tags).
  The schedule is stored when the experiment is approved and never changed afterwards, only
  extended with new balanced blocks.
- **Tools** (`backend/app/analysis/experiments.py`, each returning Evidence):
  `design_experiment` (block-randomised balanced schedule; required usable days from the outcome's
  own variation over the last 60 days, by simulation, for a minimal effect worth knowing per metric:
  for example 20 minutes of sleep, 3 ms of HRV), `experiment_status` (adherence, usable days, days
  still needed) and `analyse_experiment` (on against off days as assigned and as followed, a
  randomisation test over the stored schedule's blocks, the difference with an interval, and the
  smallest detectable effect). Outcomes are the existing daily metrics and check-in ratings.
- **Agent tools**: `propose_experiment` (the model fills behaviour, outcome and lag; the server
  validates against an allow-list of behaviour kinds and a deny-list of risky ones, then runs
  `design_experiment` and stores a `proposed` row for the app's approval card, like logging
  drafts); the expert that owns the outcome metric writes the final report from
  `analyse_experiment`'s evidence through the normal verifier. Approval, stopping and starting are
  server endpoints the person calls from the app, never model tools.
- **Daily run** (a Railway cron after the morning sync, the same pattern as `weekly-email`): for
  each running experiment, record yesterday's usable and followed flags, extend when needed,
  finish when the usable days are reached, and queue the reminder and the Today note. No model call
  on ordinary days; one expert run when an experiment finishes.
- **Verifier rules**: an experiment claim must cite `analyse_experiment` evidence; "worked" needs
  the main outcome significant on the as-assigned comparison; secondary outcomes are corrected for
  their number; "caused" stays forbidden in text even here, since adherence is self-reported.

## Memory and context

The course asks for memory's scope, lifetime, retrieval strategy and privacy to be defined. The
principles: the context window is scarce, so a run gets a small, deterministic selection; memory
is **written selectively** and **maintained**; and memory, like any text from outside, is **data,
never instructions** (memory poisoning is OWASP's agentic risk ASI06).

**Data itself is not memory.** The agent never reads rows: it fetches statistics on demand through
tools, so its view of the data is always current and every number is computed.

### Kinds of memory

All memory is per user (`user_id` on every row, every query filtered) and is deleted with the
user's data.

| Kind | What it holds | Written by | Lifetime | Retrieved when |
|---|---|---|---|---|
| **Conversation** | the chat turns: questions, verified answers, attachments | the system, per turn | the thread | always: last 3 turns verbatim; older ones through the summary, condensed until it reaches them |
| **Chat summary** (short-term) | about 100 words on the turns before those: what was asked and found, what the person said, what is open; plus drafts and reminders still waiting, read from their rows | the small model, after the answer, two turns at a time; never in a chat of under 5 turns | the conversation; cleared when an edit removes turns it reaches | always, in its own conversation only; never citable |
| **Findings** (episodic) | verified claims of past runs with their evidence ids, metrics and dates | the system, only after verification | until a newer finding on the same metric supersedes it, at most 90 days | the question's metrics match; newest first |
| **Episodes** | one dated line of a chat's best verified claims, with their evidence | code, when the chat has been idle for an hour; no model call | 90 days, or until the chat is deleted | in other chats, when the metrics match; more likely when their dates overlap the last 30 days |
| **Context answers** | the person's answers to the agent's questions ("exam week") with the dates and metrics asked about | the person | 180 days | the date range or metrics overlap |
| **Check-ins** | daily rating 1-5 and fixed tags | the person | 365 days | through a `checkins` tool, for the window being investigated |
| **Profile** (core) | the facts the person kept that still apply, and their main topics; about 250 tokens | built by code for each answer | as long as what it holds | always, in every chat; never citable |
| **Interests** | a score per metric from what they ask about, pin, open and mark useful | code, automatically; half-life 30 days | until faded; muted ones stay muted | they lift related memory and alerts; the main ones join the profile |
| **Facts** (semantic) | what the person said about themselves: routine, goal, preference, context, dated event, commitment; at most 120 characters | **heard by the listener; a card once said twice or asked for; kept only after the person's tap** | candidates 30 days; kept ones until changed or deleted; past events and commitments leave the profile | through the profile; beyond its size, as memory items for 60 days unused; `memory_lookup` always |
| **Traces** | every run's steps, cost and verdicts | the system | 30 days | never put in a prompt: for AgentOps and evaluation only |

### Listening

After an answer, code skips plain questions and one-off requests; other messages go to one small
model call (`app/agent/listener.py`, about $0.0006) that notes what they say about the person, typed
and dated, through a tool. Each note then passes the medical guard and the fact rules (no condition,
no instruction, 120 characters), and is counted in `memory_facts`: a candidate is used for nothing
and only shown on the memory page. Said twice, or with "remember that", it becomes a card in the
inbox. What the person declined is never raised again, and what was only heard in a message goes
when that message is edited or its chat deleted. `GET /memory` shows all of it except what was
declined; the person can keep, reword or delete.

### Searching

The context holds little on purpose; two tools reach the rest, for every question type except `day`.
`memory_lookup` ranks findings, facts, events and episodes by shared words, metrics and dates, and
what it returns can be cited. `search_conversations` finds what was said in the person's other
chats: quoted data with its date, never evidence, and without refused turns. A question about the
chat itself reads the same search, with no extra model call. Memories are few and short, so there
are no embeddings or vector store. Numbers, times and dates in an answer still come only from
computed evidence: the agent refers to a profile item in words ("your bedtime goal").

### Urgent messages

A message describing an emergency (chest pain, trouble breathing, stroke signs, thoughts of
self-harm) gets a fixed reply from code telling them to get help, before any routing result is used
and with no model call, so it holds when Jev or OpenAI is down. It errs towards replying. The wider
definition of what the agent may say about health is agreed in outline and on hold.

### Coaching knowledge

Advice is specific to the person or it is not given. When they ask how to improve, code runs
`habit_options` (tested habits) and `personal_options` (what stands out in their routine: bedtimes
on best and worst days, weekend drift, a heavier week, the quietest weekday), and the model words
at most two suggestions from those, fitted to the profile. What stands out is described, not
tested, so it is said as worth trying. With nothing specific, the agent says so and asks what is
going on. The verifier refuses advice anyone could read anywhere (`GENERIC_ADVICE`). Questions about
what happened get no advice. An alert adds one suggestion only on a problem that lasted (a streak,
a two-week change), only when the data has something to point at, and it reads the profile. A
comparison found the cards made little difference, so retrieval was not extended
([experiments.md](experiments.md#advice-specific-to-the-person-and-whether-cards-matter-2026-11-05)).

Fourteen cards in `backend/app/knowledge/*.md` say how to try an everyday habit, in our own words,
each with its public source and the habit it belongs to. They hold no numbers, and tests keep them
free of medical words. When a person's data supports a habit (`habit_options`), code attaches that
habit's card to the task; `knowledge_lookup` is for coaching questions about anything else. A card
only goes next to the person's own evidence, and the answer names its source without a link, since
a link would make the turn read like an instruction when quoted back. `eval/knowledge_guard.py`
checks every card with the medical guard. There are no cards on logging: no public page we found
supports one.

### Looking things up outside the data

Questions about the world (`world`, the seventh question type: what is in a food, what a metric
means) get their own short route (`app/agent/world.py`): one call picks `food_lookup` (USDA
FoodData Central) or `web_lookup` and writes a general query, code runs it, one call writes the
reply. The result is never `Evidence`, so the verifier's rule stands; the reply has its own check,
that every number in it is in the result, and the answer says where it came from and that it is not
from the person's data. When a food reply fails, code states the values; a web reply that fails
becomes "I couldn't look that up".

`web_lookup` is OpenAI's `web_search` limited to `ALLOWED_DOMAINS` (`app/outside.py`). Medical
questions are refused by the router first. A query that looks personal or medical is refused
before it leaves. A result citing nothing on the list is treated as nothing found, links are
stripped, and text that reads like an instruction is dropped. A person gets 5 searches a day;
results are cached for a day and shared, as queries hold nothing personal.

When a food is logged without values, `food_lookup` gives typical values, code scales them to the
portion, and code marks the draft `provenance: estimated` with its source, whatever the model says.
The card asks the person to check it, and an edit makes the values theirs. Without
`FA_FDC_API_KEY`, food lookups are off.

### Retrieval: the context builder

Deterministic, before the model is called:

1. **Scope.** The router's label (or the chosen expert) gives the metrics in play; an attached
   finding or metric is added first.
2. **Select.** Only rows for this user whose metrics or dates match the scope.
3. **Rank.** Score = relevance (metric match, date overlap) + recency (decays with age) +
   importance (a verified finding's effect size; facts the person confirmed count fully). Ties go
   to the newer item.
4. **Cap.** At most 5 items besides the conversation, within a fixed token budget (about 1,500
   tokens). Older findings' evidence is re-attached so it can be cited instead of recomputed.
5. **Record.** The trace lists which items were retrieved, so an answer can be traced to its
   context and retrieval can be evaluated.

No embeddings: memory here is structured (metrics, dates, tags), so filtering and ranking is
cheaper, deterministic and testable. No model call is used to summarize memory.

**Built so far: the conversation and attachments** (`backend/app/agent/context.py`, stored in
`chat_messages` and `evidence`). The last 4 turns go in verbatim (question, answer, verified claims
with their evidence ids) and their cited evidence is re-attached, at most 8 records; older turns are
condensed to the question and the claims' text; an attachment (a metric, or a finding with its
evidence) comes first. Items are added newest first while they fit in about 1,500 tokens. Refused
turns and turns that read like instructions are left out, and the trace records what was included
and dropped. Re-attached evidence counts as the expert's that produced it, so the ownership rule
treats it like a consult's. The router sees the current question and up to 3 earlier ones (questions
only), so a follow-up such as "and last week?" is routed by what it refers to, even several
questions back. An attachment's metric decides the lead unless the person picked an expert.
Findings, context answers, check-ins and facts come with their tables.

**Stored, with the write rules enforced in code** (`backend/app/db/memory.py`, migration 0003):
findings only from verified change and association claims of investigation runs, a newer one on
the same metric superseding the older; context questions written by code from a template and a
fixed menu of options (travel, work or exam schedule, more or less training, illness, new device,
other, rather not say), the answer one of them, the same metric and period never asked twice, and
two declined questions pausing questions for 14 days; check-ins for today only, 1 to 5 with fixed
tags; facts proposed by the agent and kept only once the person approves (at most 120 characters,
a fixed kind, known metrics, nothing instruction-like, never re-proposed once declined). `expire()`
enforces the 90, 180 and 365 day lifetimes.

**Retrieved into each answer** (`context.select_memory`, `memory.memory_items`). Routing comes first,
so the metrics in play are known: the lead's own and the ones it reads, and its consults'. Current
findings, answers (not "rather not say") and approved facts whose metrics overlap them are scored
on relevance, recency (halving every 30 days) and importance (a finding's effect size; what the
person confirmed counts fully); preferences always come, at most three; at most five items in all,
within the same token budget as the conversation. A finding's evidence is re-attached and counts as
its metric's owner's. The trace lists what was retrieved, and approved facts that went into a run
are marked used, so unused ones fade out after 60 days.

**Proposing facts.** The agent has a `propose_fact` tool for something lasting the person stated
about themselves (never inferred from the data), at most one per answer, checked against the fact
rules (`facts.py`). Proposals come back with the answer for the person to approve; the agent never
writes memory. Check-ins as data the tools can analyse come with the recovery score.

### Write path

| Source | Can it write memory? |
|---|---|
| The person (answers, check-ins, approved facts, preferences) | yes |
| The verifier (only claims that passed) | findings only |
| The agent | only **proposals** (`propose_fact`), which wait for the person's approval |
| External text: food names, entries from other apps, imported files | **never**, directly |

Every stored item keeps its provenance (who wrote it, which run, when).

### Injection defenses

- External and stored text is passed to the model as **quoted data** inside a delimited block
  marked as data, never in the system prompt; it is length-limited and stripped of control
  characters.
- Text that reads like an instruction ("ignore previous instructions", role tags, URLs) is dropped
  from memory candidates and logged.
- Analysis tools only read statistics. Logging tools can prepare owned drafts but cannot confirm,
  execute or undo Google writes. Nothing in the model's reach can approve memory, change settings
  or reach another user's data.
- The router (Jev) receives the question text only, never data or memory.

### How it is evaluated

Memory on against off on scenarios that need it (follow-up questions, a change explained by an
earlier context answer); stale memory (a superseded finding must not be used); poisoning attempts
(a food name carrying an instruction, a proposed fact the person declined); retrieval precision
(share of retrieved items that were relevant) and context size per run.

## Boundaries

| Agentic | Deterministic | Human-controlled |
|---|---|---|
| choosing what to investigate, forming and testing hypotheses, writing findings | ingestion, statistics, verification, authorization, data access | confirming context the data cannot show, approving consequential actions, acting on insights |

The agent describes patterns in the user's own data. It does not give medical diagnoses or advice.

## Data and privacy

The repository is public. Personal exports live under `data/` or `Takeout/`, both git-ignored, and
are never committed; so are `.env` (the OAuth client ID and secret, the token encryption key) and
the owner's Google sign-in token in `data/`. Passwords are stored as scrypt hashes, session tokens
as hashes, Google tokens encrypted; no request returns another person's data or chat. The analysis
LLM receives aggregated statistics, never raw sensor rows or account data. The planned logging
flow also needs user-supplied entry details; optional photo estimation has the separate consent
and retention requirements above. Tests and evaluation use the synthetic generator, whose
baselines are generic values, not taken from any real export.
