# Test results

Every test run on the agent, what it shows, on what data, against what, and what it found. One row
per test; the method behind each is in [evaluation-plan.md](evaluation-plan.md), the schedule in
[testing-plan.md](testing-plan.md), the full write-ups in [evaluation.md](evaluation.md) and
[experiments.md](experiments.md), and the cost of each run in [costs.md](costs.md). Results files are
in `eval/results/` (totals only; anything holding a real person's values stays in the git-ignored
`data/eval/results`). Updated 2026-11-17. **Which results are final accuracy and which are
development, and what is left: [progress-2026-11-17.md](progress-2026-11-17.md).**

## At a glance

| Test | What it shows | Data | Compared with | Result | When |
|---|---|---|---|---|---|
| **PHIA benchmark, real people, batch 1** (development) | right metric, period and figure | 338 of PHIA's questions on 48 real people (PMData, LifeSnaps), PHIA's answer logic | single agent; chatbot with the data; code-writing (PHIA's baseline) | Patterns **93.2%** (by person 90.4-95.8); single agent 89.3%, chatbot 71.3%, code 99.4%. Read to find faults: totals fixed after it | 2026-11-16 |
| **PHIA benchmark, real people, batch 2** (held out) | the same, on questions Patterns was not changed for | 337 other questions on 48 real people | the same three | Patterns **97.0%** (94.8-98.7); single agent 92.3% (Patterns +4.7, by person +1.8 to +7.3, p = 0.0009), chatbot 69.1% (+27.9), code 99.7% (-2.7) | 2026-11-17 |
| **PHIA benchmark, PHIA's users, batch A1** (held out) | the same, against PHIA's **published** answer key | 281 of PHIA's questions on its 4 synthetic users (2 left out after service failures) | the same three | Patterns **95.7%** (by person 94.2-97.6); single agent 92.2% (Patterns +3.6, by person +1.4 to +5.3, p = 0.064), chatbot 74.0% (+21.7, p < 0.001), code 97.2% (-1.4, p = 0.48). Strict (PHIA's eight-day reading of "last 7 days"): 79.4, 76.9, 67.6, 80.8. Only 4 people, so intervals by person are rough | 2026-11-17 |
| **PHIA benchmark, PHIA's users, batch A2** (held out) | the same | 282 other questions on the same 4 users | the same three | Patterns **95.0%**; single agent 92.2% (p = 0.20 alone), chatbot 70.9%, code 99.3%. **A1 and A2 pooled: Patterns 537 / 563 = 95.4%, single agent 92.2%, Patterns alone right 36 times against 18, exact p = 0.020** | 2026-11-18 |
| **Logging at scale** (development) | the draft holds what was said, and nothing is drafted when it must not be | 250 generated requests through the chat API: 90 meals, 70 workouts, 90 that must not become a draft (5 reasons, 18 each), sized so each kind is within about +-7 points and a zero-failure must-not group bounds that rate under 3.3% | none: the generator knows every value | **230 / 250 (92.0%, 95% 88-95)**. Meals 86 / 90, workouts 63 / 70 (all 7: "football" logged as American football), must-not 81 / 90: **9 of 18 "tomorrow" requests drafted as today**; 0 of 72 other must-not cases drafted (under 4.2%). Every field of every draft right (330 / 330) but the football type. Fixes and a held-out rerun to follow | 2026-11-18 |
| **Verifier, on its own** | true claims pass, broken claims are caught | 3,184 claims built by code from 61 real people's evidence | itself before the fix | true claims **1,066 / 1,066** pass; broken claims caught **2,117 / 2,118** (89.9% before the fix) | 2026-11-16 |
| **Router** | each question reaches the right place | 152 held-out questions (112 ours, 40 PHIA's) | the keyword rule | **150 / 152 (98.7%)** against 126 / 152 (82.9%) | 2026-11-16 |
| **RAG retrieval** | the right passage comes back | a second held-out set of 35 answerable questions (+ 4 unanswerable, 4 medical) | words alone; the merge of words and meaning | meaning alone recall@3 **0.94**, MRR **0.83**; the merge 0.89, 0.76; words 0.51, 0.44. The app now uses meaning alone | 2026-11-16 |
| **Food matching** | a logged food gets the right USDA food | 45 everyday foods to choose the method, then 25 held-out foods scored once; right when kcal per 100 g fall in the food's real range | USDA's own order; ranking by meaning alone | held out: **22 / 25** by meaning then the model's choice, against 14 / 25 in USDA's order and 18 / 25 by meaning; no food words in the code | 2026-11-17 |
| **Logging** | the draft holds what was said | 52 generated requests through the chat API | none: the generator knows every value | **pending** (built; grader checked on hand-made drafts) | with the PHIA batches |
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

## To be filled in

- Logging: each field's accuracy, and the requests that must not become a draft.
- PHIA mode A; the judge against Karim's and Jad's blind grades; the pilot.
