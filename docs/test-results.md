# Test results

Every test run on the agent, what it shows, on what data, against what, and what it found. One row
per test; the method behind each is in [evaluation-plan.md](evaluation-plan.md), the schedule in
[testing-plan.md](testing-plan.md), the full write-ups in [evaluation.md](evaluation.md) and
[experiments.md](experiments.md), and the cost of each run in [costs.md](costs.md). Results files are
in `eval/results/` (totals only; anything holding a real person's values stays in the git-ignored
`data/eval/results`). Updated 2026-11-19. **Which results are final accuracy and which are
development, and what is left: [progress-2026-11-17.md](progress-2026-11-17.md).**

## At a glance

| Test | What it shows | Data | Compared with | Result | When |
|---|---|---|---|---|---|
| **PHIA benchmark, real people, batch 1** (development) | right metric, period and figure | 338 of PHIA's questions on 48 real people (PMData, LifeSnaps), PHIA's answer logic | single agent; chatbot with the data; code-writing (PHIA's baseline) | Patterns **93.2%** (by person 90.4-95.8); single agent 89.3%, chatbot 71.3%, code 99.4%. Read to find faults: totals fixed after it | 2026-11-16 |
| **PHIA benchmark, real people, batch 2** (held out) | the same, on questions Patterns was not changed for | 337 other questions on 48 real people | the same three | Patterns **97.0%** (94.8-98.7); single agent 92.3% (Patterns +4.7, by person +1.8 to +7.3, p = 0.0009), chatbot 69.1% (+27.9), code 99.7% (-2.7) | 2026-11-17 |
| **PHIA benchmark, PHIA's users, batch A1** (held out) | the same, against PHIA's **published** answer key | 281 of PHIA's questions on its 4 synthetic users (2 left out after service failures) | the same three | Patterns **95.7%** (by person 94.2-97.6); single agent 92.2% (Patterns +3.6, by person +1.4 to +5.3, p = 0.064), chatbot 74.0% (+21.7, p < 0.001), code 97.2% (-1.4, p = 0.48). Strict (PHIA's eight-day reading of "last 7 days"): 79.4, 76.9, 67.6, 80.8. Only 4 people, so intervals by person are rough | 2026-11-17 |
| **PHIA benchmark, PHIA's users, batch A2** (held out) | the same | 282 other questions on the same 4 users | the same three | Patterns **95.0%**; single agent 92.2% (p = 0.20 alone), chatbot 70.9%, code 99.3%. **A1 and A2 pooled: Patterns 537 / 563 = 95.4%, single agent 92.2%, Patterns alone right 36 times against 18, exact p = 0.020** | 2026-11-18 |
| **PHIA benchmark, PHIA's users, batch A3** (held out) | the same | 282 more questions on the same 4 users | the same three | Patterns **95.0%**, single agent 86.2% (Patterns alone right 31 times against 6), chatbot 72.7%, code 99.3%. **A1-A3 pooled (845 questions): Patterns 95.3%, single agent 90.2%, chatbot 72.5%, code 98.6%; 67 against 24 discordant, exact p < 0.0001** | 2026-11-18 |
| **Broad questions** (made-up people, planted changes) | a question naming no metric is answered from every metric compared and corrected together: leads with what changed most, ranks nothing wrongly, gives no metric as a cause, says so when nothing changed | 5 people (activity, recovery, sleep or bedtime changed, or nothing), 24 wordings: 12 development, 12 held out, real router and model | the code before (named one of four sleep metrics the biggest change while two others had changed clearly) | Development, after fixes: 60 / 60 on every measure. **Held out (run once): the overview was reached by 45 / 60 answers; of those, led with the planted change 36 / 36, causal wording 0 / 60, unhedged false change 0 / 60, the no-change person right 12 / 12.** The 15 misses are three casual check-ins the router types as chat ("how's it going?"), one answered as out of scope: the next fix, to be shown on a fresh set. One "wrong biggest" was the check misreading "the main ... measures" and is fixed | 2026-11-18 |
| **PHIA regression after the broad-question change** | nothing else moved | the first 50 A1 questions re-asked with the new code | the stored A1 answers | 50 / 50 now against 49 / 50 before; 49 graded the same, the one change went from wrong to right | 2026-11-18 |
| **Independent conversation audit** (an outside reviewer, Codex) | follow-ups keep their dates, topic and operation | 98 turns in 19 conversations, two synthetic histories and one public PMData participant, through the real chat API | none (diagnostic, not an accuracy estimate) | 1,419 numbers recomputed, **0 mismatches**; but 28 / 49 initial turns fully right: follow-ups lose "those dates" or "that same night", the summary can contradict the evidence, guidance follow-ups lose their topic, strict counts read as inclusive, "35-minute walk" and "yes, log it" missed. The snapshot of the broad-question work fixed the missed sleep decline and the false-premise answer. Six fixes followed (next row) | 2026-11-18 |
| **Follow-ups after the audit's fixes** (made-up person, real router and model) | each follow-up computes over the metric, days, comparison and topic the conversation means; a question that stands on its own does not inherit; an unresolvable reference is asked about | graded by code from the evidence the agent computed, not the numbers it wrote (two days with the same value would fool a number check). Regression: the audit's own made-up conversations, 19 graded turns. Held out: 8 new conversations, 22 graded turns, written before any was run, run once | the audit's judgments of the same turns | **Regression 19 / 19** (the audit had 8 failed and 2 partial among them). **Held out 21 / 22 as graded (95.5%, Wilson 78-99%)**; the one miss is a grader error: "what's my average resting heart rate?" was answered over all the data as it should be, but the grader counted the earlier turn's evidence re-attached for citing; fixed in the grader, the run not repeated. Limits: a turn passes when some computed evidence has the right days, so a reply that also computed other days is not penalised; logging and contradiction fixes are covered by unit tests, not this run | 2026-11-18 |
| **Logging at scale** (development) | the draft holds what was said, and nothing is drafted when it must not be | 250 generated requests through the chat API: 90 meals, 70 workouts, 90 that must not become a draft (5 reasons, 18 each), sized so each kind is within about +-7 points and a zero-failure must-not group bounds that rate under 3.3% | none: the generator knows every value | **230 / 250 (92.0%, 95% 88-95)**. Meals 86 / 90, workouts 63 / 70 (all 7: "football" logged as American football), must-not 81 / 90: **9 of 18 "tomorrow" requests drafted as today**; 0 of 72 other must-not cases drafted (under 4.2%). Every field of every draft right (330 / 330) but the football type. The "tomorrow" fix came with #195; the held-out run is below ("football" itself was not changed and is not in it) | 2026-11-18 |
| **Verifier, on its own** | true claims pass, broken claims are caught | 3,184 claims built by code from 61 real people's evidence | itself before the fix | true claims **1,066 / 1,066** pass; broken claims caught **2,117 / 2,118** (89.9% before the fix) | 2026-11-16 |
| **Router** | each question reaches the right place | 152 held-out questions (112 ours, 40 PHIA's) | the keyword rule | **150 / 152 (98.7%)** against 126 / 152 (82.9%) | 2026-11-16 |
| **RAG retrieval** | the right passage comes back | a second held-out set of 35 answerable questions (+ 4 unanswerable, 4 medical) | words alone; the merge of words and meaning | meaning alone recall@3 **0.94**, MRR **0.83**; the merge 0.89, 0.76; words 0.51, 0.44. The app now uses meaning alone | 2026-11-16 |
| **Food matching** | a logged food gets the right USDA food | 45 everyday foods to choose the method, then 25 held-out foods scored once; right when kcal per 100 g fall in the food's real range | USDA's own order; ranking by meaning alone | held out: **22 / 25** by meaning then the model's choice, against 14 / 25 in USDA's order and 18 / 25 by meaning; no food words in the code | 2026-11-17 |
| **Logging, held out** | the draft holds what was said, and nothing is drafted when it must not be | 180 of 360 requests fixed before any run (`eval/logging_heldout.py --half`, stratified: 15 per meal, 5 per workout type, 10 per reason): no food, workout word or sentence form of the development set; the day before yesterday; spoken durations ("three quarters of an hour", "1h15"); a sixth must-not reason (negated or not yet). Run once on `main` after #195, graded by the development grader | none: the generator knows every value | **167 / 180 (92.8%, 95% 88-96)**. Meals **59 / 60** (98%, 91-100; one "couldn't pin that down"). Workouts **51 / 60** (85%, 74-92): 5 not drafted ("1h15" 3 of 5, "three quarters of an hour" 2 of 2: four by the reader's "couldn't pin that down", one asked for the length it was given), 4 drafted with the wrong type (HIIT and boxing as strength training, squash as strength and as "other"); day, time, length and distance right on all 55 drafts. Must-not **57 / 60** (95%, 86-98): 3 of 10 bare food statements were drafted ("a blueberry muffin for breakfast today"; a draft still waits for a tap); "tomorrow" and later **0 / 10 drafted** (the development run drafted 9 / 18), negated 0 / 10. **But** 16 of the 57 passed on the reader's generic "couldn't pin that down, name the days you mean": all 10 future requests and 5 of 10 without a length, which should have said it cannot log the future or asked how long. With those counted as misses, must-not is 41 / 60. $0.93 (about $0.005 a request), median 4 s. **Fixed after the run**, not yet re-measured on fresh requests: a log for a day to come and a workout with no length are answered by code, the quarter and "1h15" durations are read, and a type the person names is the card's; 9 of the misses replayed afterwards all came out right. The 3 drafted statements are left (both the router and the reader read them as logs) | 2026-11-22 |
| **Team warning before a noted crunch** | warned only when a past note like a coming one was followed by a real change | made-up teams of seven, live, a release followed by a sleep drop or by nothing | none (development) | warned **3 / 3**, false warnings **0 / 2** | 2026-11-17 |
| **Meal logging replays** | the right card, and a correction replacing it | Karim's chicken-and-rice conversation through the chat API | the code before #171 | right values (USDA chicken breast + white rice); correction replaced the card **2 / 2** | 2026-11-17 |
| **Real data, end to end** | answers on real people are right | first run: 421 questions, 46 people (PMData, LifeSnaps); **restated** on PMData only, 261 answers, after LifeSnaps' sleep stages and impossible zeros were found to be read wrongly | plain chatbot with the data pasted in | PMData only: **82.4%** (by person 76.7-87.4); on 111 shared questions 84.7% against **62.2%**. The LifeSnaps half is superseded until rerun | 2026-11-10, restated 2026-11-17 |
| **Experts against none** | whether the experts earn their place | 100 real-people questions, 38 people; the whole agent, 85 turns | no experts | data questions 84.3% both; why 27% against 53%: led to the **hybrid** | 2026-11-10 |
| **"Why" with planted causes** | a cause is named only when one moved | 33 why questions, causes planted in real people, with no-cause controls | the agent before code-tested causes | **16 to 28 / 33** | 2026-11-16 |
| **Memory** | keeps what was said, only that, apart per person and team | 20 scenarios, 77 checks, made-up person and team, real API | its own first run | **77 / 77** (first run 58 / 71) | 2026-11-11 |
| **Privacy between people** | no one reads, changes or deletes another person's data through the API | two made-up people with a record of every kind; every route taking an id called with the other's ids | none | **every attempt refused**, nothing changed, owners still reach their records; id-less routes return only the caller's data; a pending account reaches only its own status (`test_privacy_isolation.py`, in CI) | 2026-11-17 |
| **Team privacy attacks** | team answers never single out a person | 33 attacks on a made-up team of eight | its own first run | **33 / 33**, 28 stopped by code before the model | 2026-11-12 |
| **Team planted changes** | real team changes are reported, quiet teams left alone | made-up teams with 0, 1 or 2 planted changes; PMData's 16 people as a team | its own first run | **6 / 6** (first 5 / 6) | 2026-11-12 |
| **Whole conversations** | replies are sound, use context, sound natural | 104 turns, made-up person, real chat API, code checks and a judge | the code before the tuning round | **102 / 104** pass every code check (100 before); judge means unchanged within noise | 2026-11-16 |

## Today's tests in detail (2026-11-16)

### PHIA's questions, checked before any paid batch
- **Answer key:** our reading of PHIA's code reproduces all 1,603 of their published answers. A second,
  separate implementation agrees with every real-people answer.
- **Dropped:** 45 questions where PHIA's code disagrees with its own words, plus 147 that prove
  nothing (totals of heart rates, "how many days" within one day, thresholds nobody reaches).
  1,411 kept for PHIA's users, 675 for real people.
- **Live check, six questions, all four systems:** every system takes the data and answers. The
  checks found that real people's data can stop weeks before the question's period, that counts were
  graded too loosely, and that Patterns could not count days under a threshold. All three are fixed.
- **Found on the way:** our LifeSnaps loader had invented sleep stages (status issue 40).

### Verifier
`eval/verifier_check.py`, free, deterministic. Code writes true claims from real people's evidence,
then breaks each one way at a time.

| Break | Before the fix | After |
|---|---|---|
| Date outside the evidence, reversed direction, wording against direction, wrong metric, change not significant, wrong "no change", day on the wrong side, too little data, causal wording, medical wording | 100% | 100% |
| Number 10% off | 179 / 193 | 193 / 193 |
| Number 30% off | 349 / 386 | 379 / 380 |
| **Highest day quoted as the average** | **0 / 163** | **163 / 163** |

The fix: a number after "average", "highest", "lowest", "total", "median" or "usual range" must be that
statistic, and in a one-day claim an unlabeled number must be the day's value. The one miss left is a
wrong value equal to the usual range's window length (28 days).

### Router
`eval/router_eval.py` on `eval/router_set.json`.

| | Jev (the app's router) | Keyword rule (fallback) |
|---|---|---|
| Right place | 150 / 152 | 126 / 152 |
| PHIA's questions | 40 / 40 | 39 / 40 |
| Question type | 109 / 112 | 70 / 112 |
| Request intent | 122 / 128 | 108 / 128 |
| Median latency | 0.22 s | 0 s |

Jev's two misses span two areas and went to the general agent, which its own definition arguably
allows. Its intent misses (coaching read as "unclear") change nothing in the app.

### RAG retrieval
`eval/rag_eval.py --set eval/rag_heldout_2026-11-16.json`.

| Recall@3, MRR | First held-out (17, 2026-11-08) | Second held-out (35) |
|---|---|---|
| Words alone | 0.77, 0.59 | 0.51, 0.44 |
| Meaning alone | 0.88, 0.82 | **0.94, 0.83** |
| Words and meaning merged (the app until today) | 0.88, 0.77 | 0.89, 0.76 |

Meaning alone ranked better on both held-out sets, so the app now searches by meaning alone, with
words only when embeddings are unavailable. Limits: a French how-to question can find nothing (status
issue 41); 2 of 4 unanswerable and 2 of 4 medical questions returned passages, though medical
questions are refused by the router before any search.

## How to read these results (2026-11-17)

- **Development or regression, and held out.** Sets we read and then fixed the agent against (the
  conversation set, the router's first set, the 33 "why" questions, PHIA batch 1, the first 45
  foods) show that the fixes work and that nothing regressed; they are not unbiased estimates.
  Held-out results come from questions nothing was changed for: PHIA batch 2, the router's 152
  questions, RAG's second set, the 25 held-out foods. The report quotes held-out figures as the
  measure and development figures as the record of what was fixed.
- **Uncertainty by person.** Several questions go to the same person, and their answers are not
  independent, so intervals resample people (`by_person_95`), for rates and for paired
  differences.
- **Time.** In PHIA batches 1 and 2 the text-answering systems' time includes the grader's call that
  reads the number out of the reply; the code baseline has none. Those times are not compared
  across systems; runs from 2026-11-17 time the grader's reading apart (`read_seconds`).
- **LifeSnaps before 2026-11-16.** Its sleep-stage ratios were read as minutes and impossible zeros
  as values; the old real-data run is restated on PMData alone, and its LifeSnaps half needs a
  rerun before it is quoted.

## Structured request implementation (2026-11-18, local)

**PHIA check on the new path (2026-11-19).** Precise questions now go through the request reader
and code, so the earlier PHIA scores no longer described the path. Patterns re-asked the first 50
questions of two batches, graded as before:

| | Before (old path) | New path as first built | After two fixes |
|---|---:|---:|---:|
| A1 (the fixes were made on these) | 49 / 50 | **19 / 50** | 50 / 50 |
| A2 (not looked at while fixing) | 45 / 50 | not run | **49 / 50** (4 better, none worse) |

The drop to 19 was the reader anchoring "yesterday" and "last 7 days" to a previous request that
did not exist, then asking "which earlier period?"; and reading "the last 7 days" as ending
yesterday where the rest of the app ends it today. Code now reads both itself (a period counted
from today is anchored to today; "last N days" ends today unless "complete days" or "ending
yesterday" is said). A2 is the figure to quote; A1 was used to find the fixes.

The complete backend suite passes **1,920 tests**, 95 more than the starting revision; Ruff and
format checks pass. The new tests cover structured output, calendars and reference ambiguity,
all registered metrics, missing versus zero, threshold equality/units, multiple operations and
multiple-testing correction, confirmed food readback, real local draft replacement, ownership,
persistent scope, memory opt-out and grounded guidance fallback.

Paid checks are intentionally separate from the main benchmark: 15 smoke checks, a fresh 83-turn
set, a second fresh 78-turn set, four additional new probes with the 78-turn regression set, and
four final regressions. Their original scores and failures remain in
[typed-requests.md](typed-requests.md); final regressions pass, but are not held-out accuracy.
All responses were directly inspected as well as checked against the synthetic frame and
evidence. Total reported API cost: **$0.254653954**. No real health values, Google writes, or
paid judge were used. The earlier 369-turn real-history audit has not been replayed on this path.

## Later PR #195 checks and outstanding results

The [November 19 audit](experiments.md#agent-reliability-from-november-17-to-19) covers 211 fresh turns at `84db5f5`,
including 18 logging turns graded on both the reply and actual card state. The small B1
regression gate passed 24/24. A subsequent [reader replay](reader-replay-2026-11-19.md) inspected
58 exposed turns for diagnosis. Fresh end-to-end scores after the next implementation changes,
the human blind-grading comparison and pilot usage results remain outstanding. The mode A
benchmark and the 250-request logging development run are recorded in the table above.
