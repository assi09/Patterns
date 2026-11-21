# Structured requests and validation (2026-11-18)

The independent follow-up audit is development material, not a held-out score. Its principal
failure was interpretation: correct tools were often called for the wrong dates or operation,
and correct evidence could still produce an unavailable or contradictory final answer.

Scope authorized by Karim on 2026-11-18, now implemented locally:

- Interpret requests into validated fields, including multiple metrics and operations, explicit
  comparisons, relative dates and references to earlier requests. Calculate calendar offsets in
  code. Ask when a reference has more than one possible subject.
- Preserve data scope and guidance topics independently in the existing private answer trace.
  Do not infer a request's dates from numbers in an assistant's prose.
- Answer supported descriptive requests directly from deterministic evidence. Check complex
  answers against both their request and evidence, including after the repair allowance is used.
- Require relationship and change claims to cite the appropriate statistical tests. Causality
  wording must distinguish an observed association, an inconclusive test and missing data.
- Correct pending drafts rather than leaving stale values on their cards; preserve future dates.
  Read confirmed food logs and keep check-in ratings distinct from derived recovery scores.
- Respect requests not to propose memory and distinguish access limits from medical refusals.

Validation: offline tests for new wording, unrelated intervening turns, ambiguity, calendar
boundaries, missing metrics, comparisons, drafts, food and memory; then the full backend suite.
Any paid validation is separately capped and logged. Future generalization results must come
from new conversations specified before their run, with the final prose reviewed as well as the
tool arguments and evidence. Do not report the old audit as a fresh held-out evaluation.

## Implementation

`backend/app/agent/requests.py` reads the question, registered metric names/units/capabilities,
the user's local date, server draft presence and prior validated request state. It does not get
health rows or computed health values. Constrained function output is parsed into typed fields.
Code resolves relative dates, calendar boundaries and references; checks metric identity,
aggregation capability, threshold units, comparison operators and compatible windows; and asks
when an antecedent is ambiguous. A contradictory aggregation or draft interpretation gets at
most one repair, within a two-call, $0.015 reader budget. An unresolved request never silently
becomes an all-history query.

Data scope and guidance subjects are saved separately inside the existing private `AnswerTrace`
JSON. The API loads traces only through owned messages in the selected conversation. This works
after a new agent instance and requires no database migration or public API/mobile type change.

`requested.py` executes supported precise requests through deterministic analysis and renders
the answer from those same evidence records. Multiple operations remain separate. Descriptive
observations/counts can be reported with sparse data, explicitly as recorded observations;
inferential comparisons retain their minimum sample requirements and share the run's multiple
testing correction. Missing values stay missing; an absent metric is never replaced by another.
Wear limitations accompany recorded activity. Broad investigations and coaching retain the
existing expert loop; its final answer check now runs even after the repair allowance is spent,
and rejected claims cannot survive in the fallback summary. Negative relationship/change claims
must cite the corresponding test.

Confirmed food is read separately from the wearable series, over the requested dates and meal
type, with names and recorded nutrient totals. The former 45-day loading cutoff is removed; wearable start dates do not bound food readback.
Unknown nutrient values do not become zero, and consumed energy is distinct from energy burned.
This is readback of logged entries, not a complete estimate of what the person ate.

For corrections, the model gets the actual owned pending card. The tools enforce a newly stated
duration/day and retain the card's previously validated facts, so changing its date does not
require restating its duration. Only a successfully prepared replacement cancels the prior draft. Multiple waiting
cards require clarification. Tomorrow cannot be moved to today to pass validation. Textual
confirmation still only points to the card: a tap is required for Google execution.

Guidance uses a concrete subject in the retrieval query. When a retrieved exercise title matches
the named variant, other variants are excluded, including short qualifiers such as RKC. The
writer may not borrow instructions from another variant; failed grounding cannot fall back to
the first exercise passage. Sources remain inspectable. Memory opt-outs suppress the listener,
including opt-outs understood by the reader without a fixed English phrase.

## What the live development checks showed

All data in these checks is made up. No Google writes or paid web searches were enabled. Each
plan was written to a new output directory before its first call. Previous results were kept;
new variants were not relabelled as successful reruns. Every captured answer was directly read,
and RAG replies compared with their retrieved passages. No paid model judge was used.

| Stage | Checks | What happened | Reported API cost |
|---|---:|---|---:|
| Initial smoke | 15 (10 answers, 5 reader-only checks) | 14 passed; other-person access was clarified instead of limited; fixed | $0.011193492 |
| First fresh synthetic set | 83 | 72 automated passes; direct review also found a squat cue borrowed from a weighted variant, so one of those passes was partial | $0.061797732 |
| Fresh set after constrained decoding/variant selection | 78 | 75 passed; all 34 initial metric lookups and all 34 date-shift follow-ups passed; multipart, guidance attributes and food intent exposed three further cases | $0.081097904 |
| Four new probes plus replay of those 78 | 82 | All 4 new probes passed; 76/78 regression turns passed. Remaining failures: equality interpreted as a window comparison, and food carrying an extra wearable metric despite correct readback prose | $0.094112192 |
| Final contract regressions | 4 | All passed: strict, inclusive and equal counts, then confirmed breakfast readback with the right food name and consumed energy | $0.006452634 |

Total for this implementation's paid checks: **$0.254653954** across 262 turns/checks. Including
the two earlier independent audits (about $0.4588 and $1.330020434), the requested work remains
at about **$2.04 of the $3 ceiling**. Costs are reported token usage, not an invoice.

The repairs address general contracts rather than enumerating more follow-up wordings:
constrained output shape; additive versus non-additive metrics; a threshold count versus a
two-window change test; actual draft state versus historical food readback; concrete guidance
subjects versus answer-format attributes; and exercise variant identity.

