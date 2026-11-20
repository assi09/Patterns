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
