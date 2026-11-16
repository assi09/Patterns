# How we defend the agent: the evaluation plan before the pilot

Written 2026-11-16: how each part of the agent is defended, and why. What runs when, and its cost, is
in [testing-plan.md](testing-plan.md). The pilot then adds real users' own questions and the team
feature live.

## What the agent has to get right

The agent does not write essays or reason from scratch. It reads the person's own data and says it in
words, so the questions that matter are narrow and checkable:

1. **The right data**: the metric asked about, not a neighbour.
2. **The right time**: the day or period meant ("last week", "last night").
3. **The right number**: the figure itself, computed by code, quoted without change.
4. **The right verdict**: changed or not, linked or not, as the statistics say.
5. **Only what holds**: no cause where none moved, no number the data does not have, no medical
   advice, a refusal when it should refuse.

That makes it a data-grounded question-answering system, tested the way such systems are: a fixed
question with an answer computed independently by code, the reply checked against it. This is how
PHIA scores its objective questions (an exact-match answer key computed from the data; 84% for PHIA
against 74% for a code-generation baseline) and how text-to-SQL work scores "execution accuracy".

## Who writes the questions, and why it is still fair

Writing our own questions is standard, on three conditions, each met below:

- **The answer key is independent of the app.** `eval/oracle.py` (now `app.oracle`) computes every
  answer with its own code, so a question we wrote cannot be biased toward our answer: the grade
  depends on the data, not the wording. `eval/check_oracle.py` checks the key against the app's own
  statistics at no cost.
- **Questions cover capabilities, not just examples.** CheckList (Ribeiro et al., ACL 2020 best
  paper) tests NLP systems with a matrix of capabilities and three test types: minimum functionality
  (one plain question per capability), invariance (the same question reworded, with typos or in
  another language, must give the same answer) and directional (a change in the data must move the
  answer the right way). It found many more bugs than held-out accuracy alone.
- **Some wording is not ours.** PHIA's question bank (Merrill et al., Nature Communications) was
  written by other researchers; we ask its question templates on our real people, with the answer
  computed by our oracle. A small held-out set is written by people outside the team (Jad, the TA,
  classmates). The pilot then gives real users' own questions.

## Each component, its claim, its test and its baseline

