# Final audit of PR #195 — November 22, 2026

**Recommendation: end this audit/repair cycle and move on to the other project deliverables.**
There is substantial measured improvement. Keep the remaining issues in the
[deferred backlog](pr-195-followup-issues.md); this recommendation is not a claim that the agent
is bug-free or that it passes every original release gate. The two silent relative-period errors
still fail the original zero-wrong-period criterion. Memory and food remain weaker areas.
No further paid run is planned from this audit.

Candidate: **`910da27c912486dac18c7901ce6548df91a258fe`**, independently verified locally and
against PR #195, open/unmerged with required backend and mobile checks green. No production code
was changed, committed, pushed, merged or deployed by this audit. Google access/writes were
blocked. Local backend: **2,706 tests passed in 313.84 seconds**; Ruff and formatting checks pass.
The 224 focused passing tests are a subset, not additional live cases.

## Did it improve enough to stop iterating?

**Yes, substantially on the measured core flows.** The strongest comparison uses the exact same
592 questions, profiles, clocks, fixture actions and conversation sequences as the prior broad
`689fa7c` audit, executed again against the final candidate:

| Result on the same 592 turns | 689fa7c | 910da27 |
|---|---:|---:|
| Fully correct | 504 (85.1%) | **563 (95.1%)** |
| Partial | 33 | **7** |
| Failed | 55 | **22** |

That is **59 additional full results**, about **10 percentage points**, and **60% fewer failed
turns**. Paired ordinal outcomes: **74 improved, 16 worse, 502 unchanged**. Some failures cascade
from an earlier failed proposal; turns within a conversation are not independent trials.
The regressions are retained, including food's decline from 25/30 to 22/30.

For historical context, the earliest small audit's initial cohort was 28/49 full; the later
369-turn audit of `400d656` was 201/369 full (54.5%). Their mixes differ from this final set, so
subtracting those percentages would exaggerate the precision of a before/after claim. The
same-592 comparison above is the direct evidence of improvement. This evaluates the whole
candidate, not an ablation attributing each gain to one code change or excluding model variation.

## Final scope and method

- **592 exposed regression turns / 234 conversations**, covering all 34 metrics, direct and
  follow-up statistics, date relations and calendars, threshold/tie/zero/missingness controls,
  associations/lags, investigations/coaching, multiple results, memory lifecycle, confirmed food,
  draft/correction/status flows, exercise/routine guidance, boundaries, Arabic/French inputs and
  twelve-turn topic switching. Both prior wordings per family were retained.
- **48 newly frozen turns / 16 conversations** on existing made-up profiles, with new wording for
  dates, explicit all-history overrides, memory removal/chat-only recall, coaching, meals and
  compound replies. These are reported separately from the exposed regression set.
- **24 frozen public PHIA-derived B1 regression items**, using the same previously approved data
  transfer and historical sample. This is a small regression gate, not a new full PHIA benchmark.

All **640 synthetic turns were captured once and directly reviewed**, with independent arithmetic,
actual stored state, source checks and reopened messages/citations. A full result requires the
requested task, figures, metric/source, period, citations and applicable state to agree. Safe but
unnecessary clarification of a clear request is not a full result. No paid judge was used.
Original answers and failed attempts are retained. No completed answer was rerun to obtain a pass.

Synthetic freeze ID:
`9512da186679bb7b8acf884ef4c3b671e7ff9a2de7ae0196ec3e52bf2ff9bdee`.
Inputs, independent expected values and execution order froze before paid calls. The synthetic
phase's combined new-spend ceiling was $1.95. Private artifacts are under
`data/eval/910_final_inputs`, `910_final_results`, `910_final_review` and `910_phia`.

The 592-turn score is exposed development/regression evidence. The 48 new wordings reuse known
synthetic profiles and question families; they do not establish accuracy on an independent
real-world population. Scores are direct Codex judgments with mechanical checks, not blind human
ratings. Production Google behavior, mobile UI, DST-specific behavior and every possible wording
are outside this run. Historical official benchmark results remain separately reported.

## Results by area on the matched regression set

| Area | Previous full | Final full | Final partial | Final fail |
|---|---:|---:|---:|---:|
| Metric openings | 68/68 | **68/68** | 0 | 0 |
| Metric date follow-ups | 44/68 | **67/68** | 0 | 1 |
| Calendar openings | 24/24 | **24/24** | 0 | 0 |
| Calendar follow-ups | 18/24 | **23/24** | 0 | 1 |
| Thresholds | 29/30 | **30/30** | 0 | 0 |
| Associations | 43/48 | **48/48** | 0 | 0 |
| Investigations/coaching | 35/48 | **46/48** | 2 | 0 |
| Workout | 34/40 | **37/40** | 2 | 1 |
| Guidance | 37/40 | **38/40** | 1 | 1 |
| Memory | 28/36 | **30/36** | 0 | 6 |
| Food | 25/30 | **22/30** | 0 | 8 |
| Multiple parts | 32/36 | **34/36** | 0 | 2 |
| Coverage/quality | 26/28 | **25/28** | 2 | 1 |
| Boundaries | 27/32 | **32/32** | 0 | 0 |
| Long context | 19/24 | **23/24** | 0 | 1 |
| Multilingual inputs | 15/16 | **16/16** | 0 | 0 |