Raw plans, replies, evidence, summaries and the synthetic frame stay in ignored directories
`data/eval/typed_requests_*_2026-11-18/`. Later runs additionally retain the script, implementation
hashes and provider completions for diagnosis. Run a new check explicitly with
`PYTHONPATH=backend .venv/bin/python eval/typed_request_check.py --split <split> --out <new-dir>`.
The script refuses an existing directory; `contract-regression` is a replay, not held out.
All cases currently in that script have now been inspected and are development material. The
historical split names do not make a later rerun a new held-out evaluation.

## Limits and next evidence

Final local verification: `cd backend && ../.venv/bin/ruff check . &&
../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q` — **1,920 passed**.
There are 95 additional tests relative to the 1,825-test starting revision. Focused checks also
exercise an actual replacement card and cancellation of its predecessor, confirmation remaining
a draft, per-account/per-conversation state loading after a new agent instance, reader-service
failure, malformed output, bounded repair, missing data and unsafe fallback rejection. Existing
fixtures that claimed stability from `describe` alone were corrected rather than weakening the
new evidence-type rule. No mobile or public API contract changed.

These are implementation checks by the implementer, not an external blind evaluation. Most
questions are deliberately precise, on a synthetic table; they test metric/period identity and
retrieval, not the plausibility of a person's physiology. The 78-turn score belongs to the
version tested before the later contract repairs. **Do not turn the successful four-turn final
regression into an overall agent accuracy claim.** No final fresh end-to-end score on real
histories has been collected for this architecture.

The old 369-turn independent audit is now development/regression material and was not replayed
in this implementation check. Broad why/coaching questions, complex filters, long conversations,
guidance completeness and arbitrary wording still need a new independent conversation audit.
The existing PHIA results describe their recorded earlier revisions; they are not new results
for this request path. Live Google writes remain outside these checks. Local implementation is
ready for review; deployment and an external final evaluation are separate steps.

## Redesign after the third audit (2026-11-19)

Codex's live review showed that code rewriting the reader from phrases broke correct readings:
"24 hours earlier than that day" lost its shift to "that day". The redesign follows one rule:
**code checks the reader and never rewrites it**, except where only one reading is possible. The
acceptance criteria were written first, in [acceptance-structured-requests.md](acceptance-structured-requests.md).

- **Checks, not rewrites** (`backend/app/agent/checks.py`). Code reads the facts the words fix:
  dates written out, a shift such as "two days earlier", "that same day", "this week" or "last
  week", "the last N days", a metric called by its catalog name, a named meal, and "above 8,000".
  It checks the **resolved** request against them, so a correct reading passes however it was
  expressed: an explicit Mar 1 passes "two days after Feb 28" as well as a relative shift does. A
  contradiction goes back to the reader once, stating it; if the reader keeps it, the person is
  asked a concrete question ("Do you mean Mar 1, 2024?"). A check holds only where its phrase
  belongs to one part: "shift steps two days earlier, and my heart rate yesterday" checks neither
  part against the other's words. A negated or quoted metric name is not asked for. What code
  still fills in itself has only one possible reading: "don't save" wins; a count with no
  threshold that asks about recording counts days with data; with no earlier request, a period
  "relative to the earlier request" can only mean today.
- **Investigations keep their scope.** They resolve references as data questions do ("why did
  that happen?" keeps that result's metric and days; a chosen earlier part is the one used;
  `every_metric` looks across everything over those days). Named days are never swapped for
  recent data: days the data never reaches get a reply by code saying so; a short period is
  described on exactly its days; a second named period is the baseline. Coaching uses the named
  period and metrics, and the latest-day snapshot is left out when days were named.
- **Forgetting is a card.** "Forget my old running goal" has the small model pick the one kept
  fact it means (or lists the kept facts when it is not clear). A "Forget this?" card then waits
  for a tap: Forget deletes the fact, Keep it drops only the card. A change ("it's Tuesdays now")
  stays the listener's replacement card. This adds `memory_facts.forgets_id` (migration 0031)
  and `action`/`forgets` to `MemoryFact` in the app's contract.
- **Workouts and mixed messages.** A workout's end is its start plus its duration, by code,
  unless both clock times or a pause were said: a 34-minute run had been carded over 94 minutes.
  A message that logs something and asks about the data is read as logging with the question in
  `parts`; code answers the question in a fixed note that stays when the card's note replaces
  the reply.
- **Guidance follow-ups.** The passages a guidance answer used are kept in the request state; a
  follow-up on the same movement reads them first, and another movement never gets them. When
  no exercise title matches the topic word for word, the small model picks the same exercise and
  variant by meaning ("unweighted squat" is the bodyweight squat, not a barbell one), and other
  exercises are left out. The movement itself is searched as well as the reworded question.

All of this is checked offline with scripted readers and made-up data: Codex's 13 live-review
counterexamples and 7 fix-review counterexamples are in the suite and pass. **No paid run has
tested it.** Whether the real reader produces these readings, and how often a check sends back
a correct one, is for the fresh frozen audit the acceptance criteria describe.

## Clauses (after the v4 audit and the reader replay, 2026-11-19)

The replay ([reader-replay-2026-11-19.md](reader-replay-2026-11-19.md)) showed most misses came
from the reading's form, not from misunderstanding. The reader now returns the message as an
ordered list of **clauses** (`backend/app/agent/clauses.py`), each with only its own fields and
the words it came from: data, investigate, guidance, log, correct, status, confirm, memory, other.

- **A log has no data part**, so a workout draft can no longer become "which earlier
  measurement?". A data clause with neither metrics nor an earlier result is sent back.