| Component | What we claim | Test | Metric | Baseline | Data | Cost |
|---|---|---|---|---|---|---|
| Router | sends each question to the right handler | ~150 labeled questions (ours, PHIA's, the conversation set) | accuracy, confusion matrix | keyword router | labels by design | ~$0 (Jev) |
| Data answers (day, lookup, change, pattern) | right metric, period, figure and verdict | templates (ours and PHIA's) on real people, graded by the oracle; each also reworded, with typos and in French or Arabic | accuracy; consistency across rewordings; unsupported-number rate | plain LLM with the data pasted in; the agent without its verifier | PMData 16 + LifeSnaps 51 real people | ~$1.5 |
| Why answers | names a cause only if one moved | real people with a cause planted (semi-synthetic, as IHDP-style causal benchmarks do), plus no-cause controls; two kinds of planting | cause found; false-cause rate | the agent before code-tested causes; plain LLM | the same real people | ~$0.8 |
| RAG (guidance) | finds the right passage for the query | 78 labeled queries, plus rewordings | recall@k, MRR | BM25 only; dense only | `rag_set.json` | ~$0.05 |
| Advice | personal, grounded, never medical | same question for different people; the guard on every sentence | share personal; share cited; medical sentences | no retrieval; no personal evidence | `personal_eval.py`, `advice_guard.py` | ~$0.3 |
| Logging | the draft holds what was said | ~60 generated utterances with known slots (food, amount, time, workout, duration); future and incomplete ones | slot accuracy per field (like BFCL's argument match); right refusals | none needed (labels come from the generator) | generated | ~$0.3 |
| Memory | keeps what was said, only that, apart per person and team | `memory_eval.py` | kept right; medical kept; leaks | none | 77 checks | ~$0.3 |
| Safety | refuses medical and off-topic, answers ordinary health questions | refusal set plus benign look-alikes; prompt injection; team privacy attacks | refusal accuracy; false refusals; leaks | the bare model | existing sets | ~$0.2 |
| Conversation | sound, honest, natural, uses context | `conversation_eval.py`, 104 turns | code checks; judge scores | earlier versions | synthetic person | ~$0.6 |
| The judge itself | its scores mean something | Karim and Jad grade 50 replies blind | agreement with the judge (% and Cohen's kappa) | human against human | 50 replies | $0 |

## PHIA's questions as the main benchmark for data answers (`eval/phia_bench.py`)

**Why PHIA fits.** The course asks for agent evaluation on real public data, with answers from an
independent oracle and baselines, not only synthetic data. PHIA (Merrill et al., Nature
Communications) gives questions written by other researchers, each with an answer computed by their
code; our reading of that code reproduces all 1,603 of their published answers. Its questions test
the base of everything the app says: the right metric, period and figure (average, median, highest,
lowest, total, days past a threshold). They do not test "why", advice, logging or memory.

**Two modes.** Mode A asks each question of the PHIA synthetic user it was written for, graded by
PHIA's published answer. Mode B, the one the course requirement needs, asks the same questions of
real people from PMData and LifeSnaps, graded by PHIA's answer logic on their data. A question goes
to a person only if they have the metric on at least 80% of the days in its period (a person's sleep
can stop weeks before their steps), which leaves 58 people. A second, separate implementation agrees
with every mode-B answer.

**Cleaning** (4,000 published, 1,603 of a shape our data has, 1,411 kept):
- dropped: questions about workouts (1,532), sleep-stage percentages (668), standard deviations and
  multi-step code (197): data or computations the app does not have;
- dropped: a total of a heart rate or HRV (57), "how many days" within one day (48), a threshold no
  person reaches, answered 0 by anyone ("exactly 15 hours of sleep", 42);
- dropped: PHIA's own key errors, where its code disagrees with its words (45): "sleep less than 3
  hours" coded as at least 3 hours, light-sleep questions computed on total sleep. Every kept
  question's metric, kind, direction and period match its code;
- tidied: the template's doubled word, "did I I had" (145); no other change to the wording;
- graded twice: strict against PHIA's key, which reads "last 7 days" as eight calendar days, and
  fair, which also accepts the seven days ending today or yesterday (the two differ on 44%).

**Found while checking:** LifeSnaps' `sleep_*_ratio` columns compare a night's stage with the
person's usual (they average 1.0); `real_data.py` had multiplied them by time asleep, so every stage
came out near the whole night. Stage minutes are now absent for LifeSnaps, and stage questions go to
PMData people. Earlier real-data runs asked LifeSnaps people about deep sleep with those values; the
agent and the oracle read the same numbers, so they were graded consistently, but not on real stages.

**Systems** (same model, data, date and question): Patterns; a single agent with every tool;
a chatbot with the table pasted in (PHIA's "numerical reasoning" baseline); the model writing one
pandas expression that code runs (PHIA's "code generation" baseline).

**Measured:** strict and fair accuracy with Wilson intervals; paired exact tests of Patterns against
each baseline; accuracy by kind of question; cost and time per answer; from Patterns' traces, the
router's question type (every PHIA question is a value or a day), the tools used and the claims the
verifier rejected.

**Grading:** a reading model, blind to the system and the key, gives the reply's number; it is right
within 2% (or 1 unit), and a count of days only if exact. Code also reads every number in the reply
(durations to minutes, dates and the question's own numbers left out); where the two readings
disagree, the answer is listed for a person to check.

**Batches:** mode A in 5 batches of about 282, mode B in 2 of 338, every kind, period and metric
spread evenly. Each batch first asks 20 questions (`--first 20`), which are read before the rest; a system
failing 5 times in a row stops the run. About $0.016 per question for the four systems: $4.5 per
mode-A batch, $5.4 per mode-B batch, about $33 in all.

## When the other parts are tested

| Part | Where it is tested |
|---|---|
| Router | the question types logged on every PHIA answer (free), and ~150 labeled questions against the keyword router |
| Tools | unit tests on every statistic, including over many seeds (CI, free); which tool each PHIA answer used |
| Verifier | on its own: true claims built from real evidence must pass, the same claims broken one way at a time must be caught (free); in the PHIA runs, claims rejected per answer and numbers not in the data, Patterns against the baselines |
| RAG | `rag_eval.py`: 78 labeled queries, recall@k and MRR, hybrid against BM25 and dense alone |
| Why | `hybrid_check.py`: causes planted in real people, with no-cause controls |
| Logging, memory, safety, conversation | generated utterances with known fields; `memory_eval.py`; refusal and privacy sets; `conversation_eval.py` |

## End to end, against baselines

The same question set (real people, oracle answers, our templates plus PHIA's plus the held-out
ones) for three systems:

1. **Plain chatbot**: the same model with the person's data pasted in, no tools.
2. **Single agent**: one agent with the tools, no router, experts or code-tested causes.
3. **Patterns**: the full system.

Reported: accuracy with a confidence interval resampled by person; the rate of numbers not in the
data; correct refusals; cost and latency per answer. `three_systems.py` already runs this shape.

## What we cannot claim, said in the report

- A simulator's planted cause is not every real cause: results on planted causes reflect how they
  were planted, so two planting mechanisms are used and the limit is stated.
- The judge is one model family; its agreement with people is measured, not assumed.
- 58 real people is small: intervals are reported, and the pilot adds real users.
- PHIA is peer-reviewed (Nature Communications 2026) but recent, and its key has errors (45 dropped);
  it is described as the closest published benchmark, not a standard.
- The router's labels are ours, because the routes are our design.

## Order of work

In [testing-plan.md](testing-plan.md#order-and-budget).

Sources: [CheckList](https://arxiv.org/abs/2005.04118);
[PHIA](https://arxiv.org/abs/2406.06464); [MT-Bench, LLM-as-a-judge agreement with
people](https://arxiv.org/abs/2306.05685); [BFCL](https://gorilla.cs.berkeley.edu/leaderboard);
[semi-synthetic causal benchmarks and their limits](https://pdf.arxiv.org/pdf/2107.13346).
