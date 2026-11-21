# Model and API costs

The project runs on small prepaid budgets: **about $5 on OpenAI and $5 on TypeSafe (Jev)**. Treat
every paid request as spending real money that cannot be topped up casually.

## Rules

- **Tests and CI never call a paid API.** They use `ScriptedLLM` and fake HTTP transports.
- **Real runs only when model behaviour is what changed**, and as few as possible: one or two per
  pull request, on synthetic data unless the real data is the point. Never loop real runs.
- **Report the cost of every real run** (in the PR and in the log below). `AgentResult.budget`
  and `trace_json` give model calls, tool calls and dollars.
- **Free calls first**: listing models (`GET /v1/models` on both APIs) checks a key without
  spending anything.
- Every run has a `Budget` (default 12 model calls, $0.05); raise it only on purpose.
- `FA_LLM_SPEND_CAP_USD` (set to 4 in `.env`) refuses calls once reached. **It is counted per
  process for now**, so it does not add up across commands; until spending is recorded in the
  database (planned with tracing), keep the log below current by hand.

## Estimated cost per request

Measured on 2026-10-21 where noted; otherwise from published prices.

| Request | Model | Estimate |
|---|---|---|
| Daily check when nothing changed | none: the screen is deterministic | $0 |
| Investigating a change (general agent) | `gpt-5.4-mini` | ~$0.02–0.03 (measured: $0.024, 8 model calls, 14 tool calls, 27 s) |
| Simple chat question | `gpt-5.4-mini` | ~$0.005–0.01 |
| Expert answer, quick, no consult | `gpt-5.4-mini` | ~$0.01 (measured: $0.0086–0.0134, 4–6 model calls, about 10 s) |
| Expert answer with a consult | `gpt-5.4-mini` | ~$0.02 (measured: $0.0169–0.0261, 7–11 model calls, about 19 s) |
| Write-up with the large model, one call | `gpt-5.5` | ~$0.04–0.05 |
| Routing one question | Jev | ~$0.00003 (measured: topic plus four yes/no questions, median 0.21 s) |
| Checking one answer for advice | Jev | ~$0.00004 (4 to 5 sentences per call) |

Prices used for cost accounting are in `backend/app/agent/llm.py` (`PRICES`; per million tokens:
`gpt-5.4-mini` $0.75 in / $4.50 out, `gpt-5.5` $5 / $30). The model list on 2026-10-21
confirmed `gpt-5.4-mini`, `gpt-5.4`, `gpt-5.4-nano` and `gpt-5.5` are available to the key.
TypeSafe's model list (`jev-latest`, `jev-preview`) has no prices; the Jev estimate uses the
published $0.042 per million input tokens, output free.

## Budget plan to the demo (OpenAI, about $3 of $5)

| Use | Estimate |
|---|---|
| Development real runs (1–2 per PR) | ~$1 |
| One full evaluation: ~20 synthetic scenarios × 3 model-based setups | ~$1.50 |
| Router comparison: 100 labeled questions (Jev ~$0.003, LLM router ~$0.10) | ~$0.10 |
| Demo rehearsal | ~$0.25 |

Larger evaluation and user-testing runs in the final week need a top-up, decided then.

## Spend log