- **Several requests in one message are each answered.** Precise reads beside a log, status,
  confirmation, memory request, guidance or investigation are answered by code in a note that
  survives the card's note. **Status** is read-only and answered from the chat's actual entries
  (waiting, saved, failed, none).
- **A period kind per meaning**: written dates, a calendar period, an earlier result's days, a shift
  of them, N days ending today or on the earlier result's last day (with an offset), all history.
  "The 5 complete days before today" and "that date and the three before it" have exact forms.
  Code converts each into the internal period and does all the arithmetic, as before.
- **Checks use each clause's own words**: dates and ranges written in a clause must be that clause's
  first and last days (swapped dates between two metrics are sent back); "the last N days" is
  checked for length and end; comparisons read negation ("no higher than" is at most). A reading
  without clause words is checked against the whole question as before.
- **Memory**: the action (remember, recall with its scope, forget) is separate from "store nothing",
  which never stops a forget. An explicit remember reaches the listener however it is worded, and
  a forget goes straight to the forget card unless it also states a new fact. What was said in
  this chat stays recallable in this chat even when it was not to be kept.
- **Investigations deliver what was asked**: coaching with no option gets one supported by their
  own days, or a plain "none is supported"; a "why" with no tested relationship says what the data
  cannot tell apart.
- **Guidance**: a reply that fails its checks while the right passage was found gets one rewrite,
  told what failed; "the prescribed number of repetitions" is exercise language, not medical; a
  follow-up with a known topic is looked up under it instead of "which exercise or food?".

Each reading's fate (stage, outcome, check codes, shape, no words or values) is kept in the
private trace. Older scripted fixtures with a flat reading are still accepted; the real reader
only gets the clause schema. Offline tests use correct clause readings written from the audit's
frozen expected meaning, plus the replay's bad readings where they show a check working.

## After the v5 audit (2026-11-20)

The [v5 audit](independent-audit-v5-handoff.md) recorded 66 pass, 8 partial and 17 fail over 91
turns. It found the reader usually right and later code losing or contradicting its decision.
All 25 turns that did not pass are targeted below; they are development material now, so a
fresh frozen set is what can measure the change. The [plan](pr-195-v5-reliability-plan.md) fixes the places
where that happens, by rule rather than by wording. Nothing here was checked with a paid run.

- **Date relations.** New period kinds: `after_earlier` / `before_earlier` (the N days right
  after an earlier result's last day, or right before its first) and `month` (a named month and
  year, past or future). A block next to a comparison's two periods asks which one. Checks now
  tell an endpoint from an interval: "that day as the last of five consecutive days" is checked
  for its length (five), not sent back as "the same days"; "the six days following that block"
  must start the day after it; "move that range forward one day" is still a shift. A follow-up
  that names and moves no period keeps the earlier days; "exclude the days on the boundary" keeps
  dates and threshold and makes the comparison strict; a named month must be that whole month,
  and "January through March" is one period while "compare January with March" is two.
- **Operations against what they count.** `count` with no threshold on one day, or with no
  words that count days, goes back to the reader as a value. A nutrient named as a metric reads
  confirmed food; a clause mixing a nutrient with a wearable metric is sent back to be split.
- **Each clause is executed.** A validated log clause reaches the logging expert whatever the
  router said. Side reads keep their claims apart (`AgentResult.side_claims`), so a card's note
  replacing the reply keeps their evidence IDs, which the API stores and reopens. Prose may not
  claim a draft or a write the store does not hold, on any turn. A correction the model did not
  make is made by code from the card's own values through the same tool and checks (a new day
  keeps the local clock time in the account's zone and the real elapsed time, added to the UTC
  instant, so a workout spanning a clock change keeps its length and a paused one its active
  time); if it cannot
  be (a paused workout), the old card stays and the reply says so.
- **Memory resources.** Whether a preference is "still saved" is recall, not tracker status. A
  "keep this out of my profile" read as a forget with nothing to forget says nothing is kept.
  Read-only turns (recall, status, confirmation, correction, conversation readbacks) are never
  listened to for new facts.
- **Investigations.** An explicit diagnosis request gets the fixed boundary reply before any
  data is read, and medical words never let an investigation override the router's refusal.
  Coverage is checked per metric and per period (a future month, a metric missing on those days,
  a missing baseline, partial coverage). A run with no verified answer describes its named
  metrics over its named days. Coaching with no supported suggestion of its own is said by code:
  the verified observations, then the one conclusion the tested habits support, cited; the
  model's prose is dropped however it is worded. Coverage notes are per metric (one missing
  beside another) and, for several metrics, give the days recorded together. In a broad
  overview, every metric the summary names is cited from the overview's own test, checked
  against what the clause says of it (up, down, steady); a sentence no record or verified claim
  supports is left out, and with none left the overview's clear changes are listed by code. Parts of a whole (time in bed and time asleep, stages, efficiency, distance
  and steps) cannot be correlated as explanations.
- **Guidance.** A qualifier topic ("no equipment") folds into its movement instead of becoming a
  second subject; a follow-up on two movements asks which by name. With a known topic and its
  vetted passages, the passages are read before any source is chosen; a chooser with no tool
  call no longer bypasses them (its "no" still stands). Cited and saved passages are those that
  share the reply's words.

Tests: `backend/tests/test_v5_reliability.py` (130), each failure beside a control and a minimal
pair with a different answer, including the regressions found in review of these edits (two date
cases, a mixed-source loss, daylight saving twice, coaching wording, a metric hidden by another).
Not done: a fresh frozen evaluation; paired-phrasing consistency is for that run.

## After the v6 audit (2026-11-20)

