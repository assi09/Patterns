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
