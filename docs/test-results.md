# Test results

Every test run on the agent, what it shows, on what data, against what, and what it found. One row
per test; the method behind each is in [evaluation-plan.md](evaluation-plan.md), the schedule in
[testing-plan.md](testing-plan.md), the full write-ups in [evaluation.md](evaluation.md) and
[experiments.md](experiments.md), and the cost of each run in [costs.md](costs.md). Results files are
in `eval/results/` (totals only; anything holding a real person's values stays in the git-ignored
`data/eval/results`). Updated 2026-11-16.

## At a glance

| Test | What it shows | Data | Compared with | Result | When |
|---|---|---|---|---|---|
| **PHIA benchmark, real people** (mode B) | right metric, period and figure | PHIA's questions on 58 real people (PMData, LifeSnaps), PHIA's answer logic | single agent; chatbot with the data; code-writing (PHIA's baseline) | **pending**: batch 1 of 2 runs first | 2026-11-16/17 |
| **PHIA benchmark, PHIA's users** (mode A) | the same, against PHIA's published key | PHIA's 4 synthetic users | the same three | pending | after mode B |
| **Verifier, on its own** | true claims pass, broken claims are caught | 3,184 claims built by code from 61 real people's evidence | itself before the fix | true claims **1,066 / 1,066** pass; broken claims caught **2,117 / 2,118** (89.9% before the fix) | 2026-11-16 |
| **Router** | each question reaches the right place | 152 held-out questions (112 ours, 40 PHIA's) | the keyword rule | **150 / 152 (98.7%)** against 126 / 152 (82.9%) | 2026-11-16 |
| **RAG retrieval** | the right passage comes back | a second held-out set of 35 answerable questions (+ 4 unanswerable, 4 medical) | words alone; the merge of words and meaning | meaning alone recall@3 **0.94**, MRR **0.83**; the merge 0.89, 0.76; words 0.51, 0.44. The app now uses meaning alone | 2026-11-16 |
| **Logging** | the draft holds what was said | 52 generated requests through the chat API | none: the generator knows every value | **pending** (built; grader checked on hand-made drafts) | with the PHIA batches |
| **Real data, end to end** | answers on real people are right | 421 questions, 46 people (PMData, LifeSnaps), an independent oracle | plain chatbot with the data pasted in | **82%** (79-86%); on the same 187 questions 83% against **62%** | 2026-11-10 |
| **Experts against none** | whether the experts earn their place | 100 real-people questions, 38 people; the whole agent, 85 turns | no experts | data questions 84.3% both; why 27% against 53%: led to the **hybrid** | 2026-11-10 |
| **"Why" with planted causes** | a cause is named only when one moved | 33 why questions, causes planted in real people, with no-cause controls | the agent before code-tested causes | **16 to 28 / 33** | 2026-11-16 |
| **Memory** | keeps what was said, only that, apart per person and team | 20 scenarios, 77 checks, made-up person and team, real API | its own first run | **77 / 77** (first run 58 / 71) | 2026-11-11 |
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

## To be filled in

- PHIA mode B, batches 1 and 2: accuracy (strict and fair) for each system with intervals, paired
  tests of Patterns against each baseline, by kind of question, cost and time per answer, the
  router's type, tools used and claims rejected.
- Logging: each field's accuracy, and the requests that must not become a draft.
- PHIA mode A; the judge against Karim's and Jad's blind grades; the pilot.
