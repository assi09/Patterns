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
- Routing is what keeps health questions out. The full system refused 12 of 60 open questions; the
  bare agent refused none. It told someone citing kidney issues their data showed no clear reason
  to avoid heavy lifting, and called another person's heart health stable. A word filter caught
  neither, so "no medical wording" is a weak check. Some refusals look too strict (a question about
  a meditation practice).
- A bare agent costs about twice as much per answer.

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

## The deciding test: separated experts against no experts

After the runs above, the experts were truly separated (draft #144, commit f9f9ea8): each sees only its
own metrics, reaches another area through a consult the router allows, keeps its own tools and
searches public guidance on its own topics first. Two faults in their path were fixed. The rule was
written down before this ran: experts stay only if they match no experts on data questions and on
causes, cost at most 10% more, and are clearly better at something.

**Real people** (`eval/decide_experts.py`; 100 fresh questions, 38 people from PMData and LifeSnaps;
`eval/results/decide_experts_2026-11-10.json`):

| Set | Experts | No experts | Only experts right / only no experts right |
|---|---|---|---|
| Data questions (70) | 84.3% | 84.3% | 3 / 3 |
| Why, known cause planted in real data (30) | 27% | 53% | 3 / 11, p = 0.06 |
| Why, cause in another area (18) | 11% | 56% | 0 / 8, p = 0.008 |
| Why, cause in the same area (6) | 50% | 83% | 1 / 3 |
| Why, no cause to find (6) | 50% | 17% | 2 / 0 |
| Cost per answer | $0.0071 | $0.0081 | |

**Whole agent** on a made-up person, through the real API (`eval/agent_eval.py`, 85 turns each: logging,
memory, follow-ups, routing, advice, reminders, safety): 82 of 85 with experts, 81 of 85 without. The
raw output says 42 for no experts, because 40 of its checks ask which expert answered, which a
system without experts fails by definition; those are not counted. Logging: 13 of 13, and 12 of 13.

**Verdict by the rule: the experts do not stay.** They tie on data questions and on the whole agent and
cost 13% less, but lose clearly when a cause sits in another expert's area, which is what they were
meant to be for, and are not clearly better at anything.

No experts is not good at causes either: 53%, and it named a cause in 5 of 6 cases with none to find.
Each question ran once, the causes were read from replies by a model, and 30 is few.

## The hybrid: experts inside their area, the general agent for why

**The design** (#149): an expert answers inside its own area (lookups, changes, patterns, logging);
a why question, or one the router says spans areas, goes to the general agent with every metric and
the experts' notes. An expert the person picked still answers. Three fixes came with it, for every
route: a score is never offered as the reason for its own inputs in a correlation, the premise check
starts where a change began, and a cause must have changed in the same period.

**The questions** (`eval/hybrid_check.py`, seed 2027, none asked before, 36 real people):

| Kind | How many | What it asks | The right answer, and who decides it |
|---|---|---|---|
| change | 18 | "Has my time asleep changed in the last 21 days compared with the 28 days before?" | `eval/oracle.py`: a Mann-Whitney test at 5%, up, down or none |
| link | 16 | "Does my steps go with my time asleep the next day?" | the oracle: a Spearman test at 5%, positive, negative or none |
| weekend | 12 | "Is my HRV different on weekends compared with weekdays?" | the oracle: weekends against weekdays at 5% |
| planted | 14 | a change question after we moved the last 14 days by 1.2 of the person's spread | the direction we planted |
| planted control | 10 | the same question on the untouched data, where the oracle finds nothing | "no change" |
| why, cause in another area | 14 | "Why has my HRV dropped lately?" after we cut their time asleep, and HRV with it, over 21 days | the planted cause (time asleep, or training) |
| why, cause in the same area | 4 | "Why am I sleeping less lately?" after we moved bedtime later | later bedtime |
| why, no cause to find | 12 | "Why has my resting heart rate gone up lately?" after we moved only that | "nothing explains it" |

A planted case is kept only if the oracle confirms the change, and for "no cause" only if sleep,
activity and bedtime did not change. The reply's number, verdict or named cause is read by a small
model that sees neither the system nor the answer key. Credit stopped the run at 95 of 103.

**Results** (`eval/results/hybrid_check_2026-11-10.json`):

| | Hybrid | No experts | Before the fixes |
|---|---|---|---|
| Data questions (65) | **92%** | 89% (only hybrid right 3, only no experts 1; p = 0.63) | |
| Why, all (30) | 57% | 63% | 53% (same questions) |
| Why, cause in another area (14) | 50% | 50% | 50% |
| Why, no cause to find (12): named one anyway | 6 | 3 | 6 |
| Whole agent (85 turns) | 82 | 81 (earlier run) | |
| Cost per answer | $0.0089 | $0.0091 | |

**Verdict by the rule: the hybrid stays, narrowly.** It is at least as accurate as no experts on data
questions and the whole agent, and 2% cheaper; nothing it does is measurably better. Both send every
why question down the same path, so their 57% and 63% differ only by chance: a useful measure of how
much one run varies (two answers in 30).

**The fixes did not fix why.** 53% before, 57% after, the same 50% with a cause in another area, and
a cause named in half the cases where there was none. Reading the wrong answers:

1. **The investigation stops early.** For a resting heart rate raised by training it checked sleep,
   found it steady, and never looked at activity; for HRV lowered by short sleep it checked time in
   bed and efficiency but not time asleep.
2. **Scores still explain their inputs in comparisons.** "Your recovery score fell too" explains HRV
   with a score built from HRV; the fix covered correlations only.
3. **The premise check still misses some changes** ("held steady, 74.1 against 72.3").
4. **Some "wrong" answers are arguable.** "No other clear cause stands out" alongside a breathing rate
   that also moved is graded as naming a cause, and in real data it may really have moved.

The next step for why is to have code test every candidate cause before and after the change, as
the premise check does for the metric itself, rather than leave the choice to the model.

## Blind grading

`eval/results/phia_blind_2026-11-10.csv` has 51 answers, three each to 17 open questions, shuffled and
unlabeled. Fill in the three 1-to-5 columns. Do not open `phia_blind_key_2026-11-10.json` or
`phia_answers_2026-11-10.jsonl` until finished: they say which system wrote what.

## The pilot report

`python -m app.pilot_report --since 2026-11-12 --until 2026-11-22` prints the pilot's totals as JSON
(`backend/app/pilot_report.py`). It runs **inside the Railway `api` service** (`railway ssh`, as in
[deployment.md](deployment.md#4-first-sign-in-online)), because Postgres has no public port and
testers' health data never leaves the server. Only the printed JSON is copied to
`eval/results/pilot_<date>.json`. It costs nothing: no model is called.

What it prints, all as counts, rates and spreads (mean, median, 90th percentile, maximum):

| Section | What |
|---|---|
| `chat` | questions, questions per person per day and per active day, question types (the router's), outcomes from the stored traces, success rate (of the questions not refused), refusals, latency in total and in the model, model and tool calls, tool errors, repairs, rejected claims, fallbacks, guard outages, cost, thumbs (and thumbs by outcome), and per person only their number of questions and active days |
| `accuracy` | every stored verified claim checked against the independent answer key (`app.oracle`, moved from `eval/` so the server has it) on that person's data, over the periods its evidence covered: changes and no-changes from `compare_windows` and `weekday_split`, links from `correlate`; other claims are counted as unchecked |
| `recall` | what "has anything changed" answers missed: for each answered `change` question, the answer key tests every metric in the answering expert's area, last 14 days against the 28 before, corrected for testing them all (Benjamini-Hochberg at 0.05), and counts the changes the answer named in the right direction, named the wrong way, missed, and the changes it named that the key does not find. With nothing planted the key finds a change for 2.4-3.4% of 500 made-up people per area, so a quiet answer is rarely marked as a miss |
| `recovery_vs_check_ins` | the recovery score against morning check-ins, per person with at least 7 paired days (Spearman), reported only across people: how many, median rho, how many positive and significant |
| `proposals` | alerts raised, sent and marked useful; reminders the agent proposed and kept; memory cards shown, kept and declined |
| `teams` | per team (as "team 1"…): members, alerts raised, proposals approved or declined, the team agent's outcomes, latency, thumbs and cost |

**What these do not measure.** The claim check shows the numbers are right; recall shows what
was missed, only for change questions and only over the default period. Neither judges whether the
answer addressed the question, a "why", the summary's wording, or a general how-to answer. For those,
Karim and Jad grade a random sample of about 40 answers by hand, inside Railway, with a rubric set
before reading (addressed the question, correct, complete, nothing unsupported), only from testers
who agreed that the team may read answers. Only the scores are kept.

**Privacy.** People are "person 1", "person 2"… in an order taken from a hash of their id. Nothing
prints an email, a message, a claim's words or a health value, and a statistic about someone's own
data appears only as part of a figure across people. Admins (the owner) are left out unless
`--include-admins` is given. A test builds a made-up database and checks that none of these appear
in the output (`backend/tests/test_pilot_report.py`).

**Limits.** The answer key tests at 0.05 per claim, while the agent corrects for all the tests in
its run, so a borderline change it called unclear can count as a disagreement; the report says so.
Data synced after an answer (the last three days are reread) can shift a recomputed result
slightly. Answers from before traces were stored (#151) are counted as untraced.

## Memory, the person's and the team's (2026-11-11)

`eval/memory_eval.py` drives the real API with the real model, router and guard, on a made-up person
(120 days, a resting heart rate rise, two dated sleep dips) and a made-up team of seven. Twenty
scenarios, 77 checks. Each check is code reading the reply, the stored trace of the answer (what
context it was given, which tools ran on which dates) and the memory page or team notes afterwards.
Results are in `eval/results/memory_eval_2026-11-11_*`.

| Area | Scenarios |
|---|---|
| Within a chat | follow-ups keep the subject; "the day before that"; a trip mentioned in turn 1 used in turn 11, after it left the verbatim window |
| Across chats | the trip's dates found from another chat without ever being kept; a kept fact shaping advice; a declined one never used; said once (noticed) then twice (a card); a fact replaced; an event used only when its dates match; an earlier finding recalled; a reworded fact used; a belief that disagrees with the data |
| Forgetting | a deleted chat's words and heard facts gone; an edited message's card gone |
| Attacks | an instruction and a medical statement as memory, refused and not obeyed |
| Team memory | a note saved from what the supervisor said, found after leaving the history and lined up with the team's change; unsafe notes refused; a deleted note forgotten; something said and not saved, recalled after four more turns; the supervisor's own memory and the team's kept apart, both ways |

**The rule, set before the first run:** one full run; read every failure and sort it as a bug, a
design gap or a test flaw; fix causes with scripted tests; rerun only what failed; then one final
full run. Repeats were decided beforehand: the three cross-chat recall scenarios, three times each.

**Results.** First full run 58 of 71. After the fixes below, the final full run passed 77 of 77, with
the repeated recall scenarios 3 of 3 each; it then found four answers that passed their checks but
read badly, which were fixed and rerun (21 of 21 on the "remember" scenarios, three times each).
Context stayed within its budget on every turn (median 93 tokens, at most 1,481 of 1,500).

**What it found and what changed:**

| Found | Fix |
|---|---|
| "Why did my sleep drop around Aug 15?" answered about the last two weeks | the premise check reads a named day and tests the week from it |
| "What do you know about me?" quoted an old chat's "night shifts" after it was replaced | recall trusts the kept profile; its number check reads it; the fallback lists what was kept |
| "The day before that" counted from today | code turns it into a date from the last answer's day; the rewrite may use it; the day snapshot covers the day named |
| A coaching answer lost over a claim direction of "steady" | an unknown direction parses as none and is asked for |
| An event they kept, overlapping the change, went unmentioned | code puts it in front of the agent, to be said in their words, never as a statistic |
| The listener reworded an attack ("wants answers to ignore rules") past the instruction check | facts about how the assistant should behave are refused, and such messages are not listened to |
| A card from a message edited away stayed waiting | an undecided card goes with its words, with its inbox entry; kept or declined ones stay |
| "Do I get 8 hours?" agreed with a kept belief | the context says the data wins over what they said |
| "Remember that…" promised a card when none was made | an explicit request is heard first, and the reply says what happened; the guard gets a second try |
| The team agent did not save "we had a deadline on Oct 20" and failed the answer | a message that asks nothing takes a short note path |
| The team agent forgot anything older than three exchanges | it reads up to 20 earlier things the supervisor said |
| A note saying "everyone was crunching" was refused | notes may speak of the whole team, never a subset |
| A deleted note was still recalled from the chat | deleting a note deletes the exchange it came from |
| "What do you know about me?" in the team chat failed | a fixed reply: the team agent knows the team only |
| Deleting chats handed back the daily spending cap | a spending ledger (#154) |

**Limits.** One made-up person and team; each turn but the repeated three ran once per pass, so a
pass shows behaviour, not a rate. Some checks are word matches, and three were loosened after
reading answers that were right in other words (a recall route, a longer usual period, a usual
range); every loosening is in the script's history. Real chats from the pilot are the next test of
this, through the report's traces.
