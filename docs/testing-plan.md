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
| 4 | **RAG retrieval** | the right passage comes back for the query | BM25 alone; embeddings alone | 78 labeled queries, plus rewordings | before the pilot | ~$0.05 |
| 5 | **Logging** | the draft holds what was said: food, amount, time, workout, duration | none needed: labels come from the generator | ~60 generated utterances, plus future and incomplete ones | before the pilot | ~$0.30 |
| 6 | **Router** | each question reaches the right handler | the keyword router | ~150 labeled questions, plus the type logged on every PHIA answer | before the pilot | ~$0 (Jev) |
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

## Order and budget

1. **Free, now:** the verifier test (3), router labels (6), RAG retrieval (4), the logging generator
   (5), the judge sheet for Karim and Jad (9).
2. **Once the card is funded:** PHIA B1, the first 20 questions, read by hand; then the rest of B1;
   then B2; then mode A. About $11 for B and $22 for A.
3. **Logging and router live runs** (about $0.30), and memory, safety and conversation again only
   if the agent changed.
4. **The pilot and the team feature live.** Its questions become the next test set, read only as
   totals.

Total before the pilot: about $35, nearly all of it PHIA.