The [v6 live audit](independent-audit-v6-handoff.md) of `9684d77` passed 209 of 254 fresh turns
fully (19 partial, 26 fail); direct lookups 67/68, actions 18/18 and explicit memory 20/20 held,
while eight follow-ups answered the old interval and a "same week" count used the wrong week. Its
45 non-passing turns had six causes, each fixed as a rule. Nothing here was checked with a paid run.

- **Absence is read from the whole message.** The reader's copy of a clause's words can stop
  short of its dates, so "the words name no period" sent the right "next two dates" reading back.
  A one-clause message is checked against the whole message, and "dates" counts as a length.
- **A baseline beside a period in the same message** ("Sep 12-25 compared with before") counts
  from that period, not from an earlier chat result; a block next to an earlier result still uses
  it. "February of 2027" is February 2027, and "same week" is the earlier days.
- **Source and statistic.** An earlier food read continues only when the clause names no metric;
  "calories" is energy eaten only beside nutrients or in an explicit food read, never when the words
  say burned. Metric aliases ("physical stress-signs score" is the stress score) are given to the
  reader and read by the checks. A statistic the words name ("the lowest day's value") must be the
  one computed. "MY sleep score" asked for a teammate is the person's own; a "what lines up with
  the change" investigation is an explanation.
- **Overviews and relationships.** "The rest looked steady" is checked against every tested metric
  it covers; a false one is left out and the clear changes it hid are listed, cited. A relationship
  with no paired days gives each metric's own coverage, cited, or says the days are outside the data.
- **Guidance.** Passages for variants nobody asked for (barbell, single-arm, clock, wide) are left
  out when a plain one is there, the plain movement is searched by its head noun, and a cited
  passage must be about the topic. One earlier answer's topics named in parts ("desk worker",
  "interrupt long sitting") are one routine; two exercises are still asked about.
- **Memory.** The listener runs only when the message itself tells something (a statement or an
  explicit remember, read clause by clause); a pure question, however personal its words, raises no
  candidate. Checked in the store, not only in the listener call.

Tests: `backend/tests/test_v6_reliability.py` (56), with the v5 file's listener control updated
to this rule. The v6 decks are development material now; a fresh frozen set is what can measure it.

## Explicit anchors instead of word checks (2026-11-20)

Three audits showed the pattern checks in `checks.py` both rejected right readings and let wrong
ones through, one wording at a time; each fix added a pattern. They are gone. The reader now
states what each relative period hangs on (`relative_to`: an earlier result or this clause's first
period), the data source (`source`: food log or tracker), whether a guidance question refers back
(`refers_back`) and whether it is a medical request (`medical`). Code still does all the dates. An
overview is said by code from its own tests, each cited. Guidance passages are chosen by the small
model's variant pick, and only those the writer reports using are cited.

A small-model read-back of each resolved request (`readback.py`, gpt-5.4-nano) was built and
measured: it sent back correct readings ("the 3 days leading into it", an explicit day, an
equality count) in at least 6 of about 20 checked turns, then asked confusing questions. The
reader's first reading had been right on 162 of 163 data turns in v7, so the read-back is off
(`read_back_enabled`), kept with its tests.

Live checks by Claude (same harness and rules as Codex's v6; not independent):

| Run | Commit | Turns | Fully correct | Both wordings | Notes |
|---|---|---:|---:|---:|---|
| v7 | `4582185` | 226 | 205 (90.7%) | 101/113 | metric openings 68/68 and their adjacent-period follow-ups 68/68 (34 metrics, both wordings); investigations 0/12 (every cold-start baseline asked "which earlier measurement?") |
| v8 | `0d858a0` | 94 | 86 (91.5%) | 40/47 | metric openings 24/24 and follow-ups 24/24 (12 metrics, both wordings); thresholds, missing data, safety all full; investigations 6/12 (5 partial, 1 fail) |

The v8 deck ran first, for 34 turns, on the read-back commit; Claude saw 7 of those answers before
the same frozen deck ran again. Still weak: an investigation read as a data comparison of eight
measures instead of every measure; an overview with more than eight clear changes counted the rest
without naming or citing them (fixed after the run: every clear change is named and cited); the
fixed "what this can't tell apart" line shown when nothing
changed; one explanation that was only that line; "Just breakfast." read as a possible log; one
caffeine answer from the web instead of the vetted passage. 4,154 checked numerical fields
matched the source rows. The harness's frozen clock had given every message the same time, so
history in chats of three or more turns had no order; v8 fixes that in the harness, and v6 and v7
three-turn results may include failures from it.

## After the independent audit of `b730fda` (2026-11-20)

Codex's audit of the frozen head ([handoff](independent-audit-b730fda-handoff.md)): 90/110 fresh
turns fully correct, both wordings 37/55. Direct lookups 24/24, mixed requests 8/8, memory 16/16
and the PHIA B1 gate 24/24 held. Adjacent-period follow-ups 15/24, investigations 5/12, guidance
2/4. Each failure family was traced to its code path and fixed at that point, not per wording:

- **A follow-up's new days state both edges.** "Start at the next date and cover three days"
  after Sep 2-5 was read as three days *ending* the day after (Sep 4-6), on 9 of 12 metrics; the
  schema offered two kinds that could say the same thing differently (`days_ending` from an
  earlier end, and `after_earlier`). Those kinds and `before_earlier` are replaced by one,
  `beside_earlier`: which day of the earlier period it counts from (`its_first_day` or
  `its_last_day`), how many days from there, whether the new period starts or ends on the day
  reached, and its length. `days_ending` now counts only from today. Tests cover every edge,
  offsets from -2 to +2, lengths 1-31 and four anchors (leap day, year end), and the audit's pair
  with a trailing-window control that must give different days.
- **A food follow-up keeps its day.** "Switch back to meals, breakfast only. How many calories?"
  was sent back as a mix of sources; the retry dropped the day and read back to 1970. A named
  meal exists only in the food log, so it reads the food log; and every retry now tells the
  reader to change only what the error is about and keep the rest, periods and metrics included
  (the same retry turned an overview of every metric into eight named ones). The regression
  fixture has two confirmed breakfasts on different days, so a lost day changes the number.
- **Evidence reopens as it was used.** A test cited again with its p-value adjusted for another
  run's family kept its id, and storage kept only the first version: 7 of 237 reopened citations
  showed another run's p-values. A stored record now never changes; one cited again with other
  contents is stored as a version (`<id>~<digest>`), and that answer, finding or alarm cites it.
- **What the person reads is only what a record tested.** "Keep activity spread across the
  week" was accepted because higher average steps was a significant test; Codex's reviews then
  showed bedtime-and-sleep evidence, and a single breakfast entry, each accepting "spreading walks
  across more days". The rule is now one for every coaching path. A suggestion names in `option`
  the key of what it offers, and the verifier accepts only an option a cited record tested: a
  supported habit_options lever (timing, regularity, rest, activity, dinner, wind-down), a
  personal_options option, or the habit side of a significant association or weekday split. A
  change in a measure, a meal logged or a saved fact tests no action, so alone it backs none.
  Every coaching answer, in an investigation or not, is then said by code: each bound option in
  its record's words, up to the number asked for, else the outcome of the tested habits (an
  option, none among those tested, or too little data). An association or weekday split is said
  as something to keep an eye on together, never as a change to make. Observations are said from
  their tests, and the model's prose and its other advice claims are dropped, so neither can bring
  advice back. A saved fact cited beside a bound option is quoted to say how it fits. The only
  other advice a coaching reply can show is the top-up of general passages when more points are
  asked for than were tested, marked as general guidance from the sources.
