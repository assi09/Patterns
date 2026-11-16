# Testing plan to the demo

Written 2026-11-16. What is tested, on what, against what, and when, from now to the presentations
on 2026-12-05. The methods and the reasons behind them are in [evaluation-plan.md](evaluation-plan.md);
results go to [evaluation.md](evaluation.md), every paid run to [costs.md](costs.md) and
[experiments.md](experiments.md).

The PHIA benchmark is one part of this plan. It defends the data answers end to end. The parts that
have a job of their own (the verifier, RAG, logging, the router, "why", memory, safety) are also
tested on their own, and the pilot then tests everything on real users.

## What was done on 2026-11-16

- **Tuning round merged** (#163, #164): the agent's failures were in the harness, not the model.
  Code now names dates, refuses what the data cannot answer, and tests every likely cause of a
  "why". Why answers on real people went from 16 to 28 of 33. Details in
  [experiments.md](experiments.md#tuning-the-agent-against-the-course-notes-before-any-fine-tuning-2026-11-16).
- **Pilot caps set on Railway:** $0.50 per person a day, $5 a day in all, $50 overall.
- **PHIA chosen as the main benchmark for data answers**, after checking it against the course's
  requirement (real public data, an independent answer key, baselines). It is peer-reviewed (Merrill
  et al., *Nature Communications* 2026, Google Research) and the closest published benchmark to what
  the app does; it is recent, so it is described as such, not as a widely used standard.
- **The benchmark pipeline built** (`eval/phia_bench.py`, PR #165), checked before any paid batch:
  - the answer key: PHIA's published answers reproduced, 1,603 of 1,603; a second, separate
    implementation agrees with every real-people answer;
  - PHIA's own key errors found and dropped: 45 questions whose code disagrees with their words
    ("sleep less than 3 hours" coded as at least 3 hours; light-sleep questions computed on total
    sleep);
  - questions that prove nothing dropped (totals of heart rates, "how many days" within one day,
    thresholds nobody reaches), and a question goes to a real person only when they have the metric
    on 80% of the days it asks about;
  - all four systems tried live on a few questions ($0.15): each takes the data and answers;
  - grading checked twice: a reading model blind to the system and the key, and code reading every
    number in the reply; where they disagree, a person looks.
- **Three bugs found by those checks and fixed:** LifeSnaps sleep stages were invented by our
  loader (status issue 40); counts of days were graded within one instead of exactly; the agent's
  counting tool said it was only for goals, so "how many nights did I sleep under 7 hours?" went
  unanswered.

## The plan

| # | Test | What it shows | Against | Data | When | Cost |
|---|---|---|---|---|---|---|
| 1 | **PHIA, real people** (mode B, 2 batches of ~338) | the right metric, period and figure on real data | single agent; chatbot with the data; code-writing (PHIA's baseline) | PHIA's questions on 58 real people (PMData, LifeSnaps), PHIA's answer logic | once the card is funded; batch 1 starts with 20 questions read by hand | ~$5.40 a batch |
| 2 | **PHIA, PHIA's users** (mode A, 5 batches of ~282) | the same, against PHIA's published key | the same three | PHIA's 4 synthetic users | after B1 looks sound | ~$4.50 a batch |
| 3 | **Verifier, on its own** | it rejects wrong claims and passes right ones | no verifier | claims built by code from real people's evidence, then broken on purpose | before the pilot | free |
| 4 | **RAG retrieval** | the right passage comes back for the query | BM25 alone; embeddings alone | a second held-out set of 39 questions (everyday wording, typos, French, unanswerable) | **done 2026-11-16**, below | under $0.01 |
| 5 | **Logging** | the draft holds what was said: food, meal, day, time, calories; workout type, start, length, distance | none needed: labels come from the generator | 52 generated requests through the chat API: 20 foods, 24 workouts, 8 that must not become a draft | **built**; runs once the card is funded | ~$0.30 |
| 6 | **Router** | each question reaches the right handler | the keyword router | 152 held-out questions (112 ours, 40 PHIA's), plus the type logged on every PHIA answer | **done 2026-11-16**, below | $0.03 (Jev) |
| 7 | **Why** | a cause is named only when one moved | the agent before code-tested causes | causes planted in real people, with no-cause controls | done (28 of 33); rerun only if the code changes | ~$0.40 |
| 8 | **Memory, safety, conversation** | keeps the right things, refuses the right things, sounds right | earlier versions | `memory_eval.py`, refusal and privacy sets, `conversation_eval.py` | after any agent change | ~$1 |
| 9 | **The judge** | its scores mean something | Karim and Jad, grading blind | 50 replies | before the report | free |
| 10 | **Pilot** | the app on real users and their own questions | none: real use | 8-10 testers, about 10 days | after the tests above | live caps ($50) |
| 11 | **Team feature live** | alerts, the team agent and privacy on a real team | the made-up-team results in [teams.md](teams.md) | the pilot's team | during the pilot | inside the pilot caps |

Each test's pass rule is written before it runs. A paid run happens only once a cheap trial of it
has been read.

## The verifier: tested through PHIA, and on its own

PHIA's runs show the verifier **at work**: every Patterns answer records how many claims it rejected,
and Patterns can be compared with the baselines, which have no verifier, on stated numbers that the
data does not hold. That tells us how often it fires. It does **not** tell us whether it fired at the
right time. A rejection may have stopped a wrong number or a right one, and a wrong number that got
through looks just like a right one.

So it gets a test of its own, free and deterministic, because the verifier is code and needs no model:

1. **Right claims must pass.** Code writes true claims from real people's evidence (values, days,
   changes, links) in the forms the agent uses: rounded, in hours and minutes, with dates inside
   the window.
2. **Broken claims must be caught.** Each is then broken one way at a time: a wrong number, a date
   outside the window, a reversed direction, the wrong metric, a change that is not significant,
   "because" or "causes", medical wording.
3. **Reported:** the share caught for each kind of break (recall) and the share of right claims
   wrongly rejected (false rejections).

**First run (2026-11-16, `eval/verifier_check.py`, free):** 3,190 claims from 61 real people.
- **True claims: 1,066 of 1,066 passed**, in every form tried (the app's format, plain minutes,
  decimal hours, rounded counts).
- **Caught every time:** a date outside the evidence, a reversed direction, wording against the
  direction, the wrong metric, a change that is not significant, a "no change" that is wrong, a day
  on the wrong side of the usual range, too little data, causal and medical wording.
- **Missed:** a number 10% or 30% off got through 7-10% of the time, and **the highest day quoted as
  the average got through every time (0 of 163)**. Every miss is the same gap: the verifier checks
  that a number is somewhere in the cited evidence, not that it is the statistic the sentence names.
  The fix would tie "average", "highest", "lowest", "total" and "usual" to their own statistics.

**Fixed and retested the same day.** A number that follows "average", "highest", "lowest", "total",
"median" or "usual range" in the same clause must now be that statistic, and in a claim about one
day, a number with no such word must be the day's own value. It is rejected only when it is a
*different* level in the evidence, so a change's size, a count of days or a window's length after
"average" is left alone.

| | Before | After |
|---|---|---|
| True claims passed | 1,066 / 1,066 | **1,066 / 1,066** |
| Highest day quoted as the average | 0 / 163 | **163 / 163** |
| Number 10% off | 179 / 193 | **193 / 193** |
| Number 30% off | 349 / 386 | **379 / 380** |
| Every other break | 100% | **100%** |
| All broken claims | 89.9% | **99.95% (2,117 / 2,118)** |

Six "30% off" cases were dropped from the test: on days with 0 steps, 30% off is still 0, so they
were not breaks. The one miss left is a coincidence the verifier cannot see: a wrong HRV value that
equals 28, the number of days in the usual range's window. Unit tests for the rule were added
(35 verifier tests; 1,665 in all pass). The risk is in live answers: a true sentence worded in a way
the rule misreads would now be sent back. The first 20 PHIA questions record every rejection, so
they are read for that before the rest of the batch.

The 30 unit tests in `backend/tests/test_verifier.py` already check one hand-written example of each
rule. This test checks the rules on many real claims. An optional extra is Patterns with the verifier
turned off on 100 PHIA questions, about $0.60, which would show what it adds to accuracy. Run it only
if the report needs that number.

## The router, on held-out questions (2026-11-16)

`eval/router_eval.py` on `eval/router_set.json`: 152 questions written after the router was built
and never used to tune it. 112 are ours, covering every route, intent and question type, in English,
French and Arabic, with typos, follow-ups, logging, reminders, medical and off-topic questions and a
prompt injection; 40 are PHIA's own. Labels, with the accepted alternatives where a question is
genuinely ambiguous, were fixed before any router saw them.

| | Jev (the app's router) | Keyword rule (its fallback) |
|---|---|---|
| Right place (action and lead expert) | **150 / 152 (98.7%)** | 126 / 152 (82.9%) |
| PHIA's questions routed right | **40 / 40** | 39 / 40 |
| Question type | **109 / 112** | 70 / 112 |
| Request intent (read, log, mixed, manage, remind, clarify) | 122 / 128 | 108 / 128 |
| Median latency, cost | 0.22 s, $0.0125 for the set | 0 s, $0 |

- **Jev's two misses** are questions spanning two areas ("is there a link between my steps and my
  sleep score?", "add a coffee and how much did I sleep?") sent to the general agent. The router's
  own definition gives "several areas with no main one" to the general agent, so both are arguable;
  they stay counted as misses because the labels came first.
- **Its intent misses** are six coaching questions ("help me build a better bedtime routine") read
  as "unclear". This has no effect in the app: it asks "log it or look at the data?" only for
  statements without a question mark that are not coaching.
- **The keyword rule** misses every non-English question, most logging requests and most
  off-topic ones, and gets a question type for only 63%. It is a fallback for when Jev is down, and
  the gap is the case for keeping Jev.
- **Fixed after the first run:** PHIA's "how many days" questions carry the metric `datetime`, so
  the code that labelled them gave two sleep questions to activity. Labelled from the threshold's
  metric instead; this changed labels only, not the router.

## RAG retrieval, on a second held-out set (2026-11-16)

The first held-out quarter (17 questions) was used on 2026-11-08, so a second set was written:
`eval/rag_heldout_2026-11-16.json`, 35 answerable questions in everyday wording, typos and French,
4 the passages cannot answer (there is no HRV or heart-rate passage) and 4 medical ones. Labels were
checked against the titles present in the index before any search ran. Scored once with
`python eval/rag_eval.py --set eval/rag_heldout_2026-11-16.json`.

| Recall@3, MRR | First held-out (17) | Second held-out (35) |
|---|---|---|
| Old keyword cards | 0.24, 0.21 | 0.14, 0.14 |
| Words alone (BM25) | 0.77, 0.59 | 0.51, 0.44 |
| Meaning alone (embeddings) | 0.88, **0.82** | **0.94, 0.83** |
| Both, the app's search | 0.88, 0.77 | 0.89, 0.76 |

- **Both held-out sets rank meaning alone above the combination the app uses** (MRR 0.83 against
  0.76 on the new set). The combination was chosen on the tuning set, where it led (0.98 against
  0.94). Switching is a one-line change, `MEANING_WEIGHT` in `retrieval.py`, left for a decision.
- **French:** "comment faire une planche" finds nothing in any method: the best match is below the
  similarity floor (0.38). "Combien de protéines par jour" works. The search is given the question
  as asked, so a non-English how-to question can come back empty.
- **Two labels were narrower than the passages:** "pushups for beginners" found "Pushups" (labelled
  "push-up"), and "a good bedtime routine" found "Time to wind down" and "Prepare for Sleep". Counted
  as misses, as labelled.
- **Unanswerable questions** found nothing 2 of 4 times; "what resting heart rate is normal for my
  age" returned exercise guidelines. **Medical questions** found nothing 2 of 4 times; "what pills
  help me sleep" returned general sleep passages. Neither reaches retrieval in the app: Jev refused
  every medical question in the router set, and the verifier rejects medical wording.

## Order and budget

1. **Free, now:** the verifier test (3, done), router labels (6, done), RAG retrieval (4, done), the
   logging generator (5, built), the judge sheet for Karim and Jad (9).
2. **Once the card is funded:** PHIA B1, the first 20 questions, read by hand; then the rest of B1;
   then B2; then mode A. About $11 for B and $22 for A.
3. **Logging and router live runs** (about $0.30), and memory, safety and conversation again only
   if the agent changed.
4. **The pilot and the team feature live.** Its questions become the next test set, read only as
   totals.

Total before the pilot: about $35, nearly all of it PHIA.