| Date | What | Cost |
|---|---|---|
| 2026-10-21 | OpenAI and TypeSafe model lists (key checks) | $0 |
| 2026-10-21 | First real investigation, synthetic person (sleep drop with later bedtime) | $0.024 |
| 2026-10-21 | Readable findings check, same synthetic person (3 model calls, 10 tool calls) | $0.0096 |
| 2026-10-23 | Recovery expert, deep, synthetic person (4 model calls, 22 tool calls; all claims rejected: ids in the text) | $0.0217 |
| 2026-10-23 | Sleep expert, deep, same person after the fix (7 model calls, 16 tool calls; 3 verified claims, no consult) | $0.0152 |
| 2026-10-23 | Sleep expert, deep, after listing other experts' metrics (10 model calls, 17 tool calls; consulted recovery, 4 verified claims) | $0.0247 |
| 2026-10-23 | Jev routing checks, 16 made-up questions: topic only (14/16), then topic and per-expert needs (16/16 on the lead, 14/16 exact), 50 calls in all | $0.0013 |
| 2026-10-23 | Routed answer end to end, quick, synthetic person: Jev led with recovery and consulted sleep; all claims rejected (display names in the claims' metric field) | $0.0204 |
| 2026-10-23 | Same after the name fix: routing right again, 0 claims (null result written as an association; the consult's tool calls all refused by a budget bug) | $0.0207 |
| 2026-10-23 | Same after both fixes: 4 verified claims, consult used | $0.0188 |
| 2026-10-23 | Consult policy A vs B: 4 questions × 2 variants × 2 runs ([experiments.md](experiments.md#consult-policy-a-vs-b-2026-10-23)) | $0.2435 |
| 2026-10-23 | Verifier metric check: sleep expert asked about HRV, no consult (4 verified claims) | $0.0081 |
| 2026-10-23 | Follow-up routing, 8 conversations × 2 settings, Jev | $0.0005 |
| 2026-10-23 | Two-turn conversation end to end (sleep, then "What about on weekends?") | $0.0156 |
| 2026-10-23 | Advice guard on the 32-sentence set, Jev | $0.0002 |
| 2026-10-23 | Two-turn conversation again with the guard on (OpenAI $0.0197, Jev guard $0.0001) | $0.0198 |
| 2026-10-24 | Per-run correction: conversation, a traced rerun of turn 1, and turn 1 after the repair hint | $0.0371 |
| 2026-10-24 | Coverage and summary checks: exercise question, two-turn conversation, exercise question again | $0.0551 |
| 2026-10-24 | Memory retrieval and fact proposals: two runs with stored memory | $0.0226 |
| 2026-10-24 | Chat API end to end on the owner's live data (quick, routed to sleep by Jev, 4 verified claims, 11.3 s) | $0.0113 |
| 2026-10-24 | Request-intent routing: one synthetic mixed nutrition log/analysis message, Jev (Nutrition + mixed, 0.351 s; no Google writes or OpenAI calls) | $0.000048342 |
| 2026-10-24 | Logging tools, synthetic meal with no history: draft prepared, but model finished without submission (5 calls); OpenAI $0.005649, Jev router/guard $0.000067410; no Google writes | $0.005716410 |
| 2026-10-24 | Same after explicit logging-completion instruction: one draft, submitted in 2 calls; OpenAI $0.002841150, Jev router/guard $0.000066948; no Google writes | $0.002908098 |
| 2026-10-25 | First real Google write, owner's app session: "log a snack" (asked for the time), the time reply (misread as a sleep question), the same in one message (draft) | $0.0166 |
| 2026-10-25 | Answer and time fixes, owner's data: the sleep question again (one natural reply, 4 claims), "log a snack… just now" (still asked for the time: the tool's own description said to) | $0.0140 |
| 2026-10-25 | "Log a snack… eaten just now" after the tool-description fix: draft at the current local time with no question back (draft cancelled) | $0.0076 |
| 2026-10-25 | First real workout write: "Log a 20 minute walk that ended just now" (one answer, draft; confirmed, read back and undone) | $0.0104 |
| 2026-10-25 | "am i recovered today?" with compare_day and carried consult claims (owner's data, run through ask() directly: the app's daily cap was reached; 9 day claims, 4 carried from Sleep) | $0.0304 |
| 2026-10-25 | Any workout type: "45 minutes of kickboxing yesterday at 6pm" (KICKBOXING draft; showed the wrong "not covered" note and a repair round) and "tennis for an hour this morning at 9" after the fix (TENNIS draft, no note); both cancelled | $0.0134 |
| 2026-10-26 | Scores in Ask, synthetic person: a stress question (recovery, 5 verified claims, $0.0113) and a strain question (activity, 4 verified claims, 10 calls, $0.0422) | $0.0535 |
| 2026-10-26 | Team report prose, synthetic team of 8: two rejected runs (labels for keys; too many paragraphs for the form), then a passing one after the fixes (third run approved) | $0.0155 |
| 2026-10-27 | Questions about the chat itself, made-up text: Jev routing of 10 questions (10/10; $0.000544) and one recall answer from OpenAI ($0.000548) | $0.0011 |
| 2026-10-27 | Agent voice, synthetic person and made-up messages: the reaction to an unclear workout-and-meal message ($0.0004), a workout-and-meal log request (two drafts, $0.0059), a sleep question ($0.0130), and that question again with its trace ($0.0108) | $0.0301 |
| 2026-10-28 | Reminders through the agent, made-up requests and a synthetic person: four requests ($0.0136; the Fitbit alarm request was refused as off-topic), then again after putting reminders in the router's scope ($0.0124) | $0.0260 |
| 2026-10-28 | Smart alarm explanations, synthetic people: a planted short night with a late bedtime (sleep expert, $0.0104) and a 3-day resting heart rate rise (recovery expert, $0.0128) | $0.0231 |
| 2026-10-28 | Advice guard on the medical/coaching split, two runs, Jev | $0.0005 |
| 2026-10-28 | Coaching with the new tools, synthetic person with a planted bedtime-efficiency link: "sleep better" and "recover faster" twice ($0.0317, $0.0305), and a traced rerun ($0.0123) | $0.0745 |
| 2026-10-28 | Strategy per question type, six made-up questions (day, lookup, two coaching, pattern, why) on a synthetic person | $0.0420 |
| 2026-11-05 | Chat summary, made-up chat of five turns: two folds ($0.0011; the second lost the exams and the goal), then again after fixing the prompt ($0.0015) | $0.0027 |
| 2026-11-05 | Memory listener, made-up messages: nine ($0.0050), then eleven with the medical guard after the fixes ($0.0064), plus about $0.0006 of Jev guard calls | $0.0120 |
| 2026-11-05 | Profile and memory search, synthetic person, four made-up questions (change, lookup, a question about another chat, why) | $0.0353 |
| 2026-11-05 | Knowledge cards: medical guard on all cards, twice ($0.0003), and "How can I sleep better?" twice on a synthetic person ($0.0067, about $0.008) | $0.0150 |
| 2026-11-05 | Outside lookups, made-up questions: five (one USDA, two web, two refused, $0.0620), then one web question after the fix ($0.0330). Web cost counts each search at $0.025, the higher published figure; check the OpenAI dashboard for the real charge | $0.0950 |
| 2026-11-05 | Chat evaluation, synthetic person: 62 questions, 16 listener messages and 4 recall questions ($0.6151), three questions to find why summaries failed ($0.0147), and eleven again after the fixes ($0.1081), plus about $0.01 of Jev | $0.7479 |
| 2026-11-05 | Advice comparison, two synthetic people: 18 coaching answers three ways, 3 plain questions and an alert | $0.3632 |
| 2026-11-05 | First real-data check, the owner's Takeout export, six questions (`eval/real_check.py`; answers stay in git-ignored `data/`) | $0.0725 |
| 2026-11-05 | The no-answer question twice on the owner's export ($0.0107), then the six-question real-data check again ($0.0869) | $0.0976 |
| 2026-11-08 | Workout logging as in the bug report, made-up person: three conversations ($0.0262), then the request given one detail at a time and a change of topic after the fixes ($0.0166) | $0.0428 |
| 2026-11-08 | Whole-agent evaluation through the API, made-up person (`eval/agent_eval.py`): a pass stopped by the app's own daily cap ($0.13), three full passes of 74–75 turns around two rounds of fixes ($0.49, $0.52, $0.54), a final pass ($0.52), a smoke run and a diagnostic run (about $0.08), plus about $0.1 of background summaries and memory listening | about $2.40 |
| 2026-11-08 | RAG: guard review of the passages, three runs ($0.037), embeddings ($0.0038), retrieval evaluation (under $0.01), with and without retrieval on a made-up person: 100 answers ($0.81, how-to questions mostly refused by the router), the how-to set again after the fix ($0.33), and routing and safety again ($0.08), plus a smoke run (about $0.03) | about $1.30 |
| 2026-11-08/09 | Personalization and open fixes, made-up people: five people and five questions ($0.24), three questions again ($0.14), whole-agent pass ($0.61), two targeted passes ($0.19, $0.08), two traced questions (about $0.02) | about $1.28 |
| 2026-11-09 | Everyday advice quality, made-up person: nine scenarios ($0.11), two again after the fixes ($0.03) | about $0.14 |
| 2026-11-09 | Life rules, premise check and more nutrition: embeddings ($0.004), a look at simple questions ($0.03), the whole agent three times, 246 turns ($0.57, $0.48, $0.45), and the failed scenarios again ($0.05) | about $1.58 |
| 2026-11-10 | Points, drafts and follow-ups: the banana request five times ($0.02), nine scenarios after the fixes ($0.06) | about $0.08 |
| 2026-11-10 | Real-data evaluation, LifeSnaps and PMData: a 15-question pilot ($0.11), tracing its failures ($0.03), the full run, 472 questions from 46 people with a plain chatbot on 187 of them ($3.33) | about $3.47 |
| 2026-11-10 | Three systems on PHIA's questions and planted causes: a six-question try ($0.10), full system and bare agent on 160 ($1.97), no experts on 136 and 20 planted-cause questions on all three ($1.27), a baseline trial stopped early ($0.01) | about $3.35 |
| 2026-11-10 | Separated experts against no experts: 100 real-people questions ($1.59), a three-question try ($0.06), the whole agent with and without experts, 85 turns each ($0.43, $0.41) | about $2.49 |
| 2026-11-10 | The hybrid against no experts: 95 real-people questions on both ($1.78), the same 33 why questions on the code before the fixes ($0.41), the whole agent with the hybrid, 85 turns ($0.47), the team agent tried live ($0.05), tracing failed expert answers and one PHIA question ($0.03) | about $2.74 |
| 2026-11-11 | Memory evaluation (`eval/memory_eval.py`): first full run ($0.32 with the chats it deleted), reruns of what failed ($0.40), two final full runs ($0.57), reruns after reading the answers ($0.13), checks on the listener and guard ($0.01) | about $1.43 |
| 2026-11-12 | Team agent evaluation (`eval/team_eval.py`): 33 privacy attacks twice ($0.10, $0.02), planted team changes twice ($0.05 each) | about $0.22 |
| 2026-11-14 | Conversation evaluation (`eval/conversation_eval.py`, synthetic person, real chat API): a four-turn trial ($0.014), run 1 stopped halfway by the app's per-person cap ($0.12), runs 2 to 4 after fixes, 47 to 62 turns each ($0.25, $0.32, $0.32 with the judge), listener checks on three messages ($0.002) | about $1.02 |
| 2026-11-16 | Agent tuning round, baseline: the conversation evaluation widened to 104 turns (PHIA questions, edge cases, languages, logging, reminders, memory changes) on PR #163's code ($0.54 with the judge), a check of which model settings the API accepts ($0.002), one replay of a failed turn ($0.01) | about $0.55 |
| 2026-11-16 | Agent tuning round against the course notes (C2-C6): re-judging the baseline twice to measure the judge ($0.11), a trial of the first fixes, 43 turns ($0.28), configuration probes of 27 turns each (defaults twice, temperature 0.4, gpt-5.4; $1.03 with judges, a reasoning-effort probe that the API refused, $0.02), the real-people why questions before and after code-tested causes ($0.36, $0.38), the full 104-turn run ($0.59, plus $0.10 for a run that crashed on an HTTP error), a targeted confirmation of 32 turns ($0.25), and short replays to trace single failures (about $0.25) | about $3.35 |
| 2026-11-16 | PHIA benchmark checks before any batch (`eval/phia_bench.py`): the four systems live on two questions ($0.05) and four real-people questions ($0.09), three count questions after the counting-tool fix ($0.01) | about $0.15 |
| 2026-11-16 | PHIA real people: batch 1 first 20 ($0.37), traces of two misses ($0.02), the rest of batch 1 ($3.96); the totals fix checked on 8 failures and 40 regressions ($0.15); the team agent's Monday run on made-up teams, eight runs ($0.08) | about $4.58 |
| 2026-11-18 | PHIA mode A, batch 3 on PHIA's 4 users: first 20 ($0.22), then the rest ($2.95) | about $3.16 |
| 2026-11-19 | Structured requests on PHIA: A1 50 questions three times ($0.06, $0.07, $0.07), A2 50 once ($0.07), three spot checks ($0.02) | about $0.29 |
| 2026-11-18 | Follow-ups after the audit fixes: the audit's conversations ($0.06), held out once ($0.08) | about $0.14 |
| 2026-11-18 | Broad questions: a 10-answer trial ($0.06), one replay ($0.01), development before and after fixes ($0.35, $0.39), held out once ($0.47); PHIA regression, 50 questions ($0.14) | about $1.42 |
| 2026-11-18 | PHIA mode A, batch 2 on PHIA's 4 users: first 20 ($0.24), then the rest ($2.88) | about $3.13 |
| 2026-11-18 | Logging test at scale: 250 generated requests through the chat API | about $0.81 |
| 2026-11-17 | PHIA mode A, batch 1 on PHIA's 4 synthetic users: first 20 ($0.21), then the rest ($2.78); grader's reading timed apart | about $2.99 |
| 2026-11-17 | PHIA real people, batch 2: 39 questions on the code before the totals fix ($0.45, stopped), then the batch on the fixed code with Patterns asked again on those 39 ($3.79) | about $4.24 |
| 2026-11-17 | Meal logging fix: replays of Karim's chicken-and-rice conversation (six, $0.07), food ranking on 45 and 25 held-out foods with embeddings and the model's choice (about $0.03) | about $0.10 |
| 2026-11-17 | Team warning before a noted crunch: about 30 Monday runs on made-up teams while measuring and fixing it | about $0.35 |
| 2026-11-16 | Router on 152 held-out questions, Jev twice ($0.0124, $0.0125); RAG on the second held-out set and ten borderline queries (embeddings, under $0.01) | about $0.03 |
| 2026-11-18 | Structured requests, synthetic smoke: 10 answers and 5 reader-only checks; 14/15 checks, one access-limit miss fixed | $0.011193492 |
| 2026-11-18 | Structured requests, first fresh synthetic set: 83 turns, 72 automated passes; direct source review also found a variant mismatch. No paid judge or Google writes | $0.061797732 |
| 2026-11-18 | Constrained reader and variant selection, fresh 78-turn set: 75 strict passes, all 34 metric/date-shift pairs correct | $0.081097904 |
| 2026-11-18 | Request-capability repair: 4 fresh probes plus 78 regression turns, 80/82 strict passes; two remaining contract failures fixed | $0.094112192 |
| 2026-11-18 | Final threshold/food contract regressions: 4/4 passes; no new overall accuracy claim | $0.006452634 |

These implementation checks total **$0.254653954** (OpenAI $0.232608700, Jev $0.022045254).
Including the earlier independently requested audits (about $0.4588 and $1.330020434), the shared
$3 request is at about $2.04. See [methods, failures and limits](typed-requests.md). All new data
is made up; provider-reported usage is logged and raw runs remain under ignored `data/eval/`.


## Independent candidate audit — November 19, 2026

Karim authorized a new, separate **$2 maximum** for testing Claude's latest PR #195 head
(`fa15f4a`), including direct review and a local Markdown handoff.

| Date | Run | Metered upper estimate |
|---|---|---:|
| 2026-11-19 | Independent candidate audit v3 on Claude’s PHIA-fixed `fa15f4a`: 463 turns in 183 conversations, 347 fresh / 116 exposed regressions, all 34 metrics and four public histories; every answer directly reviewed | $0.855184784 |
| 2026-11-19 | Additional coverage diagnostics, frozen separately before execution: 25 turns; null/positive/constant/disjoint associations, same-night references, two windows, hour/minute thresholds, mixed read/log and source boundaries | $0.055229928 |

Combined recorded estimate **$0.909444218** (OpenAI **$0.866389430**, Jev **$0.043054788**),
plus **$0.000970494** held for uncertain failed-call charges: conservative upper total
**$0.910414712**, leaving **$1.089585288** of this allowance. The supplement ran only after
the main process finished and was capped at the unused portion including main uncertainty.
The initial usage-limit approval-review block did not execute the command and cost $0.
No paid model judge or Google traffic/writes. Scripted offline preflights cost $0 and are
excluded from accuracy. All 488 actual replies were reviewed; all raw artifacts remain under
ignored `data/eval/`. See [the completed local handoff](independent-audit-v3-handoff.md) for
cohort scores, independent recalculations, grading corrections and limitations.


## Independent post-redesign audit — November 19, 2026

Within the unused portion of Karim's separate $2 allowance, tested PR #195 head `84db5f5`.

| Run | OpenAI | Jev | Total estimate |
|---|---:|---:|---:|
| Fresh frozen synthetic API conversations, 211 turns / 78 conversations; direct answer, independent row/evidence and state review | $0.386967800 | $0.019739496 | $0.406707296 |
| Frozen 24-item PHIA B1 regression gate, including four conservative-reservation blocks and their later completion; no completed answer repeated, no paid judge | $0.048681150 | $0.002340660 | $0.051021810 |

New total **$0.457729106**, no uncertain reservations outstanding. Together with the earlier
$0.910414712 conservative upper estimate: **$1.368143818 of $2**, leaving **$0.631856182**.
The user explicitly approved the PHIA public-health-derived data transfer after automatic review
initially blocked it; the rejected command made no paid calls. Shared-budget reallocation and all
original blocked outputs are retained. Offline tests, preflight and memory API diagnostics cost $0.
No Google traffic/writes, merge, deploy or full PHIA batches. See
[independent-audit-v4-handoff.md](independent-audit-v4-handoff.md) for per-area grades, failures,
methods and limitations; raw inputs/outputs remain under ignored `data/eval/`.

### 2026-11-19: request-reader replay of the v4 audit's misses

Within the same $2 allowance, approved with a hard $0.07 cap. Only the request reader (`gpt-5.4-mini`),
on the 47 failed/partial turns of the v4 audit and 11 passing controls, with each turn's original
question, profile date, earlier turns, saved request state and waiting-card flag
(`eval/reader_replay.py`). Readings kept under ignored `data/eval/reader_replay_2026-11-19/`.

| Run | OpenAI | Total |
|---|---:|---:|
| 58 reader-only turns (the 59th stopped at the cap) | $0.0675 | **$0.0675** |

Allowance: $1.368143818 + $0.0675 = **$1.4356 of $2**, leaving **about $0.564**.

### 2026-11-19: smoke run of the clause reader

Approved with a hard $0.03 cap. Request reader only, 20 turns ([reader-smoke-2026-11-19.md](reader-smoke-2026-11-19.md)),
then a recheck of one stop-rule turn after its fix.

| Run | OpenAI | Total |
|---|---:|---:|
| 20 reader-only turns, one call each | $0.0249 | $0.0249 |
| Recheck of `calendar_rollover-02/t3` (sent back once, then right) | $0.0050 | $0.0050 |
| **Smoke total** | | **$0.0299** |

Allowance: $1.4356 + $0.0299 = **$1.4655 of $2**, leaving **about $0.534**.

### 2026-11-19: live re-check of the two smoke fixes

Approved with a hard $0.007 cap. Request reader only, two turns, each run once.

| Run | OpenAI | Total |
|---|---:|---:|
| `privacy_memory-01/t2` and `calendar_rollover-01/t3`, two calls each (one retry) | $0.0062 | **$0.0062** |

Allowance: $1.4655 + $0.0062 = **$1.4717 of $2**, leaving **about $0.528**.

### November 20, 2026 — PR 195 independent conversation audit and PHIA gate

Frozen candidate `7ef95c7`. Upper-bound spend was $0.192801780 for the initial conversation run, $0.028625010 to complete the 22 budget-blocked turns and $0.031907418 for the 24-question B1 gate. Total **$0.253334208**. Cumulative spend is approximately **$1.7250 of $2**, leaving **$0.2750**. Results and limitations are in [the audit handoff](independent-audit-v5-handoff.md).

### November 20, 2026 — PR 195 v6 fresh audit and PHIA gate

Frozen candidate `9684d77`. The first 36 conversation turns cost $0.122029424 and the 24-question PHIA B1 run cost $0.038393718. Four expansion shards cost $0.105157540, $0.135743342, $0.099541266 and $0.072930334. Replacing six meal turns after correcting the evaluation fixture cost $0.008667570. Total **$0.582463194**. With the approved additional $2, cumulative spend is approximately **$2.3075 of $4**, leaving **$1.6925**. Results are in the [v6 audit handoff](independent-audit-v6-handoff.md).

### November 20, 2026 — Claude's own live checks while Codex was away (v7, v8)

Same harness, oracle and grading rules as v6; graded by Claude, who wrote the code, so not
independent. v7 on `4582185` (226 turns): $0.381964. v8 on `5f51a36` with the gpt-5.4-nano
read-back, stopped after 34 turns when it rejected correct readings: $0.093391. The same frozen
v8 deck on `0d858a0` with the read-back off (94 turns): $0.256848. Total **$0.732203**. Cumulative
spend is approximately **$3.0397 of $4**, leaving **$0.9603**. Results are in
[typed-requests.md](typed-requests.md#explicit-anchors-instead-of-word-checks-2026-11-20).

### November 20, 2026 — independent audit of the frozen redesigned reader

On `b730fda`, 110 fresh synthetic conversation turns cost $0.325881382. The separate 24-question B1 gate cost $0.034121418. Total **$0.360002800** against the predeclared $0.935 ceiling. Cumulative spend is approximately **$3.3997 of $4**, leaving **$0.6003**. See the [independent audit handoff](independent-audit-b730fda-handoff.md).

### November 21, 2026 — focused independent live audit on a196c6d

86 fresh turns in 36 synthetic chats cost **$0.286983744** ($0.278319480 OpenAI and $0.008664264 Jev), within the $0.59 cap. The reopen checks incurred no paid calls. Cumulative audit spend is approximately **$3.6867 of $4**, leaving **$0.3133**. See the [audit handoff](independent-audit-a196c6d-handoff.md).

### November 21, 2026 — matched reader comparison on the edit slice (Claude)

Reader-only calls (gpt-5.4-mini, no agent run) on the 48 historical date follow-ups and 6 workout
edits: two price probes $0.009252, the edit reader $0.066747, the current reader at `a196c6d`
$0.091011 (stopped at its $0.09 cap after 36 cases), and the edit reader with a required length
$0.080902 (stopped at its $0.08 cap after 41 cases). Total **$0.247912**. Cumulative spend is
approximately **$3.9346 of $4**, leaving **$0.0654**. Results are in
[typed-requests.md](typed-requests.md#edits-to-an-earlier-result-or-card-2026-11-21).

### November 21, 2026 — independent audit on 9228fe6

88 fresh synthetic chat turns cost $0.232728534 and 24 frozen PHIA B1 questions cost $0.036339018. Total **$0.269067552** of this audit's $2 authorization. Offline grading and reopening incurred no API charges. See the [audit handoff](independent-audit-9228fe6-handoff.md).

### November 21, 2026 — post-audit diagnostic probes on 9228fe6

Matched reader, calendar and exercise-selector probes recorded $0.248385800 in returned usage. Combined with the preceding audit, confirmed spend is $0.517453352 against the same $2 cap. Two diagnostic meters retain $0.603452250 in unresolved reservations, including a reproduced HTTP 400 for unsupported reasoning effort with function tools. These reservations are an upper bound, not confirmed charges. Conservative remaining allowance is $0.879094. No paid diagnostic result is a release score.

### November 21, 2026 — independent audit of b3d64ca

Frozen candidate `b3d64ca33f7da5992890b20dd290c6bace660955`: 90 fresh synthetic API turns
cost **$0.308799922** (OpenAI $0.299549590, Jev $0.009250332); the frozen 24-item PHIA B1
regression gate cost **$0.043868418** (OpenAI $0.041856450, Jev $0.002011968). Combined
**$0.352668340**, within the user's explicit $0.65 approval and the existing shared $2 allowance.
The initial automatic approval rejection did not execute and cost $0. New unresolved reservations:
$0. Including the earlier $0.603452250 unresolved reservations, conservative cumulative usage
is **$1.473573942 of $2**, leaving **$0.526426058**. No paid judge, Google traffic or writes;
offline replays/tests/preflight/reopening cost $0. Results and limitations are in the
[b3d64ca independent handoff](independent-audit-b3d64ca-handoff.md): HOLD; 83 full, 1 partial,
6 failed of 90 fresh turns; PHIA 24/24. The prior diagnostic runs remain development results.

### November 21, 2026 — next-audit authorization and planning

The user authorized a **new $5 maximum across the next audits**, with broader question coverage.
This is a forward-looking shared cap, not $5 per run; the previous approximately $0.526 remaining
is not added to it. Earlier usage and unresolved reservations remain recorded above. This
planning/code review cost **$0**, leaving the new **$5.00** unspent. Proposed allocations:
$0.75 matched development diagnosis, $3.50 fresh broad conversations, $0.25 PHIA B1 and $0.50
uncertainty/confirmation reserve, all under one combined meter. No paid run started. See
[the general repair and expanded audit plan](pr-195-general-repair-plan.md).

### November 21, 2026 — expanded independent audit of 689fa7c

Against the user's new shared **$5** authorization: the 22-input matched reader development
comparison cost **$0.074579400**; 592 fresh synthetic API turns in 234 conversations cost
**$1.409913034**; the frozen 24-item PHIA B1 gate cost **$0.045561318**. Combined
**$1.530053752** (OpenAI $1.472697460, Jev $0.057356292), with **$0 unresolved reservations**,
leaving **$3.469946248** for subsequent audits. The prior balance is not added. Backend/failure
tests, source-row checks, adapter probes and reopening cost $0. No paid judge or Google
traffic/writes. Automatic approval review initially rejected the PHIA invocation before any
calls; the user then specifically approved the public health-derived payload transfer to OpenAI
within the existing cap. That gate ran once: **23/24**, one regression within the predeclared
allowance. See the [689fa7c handoff](independent-audit-689fa7c-handoff.md): HOLD; 504 full,
33 partial and 55 failed fresh turns, with every delivered answer reviewed and messages/citations
reopened. The PHIA result does not clear the fresh audit's named-period and other release blockers.

### November 22, 2026 — e1c1eec matched-reader development comparison

Frozen candidate `e1c1eec0535c013b103ad33088bf41492ef24f1c` versus baseline `689fa7c` on
152 exposed synthetic inputs per arm. The baseline cost **$0.227755200** and candidate
**$0.343948800**: combined **$0.571704000**, entirely OpenAI reader calls, below the predeclared
combined $0.75 ceiling. No paid judge, embeddings, web lookup, PHIA or Google traffic/writes.
Offline tests, renderer probes and counterfactual/fixture checks cost $0.

Shared new-$5 cumulative spend is **$2.101757752** (OpenAI $2.044401460, Jev $0.057356292),
with **$0 unresolved reservations**, leaving **$2.898242248**. Common-field request matches
improved 103/150 → 133/150 (42 improved, 12 spoiled); the two new duration-basis cases are
reported separately. These are development extraction checks, not held-out answer accuracy.
The successor-block category regressed 12/12 → 3/12, and a deterministic renderer issue remains.
No fresh release audit ran. See the [e1c1eec handoff](independent-audit-e1c1eec-handoff.md).

### November 22, 2026 — bcdb0ff matched-reader development comparison

Frozen `bcdb0ffb205effdc4e3145d89400a0454eab2482` versus `e1c1eec` on the same 152 exposed
synthetic inputs per arm, with complete stored claims attached to both arms before freezing.
Baseline **$0.339550950**, candidate **$0.272442000**: combined **$0.611992950**, under the
predeclared combined $0.75 ceiling. All 304 inputs completed, with 324 reader completions including
interpretation retries. No paid judge, embeddings, web lookup, PHIA or Google traffic/writes.
Offline review, probes and 2,685 backend tests cost $0.

Shared new-$5 cumulative usage is **$2.713750702** (OpenAI $2.656394410, Jev $0.057356292),
with **$0 unresolved reservations**, leaving **$2.286249298**. Strict request matches improve
138/152 → 146/152 (common fields 136/150 → 144/150; 11 improved, three spoiled). One strict
workout mismatch is action-equivalent in an independent actual-edit control; the frozen score is
retained. This is development extraction coverage, not held-out answer accuracy. HOLD: coaching
renderer, compound dispatch, duplicate state and semantic reader misses remain. No fresh release
audit ran. See the [bcdb0ff independent handoff](independent-audit-bcdb0ff-handoff.md).