- **Nothing changed, nothing to explain.** Explaining a look across measures where none changed
  clearly is said by code (nothing changed clearly, cited, so no change to explain), without the
  "changes seen over the same days" limit line. Prompts no longer tell the model to say measures
  "held steady"; a test that finds no change does not show none.
- **Every measure, however typed.** A data clause can say `every_metric`; it becomes the
  overview across every metric over its days, so "contrast my full set of measurements" is a
  comparison, not eight metrics' averages.
- **A paused workout.** Elapsed, active and paused time are separate facts; a stated pause
  ("15:00 until 15:40, 10 minutes paused") no longer refuses a right draft, and a refusal names
  what the draft has against what was said.
- **Guidance variants.** The variant pick treats grip, hand and foot positions (close, wide,
  narrow, sumo) as variants, so the standard push-up is the plain passage.

These change model behaviour (the reader's schema and prompt, the verifier); no live run was made
after them. The next independent run should reuse fresh paired wordings for these families.

## Edits to an earlier result or card (2026-11-21)

Codex's review of `a196c6d` ([plan](a196c6d-root-causes-and-fix-plan.md),
[audit](independent-audit-a196c6d-handoff.md)) showed that the date executor reproduces all 48
date follow-ups of the last two independent decks when given the intended edit, while the live
agent got 30/48: 13 of the 18 misses had the right number of days on the wrong side of, or at
the wrong distance from, the earlier period. The work moved from adding follow-up wordings to
making the edit explicit:

- **One computation for every edit of an earlier period.** `from_earlier` replaces the same-days,
  shift and beside kinds: the earlier first or last day it hangs on, an offset, whether the new
  period starts or ends there, and its length. The reader sees each earlier result with its
  actual first and last day and number of days (`earlier_results`), not raw state.
- **The card is an object the reader sees.** A correction gets the waiting card's day, start,
  active, elapsed and paused minutes; a day said against the card is `days_from_card`; a duration
  the card already has is no change. A correction the reading fully states is applied to the
  stored card by code before any drafting model runs, and a replacement that changes an
  untouched duration is refused, naming the field. With no card waiting, a correction reading is
  sent back.

**Matched reader comparison** on identical inputs (development data: the 48 historical date
follow-ups and 6 workout edits), gpt-5.4-mini, read-back off:

| | Current reader (`a196c6d`) | Edit reader, length optional | Edit reader, length required |
|---|---:|---:|---:|
| b730 date follow-ups | 24/24 | 22/24 | 24/24 |
| a196 date follow-ups | 16/24 (8 rerun, 8 from the a196 audit) | 23/24 | 17/17 run |
| Workout edits | 0/2 paused moves (a196 audit) | 6/6 | not run |
| The 36 cases all three ran | 32/36 | 34/36 | 36/36 |
| Unnecessary clarifications | 0 | 0 | 0 |

The optional length was the weak spot: "three calendar days" and "four days up to the day before"
came back with no length, so the earlier length was kept or the four went into the offset; the
length is now required (the earlier number of days when none is said). One reading moved a card
when none was waiting, which the no-card rule now sends back. The last run stopped at its $0.08
cap with 7 a196 date cases and the 6 workout edits unrun. These are development cases; the release
decision needs an unseen deck with new paraphrases, scored on exact dates and unchanged card
fields through the normal API.

Fixes from the same review that need no smarter model:

- An explanation or coaching follow-up that names no new days keeps the single investigation under
  discussion; a new broad question still gets the default. An investigation of two periods is the
  later against the earlier, however they were said.
- Switching from food eaten to the tracker keeps the days and the energy: an inherited food
  operation becomes the tracker's value for one day, or its total or mean over several.