Arabic/French inputs were understood in these metric tasks; replies remained in English. This
is not a claim of fully localized responses. Coaching shortages that are explicitly disclosed
are allowed by the frozen requests; inventing unsupported options is not required for a pass.
Two coaching partials concern general food-choice advice outside the agreed habit-coaching scope.

## New wording cohort — 42 full, 2 partial, 4 failed of 48

| New area | Full | Partial | Fail |
|---|---:|---:|---:|
| Relative dates | 18/18 | 0 | 0 |
| All-history and explicit window restoration | 6/6 | 0 | 0 |
| Memory removal and chat-only recall | 6/6 | 0 | 0 |
| Coaching | 4/6 | 2 | 0 |
| Food/source follow-ups | 2/6 | 0 | 4 |
| Comparison plus status/recall, then explanation | 6/6 | 0 | 0 |

The two new coaching partials repeat a correct comparison but omit an explicitly requested causal
limitation. Food failures concern clearing meal filters, changing nutrients and switching from
intake to tracker expenditure. The new history/removal prompts work in these live examples;
that does not erase the distinct memory replacement and recall failures in the broad set.
Do not blend 42/48 with the exposed score and label the result held-out accuracy.

## Numerical, source, state and persistence verification

- **23,006 independently checked synthetic numeric fields: zero mismatches**, no unhandled tools.
  These checks do not excuse answering the wrong question with correctly computed numbers.
- **344 food-total/known-value/source-passage checks: zero mismatches.**
- **1,222 run-adjusted statistical records: zero correction-family mismatches.**
- **42 exact workout payload checks:** dates, start/end instants, active durations, activity types
  and single pending draft all agree with the frozen behavioral expectations. This includes paused
  and overnight corrections; correct payloads do not excuse an incorrect status/read response.
- **640 messages and 1,566 citation references reopened:** text and final cited payloads agree.
  **540 cross-account evidence/action access checks:** all refused with 404.
- No unconfirmed Google writes, approvals or removals of approved memory; no protected no-save
  fact changes in the checked workflows. A misleading memory-update acknowledgement still occurs
  when a requested replacement was not actually prepared; it is a failure, not a successful save.

An initial reopening checker flagged nine citation IDs across six coaching repeats. The checker
looked for the newly persisted version suffix literally in a capture already keyed by an older
suffix. Each base ID had exactly one raw candidate, and every payload field matched the reopened
record exactly. After correcting this reference matching, all citations pass; original flags and
nine exact-payload checks are retained. This was a checker issue, not evidence of lost versioning.
Side claims are checked using the full stored chat claims, not the capture's main-only claim list.

## PHIA: 24/24

All 24 final results have the correct cited metric, operation, accepted period and comparator,
with visible expected answers and **627 independent numeric checks, zero mismatches**. All 24
historical baseline items were fair; there is no final regression in this sample.

The initial gate completed 20 OpenAI readings. Four remaining readings were blocked by an overly
conservative phase reservation, producing `BudgetExceeded` fallbacks; they incurred only small
router charges. The first completion launcher stopped at a pre-call assertion because it had
incorrectly assumed those router charges were zero. It made no paid calls. After verifying that
there were exactly 20 OpenAI completions, only the four blocked readings were completed once,
with an additional $0.15 conservative reservation inside the existing $5 cap. The 20 answered
items were untouched. Initial fallbacks, completion plan and final results remain separate.
This is an infrastructure completion, not repeating four incorrect model answers.

## What remains and what stopping means

The [deferred backlog](pr-195-followup-issues.md) contains concrete examples and priorities:
wrong anchored-period roles; food source/nutrient/filter and whole-answer edits; misleading or
missed memory operations; movement continuity; coverage/status intent; coaching scope; and the
known offline policy-envelope/retry-preservation gaps.

Two main-set cases still silently use the wrong relative period (`metric_strain-02/t2`,
`date_endzero-02/t2`). Memory is 30/36, below the original 90% target. Thus this is **not a clean
pass against the original release criteria**, even though the improvement is large. PR #195 is
left open/unmerged. Ending repeated audits and moving to other deliverables is the practical
recommendation; it does not certify every feature or erase the recorded failures.

## Spend

| Final audit phase | New cost |
|---|---:|
| 640 synthetic turns | $1.782488472 |
| PHIA initial gate, including router-only blocked readings | $0.047878746 |
| Four blocked OpenAI readings completed once | $0.014146464 |
| **Final audit total** | **$1.844513682** |

Shared new-$5 cumulative usage: **$4.558264384** (OpenAI $4.437424630, Jev $0.120839754),
with **$0 unresolved reservations**; **$0.441735616 remains**. The old separate allowance is not
added. Offline tests, direct review, arithmetic, reopening and documentation cost $0.
No additional paid audit is planned. Complete private per-turn grades, paired transitions,
source/state checks and receipts are retained for review.
