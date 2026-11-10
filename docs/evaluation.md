# Evaluation: what was tested, and what it does and does not show

Run on 2026-11-10. Costs are in [costs.md](costs.md), the running history in
[experiments.md](experiments.md). Every script is in `eval/`, every result in `eval/results/`.

## The systems compared

| System | What it is |
|---|---|
| **Full system** ("experts") | The app: routing, the sleep, recovery and activity experts, consults, and the question-type plans |
| **No experts** ("pipeline") | The same app with every question sent to the general agent (`NoExperts` in `eval/phia.py`) |
| **Bare agent** ("general") | One agent with every tool and metric: no routing, no plans, no automatic RAG, no premise check |
| Plain chatbot | A model given the person's table and no tools (real-data test only) |

The claim checker and the medical guard are on for the three agents. Full against no experts shows
what the experts add; no experts against bare shows what the rest adds.

**What differs between experts:** the metrics each owns, its instructions, and the rule that a claim
about another area needs that expert's evidence. **Shared by all:** the tools (chosen by question type,
not by expert), one memory per person, and one RAG index (a per-area filter exists but nothing uses it).

## The tests

| Test | Questions from | Data | Right answer from | Script and results |
|---|---|---|---|---|
| Real data | Our templates, randomized | 46 real people: all 16 of PMData, a random 30 of 51 usable in LifeSnaps | `eval/oracle.py`, written apart from the app | `real_eval.py`, `real_regrade.py`; `real_eval_2026-11-10_full_regraded.json` |
| PHIA exact | PHIA's, written by experts from templates | PHIA's 4 synthetic users, about 30 days | PHIA's key | `phia.py`, `three_systems.py`; `three_systems_2026-11-10.json` |
| PHIA open | People, via PHIA's survey | The same users | None: people grade `phia_blind_2026-11-10.csv` | Same |
| Why, planted cause | Ours | 20 synthetic people with a known cause (`app/synthetic.py`) | The planted cause | `three_systems.py`; `why_answers_2026-11-10.jsonl` |

PHIA: Merrill, Paruchuri et al., *Transforming wearable data into personal health insights using large
language model agents*, Nature Communications; [repository](https://github.com/yahskapar/personal-health-insights-agent),
CC BY-NC 4.0. Of its 4,000 exact questions, 1,603 ask for a plain daily value on a metric the app has
(workouts and percent columns are left out), and 100 were drawn at random. Following its stored code
reproduced all 1,603 answers. Its "last 7 days" covers eight calendar days, so a strict score uses its
key and a fair score also accepts seven days ending today or yesterday.

## Results

**Real data, full system:** 82% correct (346 of 421; 95% interval resampling people, 79 to 86%). On the
same 187 questions, 83% against 62% for the plain chatbot. Details in experiments.md.

**The three systems** (the same questions; "only A / only B" counts questions just one got right):

| Set | Full system | No experts | Bare agent | Full vs no experts | Full vs bare |
|---|---|---|---|---|---|
| PHIA exact, strict (83) | 53% | 58% | 63% | 4 / 8, p = 0.39 | 2 / 10, p = 0.04 |
| PHIA exact, fair (83) | 60% | 65% | 70% | 4 / 8, p = 0.39 | 2 / 10, p = 0.04 |
| Why, all (20) | 25% | 70% | 90% | 0 / 9, p = 0.004 | 0 / 13, p < 0.001 |
| Why, cause in another area (10) | 20% | 60% | 80% | 0 / 4 | 0 / 6 |
| Why, cause in the same area (5) | 60% | 80% | 100% | 0 / 1 | 0 / 2 |
| Why, no cause to find (5) | 0% | 80% | 100% | 0 / 4 | 0 / 5 |

| How each ran | Full system | No experts | Bare agent |
|---|---|---|---|
| Cost per exact answer | $0.0035 | $0.0031 | $0.0064 |
| Calls per exact answer | 2.8 | 2.6 | 4.7 |
| Ran out of budget, exact (of 83) | 0 | 0 | 11 |
| Refused, open questions (of 53) | 11 | 11 | 0 |

**The experts did not help on these tests, and on "why" questions they did worse.** The comparison on
exact questions cannot tell the full system from no experts; the bare agent is ahead of the full system
at a level that would not survive correcting for three comparisons. The "why" gap is large but comes
from 20 people built from four patterns.

## Why the experts lost, read from the answers and the code

1. **A circular test.** For recovery with sleep, `CROSS_AREA` correlates sleep with `recovery_score`,
   which the app builds partly from sleep, so sleep nearly always "explains" it. With no cause planted,
   the full system named sleep or something unrelated in 5 of 5.
2. **The test replaces the investigation.** When the router allows a consult on a "why", the plan
   narrows to `coverage` and `correlate` over 90 days, so the expert no longer compares before and
   after the change. Resting heart rate is not in any cross-area pair, so training was never tested.
3. **Answers about one day come from a fixed snapshot of main metrics,** so "light sleep today" can be
   answered with something else.
4. **Other weak spots on exact questions, shared by all:** "how many days below X" (7% and 33%) and
   sums (26% and 32%): no tool counts or sums days, and the model may not compute.

These are causes read from traces, and none has been fixed or re-tested.

## What can be claimed

- On real people, single data questions are right about 82% of the time, and more accurate than a
  plain chatbot given the same table. The agent rarely invents a change and misses some real ones.
- A bare agent costs about twice as much per answer and refuses nothing, including questions an
  app with no medical scope should not answer.

## What cannot be claimed

- That experts improve answers. These tests point the other way until the causes above are fixed.
- That the advice is good. The open answers await the blind grading; the automatic judge is not
  validated (2.85 full, 2.45 bare, on 60).
- That memory and follow-ups work on real data: every question here was asked on its own.
- Agreement with outside truth: PMData's injury and training logs and LifeSnaps' check-ins are unused.

## Limits

- Each question ran once. PHIA's users are synthetic and short, so it has no long-term trends.
- The no-experts system covers 83 of 100 exact and 53 of 60 open questions: credit ran out.
- Web search and food lookups were off in the PHIA tests, so a question misrouted to "world" fails.
- Neither real dataset records wear time, so low-wear days are not filtered there.
- The real-data score was regraded after reading it; both scores are kept. The planted-cause questions
  are ours, as is the template for reading the cause.

## Blind grading

`eval/results/phia_blind_2026-11-10.csv` has 51 answers, three each to 17 open questions, shuffled and
unlabeled. Fill in the three 1-to-5 columns. Do not open `phia_blind_key_2026-11-10.json` or
`phia_answers_2026-11-10.jsonl` until finished: they say which system wrote what.