- An overview counts measures, not records: the latest record of each metric over each pair of
  periods speaks for it (32 metrics were "39 measures").
- Each habit lever says what its comparison permits: an action when the days differ in the habit
  itself (bedtime, activity, a late meal), a pattern to watch when they differ in something else
  (a stress tag, a hard day before). A stress-tag split is no longer "a wind-down routine".
- An instruction for this answer ("give me three options here") is not something told about the
  person, so it makes no memory card; "I generally prefer three options" still can.

## After the independent audit of `9228fe6` (2026-11-21)

Codex's audit ([handoff](independent-audit-9228fe6-handoff.md)) kept the paused-workout repair
(8/8), memory (6/6), evidence versioning and PHIA B1 (24/24), and held the merge on dates (16/24
follow-ups), investigations (3/16), food (3/6) and guidance (0/4 fully correct). Its offline
root-cause checks named the earliest wrong field in each; the changes follow them, with the
controls it named:

- **A reference keeps its days before the source picks the operation.** A part that points at an
  earlier result (by reference, an inherited operation or no metric of its own) and names no new
  days keeps that result's days; "keep the date, burned energy now" had read the empty period
  list as all history and summed 150 days. Explicit whole history, an explicit new date and a
  cold total are unchanged.
- **One look written twice is one look.** Beside an investigation, a whole-registry data clause
  over the same days goes, and an investigation that names no days takes the one scope the
  message's data clauses share. A side read of named metrics stays; a whole-registry clause over
  other days is kept, not dropped. A meal read with no metric is never a look across everything,
  and never needs an earlier result.
- **A whole comparison is reused whole.** `same_as_earlier` is back, for all of an earlier
  result's periods unchanged; `from_earlier` is only for editing days. Both wordings of "why"
  after a two-period look had come back as two single-period edits. The guard that asks which
  period an edit of one side means is unchanged.
- **The last answer again, in another form, keeps its request.** A `redo` clause ("give me up to
  three options here, saying which are personal") answers the last request again with its scope;
  after a look at their data, options asked for are coaching on that look. It was read as small
  talk, and the habits were then tested on the default two months.
- **Coaching on a comparison says which period it tested.** The habit tools take one period: the
  later one of the comparison, said in the reply, never the enclosing range.
- **A meal is kept by name or time of day.** The reader is told "that morning only" is breakfast
  and that intake is the food log; an absent meal still means every meal.
- **A failed variant pick authorizes no other variant.** Title neighbours and the titles the pick
  sees are ordered closest first (most shared words, fewest extra), so the plain entry is inside
  the 25 titles; the fallback normalizes words one way ("push-up" is "Pushups"), keeps passages an
  earlier answer established for the movement, and with no word-for-word title offers no exercise
  passage instead of every candidate.

No live run followed: these are offline repairs with the audit's cases and controls as tests
(`tests/test_r922_reliability.py`). The release decision needs fresh paired conversations under
the unchanged gates.

## After the independent audit of `b3d64ca` and the general repair plan (2026-11-21)

Codex's audit ([handoff](independent-audit-b3d64ca-handoff.md)) confirmed the food chain (10/10),
guidance (16/16), comparison and coaching scope, card patches and evidence versions, and held the
merge on five date follow-ups and one correction moved the wrong way. Its
[general repair plan](pr-195-general-repair-plan.md) named the contracts behind those and three
more defects its offline probes reproduced. Each change below enforces one invariant, tested with
the plan's reproduction and its contrasting control (`tests/test_b3_reliability.py`):

| Section | Invariant now enforced |
|---|---|
| F | An unknown habit exposure is in neither group: a night with no bedtime, or a day with no strain, is not a "later night" or an "ordinary day". Adding unknown rows does not change a known-pair result. |
| E | The run's correction family counts hypotheses, not records: an identical retest under a new id is one test (0.03 and 0.07 stay at 0.06, not 0.045); a different test of the same metric is another. |
| D | Every result of an answer is addressable next turn, its side reads included, and the last answer's kind is kept: "that again" after guidance redoes the guidance. Two clauses are one look only for the same periods of the same result. A comparison of every measure over other days runs cold, as an overview. |
| A | The trace outline keeps every field of a date edit (landmark, offset, boundary, length), a correction's signed move and a redo's count, so the first wrong field of a reading is visible without another call. |
| B | A redo keeps the data or is sent back: the reader states `keeps_the_data`, and a shorter period is a data edit. A reading that is neither small talk nor something about them, and no request the app can run, gets one question naming the last result, never a default data run. |
| C | A reported date error ("two days too early") is `card_was` plus days, and code derives the move; an instruction to move is still `days_from_card`. The reader is told that a new edge on the earlier edge is offset 0. |
| G | Coaching is assembled once: an investigation's options are said by code first, then topped up with labelled general points up to the number asked for, which the reader now states (`points`) instead of a word count that never recognised "options". |

The C and B reader changes, and `points`, are prompt and schema changes with no live measurement
yet. The plan's matched-reader step and Codex's unseen paired deck decide whether they help.

## After the independent audit of `689fa7c` (2026-11-21)

Codex's expanded audit ([handoff](independent-audit-689fa7c-handoff.md)) of 592 fresh turns held
the merge: 504 full, 33 partial, 55 failed, with direct metric openings at 68/68 and date
follow-ups at 44/68. Grouped by first wrong decision, most failures share a few causes. Twenty
were a redo that could not carry an edit, and seven were a date edit's offset given for the
wrong end. Three were a dated follow-up with no metric read as every measure. The rest were
actions, memory, option assembly and reply wording. Each change below enforces one contract
across question families, tested with the audit's reproduction and a contrasting control
(`tests/test_689_reliability.py`):

| Handoff § | Contract now enforced |
|---|---|
| 1 | A redo says the request it repeats, field by field, as a data clause does: its periods (required, `same_as_earlier` to keep them), statistic (`inherit` keeps it), measures, comparison, threshold and lag (null keeps them). The `keeps_the_data` flag is gone: it was the same reader judging its own choice. Changed, the redo is the earlier request with what it keeps inherited, resolved as that request's own kind. Unchanged, it is the last answer as it was (guidance, a status with its figure, a look). |
| 1 | A date edit places the new period's first day, its last day or both, each named for the day it is, plus a length. The single offset with a starts/ends flag was misread one way every time: the offset given was always the start. Code checks that two placed days and a length agree, and sends back a period with nothing placed or no length. Recorded readings in the old form still parse as the day their boundary named. |
| 1 | Naming no metric keeps the earlier result's metric when there is one. Only a cold question, or an explicit `every_metric`, is every measure. |
| 2 | The reader sees each earlier result's comparison, threshold, lag, meal and scope. A follow-up's lag left null keeps the earlier lag. Older results stay addressable by index after the last answer's ("return to the steps result" after other answers). |
| 3 | A paused card's duration edit says which duration it is (`duration_is`) and any pause stated. Code works out active and elapsed time from the card, and the draft must match both. One duration on a paused card with no basis gets one question naming the pause. The reader's validated day binds the action's day checks, so the day pattern no longer refuses "Oct31", and its exercise type replaces a generic one. A status question reads the waiting card's values. |
| 4 | A clause counts as copied when an earlier message holds nearly all its words and holds more of them than the current message does. Such a clause is dropped when the remaining clauses cover the current message, and sent back otherwise. Remember and forget get only the memory clause's own words. The forget picker sees the turns just before. "Nothing is kept right now" replaces "nothing has been approved". |
| 5 | A coaching answer's public guidance is searched for the resolved request's measures, or the ones its habits were tested for, never for the follow-up's words about form. General points are labelled with their source. A count the evidence and sources cannot reach is said. |
| 6 | A food read carries the nutrients it asks about. An unrecorded one is said unknown, never repeated away or given as zero. A food-scope retry keeps the fields its error was not about (`RetryReading.keeps`). A request to join two sources, or to invent a value or evidence, is a typed field with a reply in code. A constant series and a too-few-days association cite the records that show them. A guidance topic keeps its base movement. An exercise with no vetted passage is said so, never answered from another exercise or the web. A medical flag needs its words from the current message. |
| Unplaced | An `other` clause that is neither small talk nor about the person, or a reading with no clause, goes back once with what a follow-up can be, before anyone is asked. |

The redo, date-edit, `duration_is`/`paused_minutes`, `exercise_type`, `movement`, `nutrients`,
`fabricate`, `mix_sources`, `medical_said` and `message` fields change the reader's schema and
prompt, and none has been measured live: no paid call was made for this round. The awake-time
wording for PHIA B1-021 is a prompt change of the same kind. Not addressed here: the
investigation prose that calls a measure steady or "run down" without a test (handoff §6) needs
the verifier to check adjacent prose, a larger change.

## After the offline review of `40baaee` (2026-11-21)

Codex's offline review ([findings](pr-195-40baaee-offline-review.md)) reproduced seven gaps the
suite missed, with supplied reader fields and no paid call. Each fix enforces the contract and is
tested with the review's reproduction and contrasting controls (`tests/test_40baaee_review.py`):

| Review § | Contract now enforced |
|---|---|
| 1 | A redo's lag is an edit when it is said and differs from the last answer's own lag; 0 is a value (the same-day test). Null keeps it. A lag beside an answer that gave no association (guidance, memory) is no data edit. |
| 2 | An explicit statistic wins over a look's description: "the median steps for those dates" after an investigation is the median over its days. With no measure named it takes the look's measures. After a two-period look the single-period guard still asks which. An unchanged redo stays the look. |
| 3 | A duration with a basis is compared only with that duration of the card. A new active time equal to the old elapsed time is an edit (40 active, 49 in all), and the same holds the other way. With no basis, either duration restated is still no change. |
| 4 | The state keeps the whole delivered request (`answer`): kind, main results and side reads, status, recall scope, guidance topic, focus. An unchanged redo replays all of it: a recall with its figure, a status with no figure, guidance with its side read. It never replays older data the last answer did not give. A memory change is replayed as what is kept now, and a card as its status, never another write. A state saved in the old form is read the same way. |
| 5 | A retry's kept fields go back onto the data clause with the same words, only when exactly one matches. Reordered clauses keep their own sources, and nothing moves between clauses that cannot be told apart. |
| 6 | Coaching options asked for on days with no data keep the data limit. They are answered with labelled general points from vetted sources on the measures asked about, the shortfall is said, and the reply says none is personal. With no measure to look up, it says why no options are given. |
| 7 | An explanation ("why") says only what its verified claims say: its shown text is assembled from them, and what cannot be told is code's note. The model's surrounding prose had added "feeling more run down", which nobody reported and no tool measured. A reply written by code, or one with no verified claim, is left as it is. |

Codex's probes (`data/eval/40baaee_review/probes.py`) now give the expected result for every case
but the direct verifier replay of the old "run down" answer, whose checks are unchanged. The
reader schema itself is still unmeasured live.

## After the offline review of `462f700` (2026-11-21)

Codex's next review ([findings](pr-195-462f700-offline-review.md)) found that §7 above was not
enough. The joined claim texts were still the model's: an unreported outcome ("You have been
feeling more run down", "You have been walking to work") written inside a valid steps-change
claim was accepted and published. It also found two replay boundaries. Fixes, tested with the
review's reproductions and controls (`tests/test_462f700_review.py`):

| Finding | Contract now enforced |
|---|---|
| 1 | An explanation's shown text is stated by code from the records its claims cite (`findings.code_claim`): each record once, in citation order, as a fixed sentence of its own statistic. That covers a change or no change with its figures, a trend, or an association with its correlation. A record says nothing beyond its metric and statistic, so no claim text the model wrote is published. A computed check-in result is said as its rating, and an association as the test, never a cause. When nothing cited is a finding code can state, the reply says it can't tie an explanation to a tested result. The verifier's claim checks are unchanged and still accept such claim text, so the guarantee comes from assembly. |
| 2 | A state saved before whole answers were kept replays a kept result beside guidance, a recall or a status only when the last turn's own verified claims name its metric. A plank answer no longer reopens an older resting heart rate. Older results stay addressable by index. New states keep their exact components. |
| 3 | The saved answer keeps its point count. An unchanged or edited repeat inherits it, and a new count wins. A new question starts with its own. |

What this costs: explanation answers now read as code's statements of the tested results plus
the limits note. Model-written linking or attribution ("you said you've been tired") is not
shown. The reader schema and these assembly changes are still unmeasured live; the next step is
the capped matched-reader comparison.

## After the review and matched-reader comparison of `e1c1eec` (2026-11-22)

Codex's matched comparison ([handoff](independent-audit-e1c1eec-handoff.md)) put the new reader
at 133/150 against 103/150 on exposed development inputs, with 42 improved and 12 spoiled. Most
of the spoiled cases were one regression: "the next four days after that block" fell from
12/12 to 3/12, because the reader placed the new last day where the first belonged. The review
also found renderer and target-scope gaps. Fixes, tested with the review's reproductions and
controls (`tests/test_e1c1eec_review.py`):

| § | Contract now enforced |
|---|---|
| A | A record is stated by its own tool's meaning, with the figures that tool holds. A window comparison is "went up: X against Y" and a change point is "went up around <date>: X after against Y before". A weekday split compares weekend days with weekdays, and a tag effect compares tagged days with untagged ones, as a value claim, never a change. Each stated claim passes the verifier again. A record with too little data or a figure missing is not stated, and the reply notes the omission. The renderer never writes an empty sentence and never falls back to the model's words. |
| B | A block right after or before an earlier period (`block_after`, `block_before`) or the whole period moved (`whole_shifted`) is its own period kind. The reader says the relation and the count, and code works out the boundary, or keeps the width for a shift. Placed endpoints (`from_earlier`) stay for anchored ranges inside or ending on the period. Neither the arithmetic nor the placed form changed. |
| C | A repeat says its target (`same`, `named`, `every_metric`) apart from its statistic. Every measure asked for is every measure. A broad look edited to a comparison keeps its breadth, and either way the result is the existing overview. Measures a repeat states are the ones used. A target that contradicts its metrics goes back. A repeat beside a status, a recall or guidance is resolved too, and what it repeats becomes that answer's reads. |

Checked offline, at no cost: replaying the candidate arm's 152 recorded readings through this
code and scoring them with Codex's frozen `score` changes nothing that passed (135 of 135). It
turns one failure into a pass (`main_side_scope-01/t3`), and with its stored full claims
`mixed_log-01/t3` passes too. The successor-block regression and the other reader-choice misses
cannot be fixed by replaying old readings: the new period kinds and `target` need the matched
reader step again, with the protected before, ending, trailing and calendar controls. Not
addressed: the chat-only recall miss (`memory_chatonly-01/t2`, D). The provenance guard stays,
and the retry still reads the recall as unsure.

## After the review and matched-reader comparison of `bcdb0ff` (2026-11-22)

Codex's comparison ([handoff](independent-audit-bcdb0ff-handoff.md)) put the reader at 146/152,
against 138/152 for the e1c1eec reader on the same exposed inputs. Successor blocks went from
7/12 to 12/12, with no other date relation spoiled. It also found three code gaps and three
reader misses. Fixes, tested with the review's reproductions and controls
(`tests/test_bcdb0ff_review.py`):

| Finding | Contract now enforced |
|---|---|
| 1 | One record-aware renderer (`code_claim`) for every observation a reply can say: explanations, coaching observations and the overview's listed findings. The old window-only renderer is removed. A coaching observation code cannot state is left out, the reply says so, and every published claim passes the verifier again. |
| 2 | A repeat beside another clause is composed by what it is (`_composed`). A repeated figure joins the request's results. A repeated look leads, and a status or recall asked beside it is answered under it by code (`_with_beside`). The same answer twice is one. A pair that cannot be answered together, such as a look and a guidance question, gets a question instead of losing one. |
| 3 | Equivalent results are kept once before execution and storage, main against side included, and the answer's counts are taken after that. A state already saved with a duplicate reads it once. Two different results still ask which. |
| Reader | A retry keeps a length the message said (`RetryReading.keeps` with `periods.length`, on the clause with the same words). If the retry still conflicts, the reply asks which days, never one day in place of the three said. The prompt says a follow-up asking for all of their history in place of the earlier days is `all_history`, never `same_as_earlier`, and that asking for the card that removes something kept is memory forget. |

Checked offline at no cost: replaying the bcdb0ff candidate's 152 recorded readings through this
code, scored with Codex's frozen `score`, changes nothing that passed (146 of 146). The duplicate
case now passes (`investigate_lowwear-02/t4`). The two lost-length cases now ask instead of
accepting a one-day window. The history-override and memory-removal misses need a live reader,
and their prompt changes are unmeasured.
