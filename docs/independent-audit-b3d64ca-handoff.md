# Independent audit of b3d64ca — November 21, 2026

**HOLD PR #195.** The frozen candidate is
`b3d64ca33f7da5992890b20dd290c6bace660955`. Its food/source and exercise repairs work in this
sample, and comparison scope is substantially better represented. Five fresh date follow-ups
still answer different days, and one workout correction moves in the wrong direction. The
zero-tolerance named-period gate fails. Passing CI and 2,498 backend tests do not clear that gate.

## Candidate, method and results

Verified local HEAD and the remote open/unmerged PR head against the frozen SHA; backend and
mobile CI were green. Diffed against `9228fe6` before testing. Preserved the two pre-existing
untracked handoffs. No production code changed, and no push, merge, deploy or Google traffic
occurred. The harness disables writes and blocks every Google client request.

The new deck froze **36 synthetic conversations / 90 turns**, with two wordings per family,
before paid calls. Freeze ID:
`e75df02f499506e75b16768f6618fd24c7b160efd7ef219d07e7745084c7cdaa`.
It uses new seeds, dates and wording. One profile has a planted steps rise and sleep decline in
the requested focal block; the other is flat. Explicit history/new-metric controls, confirmed
food versus drafts, meal-filter removal, paused workout dates and four exercise variants/families
are included. The same previously frozen **24-item PHIA B1** sample is a separate regression gate,
not fresh conversation evidence. No paid judge.

| Area | Full | Partial | Fail | Paired turns both fully correct |
|---|---:|---:|---:|---:|
| Direct metric openings | 16/16 | 0 | 0 | 8/8 |
| Date follow-ups | 11/16 | 0 | 5 | 4/8 |
| Investigations, why, coaching and format | 15/16 | 1 | 0 | 7/8 |
| Food and tracker transitions | 10/10 | 0 | 0 | 5/5 |
| Workout draft and correction | 3/4 | 0 | 1 | 1/2 |
| Guidance | 16/16 | 0 | 0 | 8/8 |
| Memory | 6/6 | 0 | 0 | 3/3 |
| New-metric/history/new-date controls | 6/6 | 0 | 0 | 3/3 |
| Total, descriptive only | 83/90 | 1 | 6 | 39/45 |

Both entire conversations were fully correct in **12/18** paired families. Unnecessary
clarifications: **0/90**; the wrong dates were answered rather than clarified. PHIA passed
**24/24**, with no loss against the stored baseline. All PHIA answers were directly reviewed;
metric, operation, period convention and comparator were checked with their citations. Independent
source-row checks found **0 discrepancies in 627 PHIA numerical fields** and **0 in 4,080 synthetic
numerical fields**. These are checks of supported fields, not an assertion that every possible
statistical property was reimplemented. Correct arithmetic on the wrong window is still a fail.

All 90 delivered messages reopened unchanged. All **288 citation occurrences** reopened with
the captured metrics, windows and statistics, including versioned records. All four workout
card references reopened with matching payload fields; the original cards were cancelled after
the corrections. There was no observed false saved/deleted success or unconfirmed memory deletion.
The memory sample tests propose → Keep → recall → forget proposal, not the entire cancellation
and deletion lifecycle. No comprehensive privacy, medical, concurrency, mixed-action or all-34-
metric release claim is made.

The four “up to three, if supported” format turns earned full credit for retaining scope and
stating a scoped lack of supported personal habits. That allowance was in the frozen key. It
**does not prove** that exactly three options or a mixture of personal and general tips survives
rendering. The investigation partial is `compare_changed-02/t2`: the correct comparison and
causal limit also add a possible explanation for feeling “run down,” an unreported/unmeasured
outcome with no supporting evidence. It was not classified as a medical violation.

## What the repairs demonstrably fix

- **Food/source/date:** the original captured `energy-02/t2` output now delivers the one-day
  tracker result. Explicit history, a new date, cold totals and a genuinely new metric remain
  distinct. All ten fresh food-chain turns pass: intake → tracker on the same day → breakfast →
  all meals → another breakfast date. Draft food and the preceding day's breakfast stay excluded.
- **Investigation openings:** both historical captured duplicate forms resolve: identical dated
  data/investigation clauses, and dated data beside an undated investigation. Named side reads
  survive. All four fresh all-measure openings use the requested two blocks and distinguish the
  planted change from flat data.
- **Whole comparison reuse:** all four fresh why turns retain both blocks; the flat cases say
  there is no clear change to explain. Coaching and format turns cite habits tested only on the
  later block and explicitly disclose that limitation. They no longer cite the unrelated 60 days.
- **Guidance recall/fallback:** the plain `Pushups` entry reaches the actual 25-title selector
  input, including a constructed case where it started 26th in candidate order. `push-up` and
  `Pushups` now match in fallback. Failed matching with no exact title offers no exercise passage.
  The fresh plain, feet-elevated, wide-floor and unweighted-bridge answers all use eligible
  variants and keep semantic continuity.
- **Preserved:** evidence versions reopen correctly. The deterministic workout patch still
  preserves active/elapsed time and pauses. Meal execution, single-window ambiguity guard,
  small reader model and formatting-versus-memory distinction remain intact in these checks.

## Release blockers: earliest wrong value, replay and control

### 1. Derived-date interpretation still fails in two different ways

`hrv_ms-01/t2`: “Make a three-day average whose last day is that original first day.” The opening
was September 25–October 1. Expected September 23–25; delivered and cited **September 21–23**.
The accepted `ResolvedPart.windows` is already wrong. `hrv_ms-02/t2`, its paired wording, delivers
September 22–28 instead of the same intended September 23–25. Both retain the right metric and
mean. These are not evidence arithmetic errors.

Responsible boundary: `requests.interpret` / `resolve`, before `requested.execute`. The trace
retains `beside/previous` but not the original landmark, offset, boundary and length. It cannot
identify which raw field was wrong. Do not describe an inferred tuple as a captured one.
`replay_live_failures.py` feeds the stored resolved request to the deterministic executor and
reproduces the wrong delivery; changing only its window to the frozen intended dates returns
the requested three-day statistic. The two HRV wordings both fail, while the same-date-width
executor control succeeds. Current code can represent the correct interval.

Next: retain the raw non-personal date fields and initial/retry outputs for synthetic cases;
repair extraction of the landmark, boundary and requested width using matched counterexamples.
No new larger-model or endpoint/calendar-schema recommendation follows from this audit. The
previous matched experiments still showed no net gain from those alternatives. Do not weaken
period arithmetic or the single-window guard to accommodate a wrong reading.

### 2. A date-width edit is now misclassified as `redo`

`time_in_bed-02/t2`: “Shorten it to a three-date average, still finishing on that same last date.”
The previous interval was September 27–October 3. Expected October 1–3. The initial accepted
reader kind is **redo**, and `_redo` returns the unchanged seven-day September 27–October 3 mean.
The paired wording (“Keep the ending date but use only the final three days for the average”)
passes. This is an actual fresh failure involving the new clause type.

Responsible functions: `clauses.reading_from` accepts `RedoClause`; `requests._redo` treats it as
permission to reuse the stored request unchanged. Offline replay with the accepted redo clause
reproduces the seven days. A near-identical **format-only** control, “Say that same result in
fewer words, keeping its dates,” correctly retains those seven days.

Smallest repair: distinguish shortening an **answer** from shortening its **data interval** in
RedoClause/PROMPT and test both. A redo must not swallow an explicit semantic change to the
query. This is a reader distinction to evaluate, not evidence that the current executor needs
another interval encoding.

### 3. Elliptical follow-ups classified as `other` still reach unrelated defaults

`checkin_rating-02/t2`: “Treat the last date as zero, and use days +1 through +4 for the mean.”
Expected the check-in mean October 7–10. Initial accepted kind is **other**, with no parts.
The delivered reply instead reports recent **steps**, November 15–19, and discusses unavailable
future days. `sleep_minutes-02/t2` takes the same `other` path and reports November 15–18 sleep,
with the further false description that these are +1 through +4 from November 18.
Their first-wording counterparts retain the metric and October interval correctly.

Earliest wrong value: the accepted speech-act kind. Responsible path: `reading_from` →
`resolve`'s early `other` return → `ask`'s independently routed fallback. Saved request state
still holds the earlier explicit metric/dates, but the fallback does not execute them. The
captured turns and traces reproduce this; there was no extra paid reread. A parser control must
contrast an elliptical date edit with actual small talk and an explicitly new broad question.

Next: repair operation/speech-act recognition and prevent an unresolved data continuation from
silently becoming an unrelated recent-data answer. Preserve intentional new-topic defaults.
A precise generic implementation cannot be selected from the reduced trace alone; instrument
the missing reader fields rather than adding another untested model layer.

### 4. Workout correction direction is wrong, while patch preservation works

`paused_move-01/t2`: “That was two days too early. Fix just its date.” The existing November 4
card should move to November 6. The accepted request has **card_day_offset=-2**, and the stored
replacement is November 2. The paired “Move the draft forward two calendar days; keep the times
and pause” produces November 6 correctly. Both preserve 16:12–16:59, 39 active minutes and eight
paused minutes, with one pending replacement and the original cancelled.

`api.chat.card_edit` correctly applies the supplied offset; `corrected_payload` correctly
preserves duration. Offline replay with -2 reproduces November 2; changing only the offset to
+2 produces November 6 with the same active and elapsed duration. The earliest demonstrably
wrong value is the reader's signed displacement, not the card's anchor or duration.

Next: clarify and measure the distinction between when the event happened and how its recorded
date must move (“too early” versus “move earlier”; “too late” versus “move later”). Keep the
working deterministic card patch. This new miss does not justify reverting it.

## Additional deterministic defects, separate from fresh scores

The candidate's tests do not establish every claimed control. These are scripted development
reproductions in `b3_audit_code/offline_review.py`, not extra live cases:

1. **Duplicate coalescing ignores different referents.** `_every_metric_looked_into` compares
   period objects but not `earlier_result`. A whole-registry side comparison referring to result
   0 and an investigation referring to result 1 both use `same_as_earlier`. Their raw period
   lists compare equal, so the side read is dropped, even though the two saved comparisons have
   different dates. The same-reference control should coalesce and does. Restore reference
   identity as part of equivalence, preferably compare normalized scope and operation before
   deleting a requested clause. The original prototype checked reference equality.
2. **A retained different-window whole-registry side comparison still fails to execute cold.**
   Change only one endpoint of the side comparison. It survives clause coalescing, but has no
   named metrics; `resolve` sets `unnamed=True`, `_prior` requires history, and a cold request
   clarifies. The exact duplicate now passes. “Kept” syntactically is not “answered.” Resolve an
   explicit whole-registry side read as such, without falsely requiring an inherited metric.
   Keep named side reads and genuinely different scopes.
3. **Redo is bound to a surviving data slot, not necessarily the last answer.** After a data
   comparison followed by public plank guidance, a correctly parsed redo of the last answer
   re-enters the old comparison as coaching. `interpret` preserves the old data slot across
   guidance; `_redo` consults only that slot. A data-only predecessor is the passing control.
   Keep addressable old data for explicit references, but bind an unqualified redo to the last
   answered request's kind and referent. Do not discard all previous state to solve this.
4. **Multi-option/general rendering is still not demonstrated.** `RedoClause.options` only
   determines coaching truthiness in `_redo`; the count is not a durable response constraint.
   `_fill_points` can add guidance, then `one_coaching_conclusion` rebuilds the answer from
   observations and personal suggestions and drops general guidance. An offline renderer
   control reproduces that deletion. Fix the final assembly once, retaining count and
   personal/general constraints; test supported one-personal-plus-two-general and an honest
   fewer-than-requested case. The fresh negative-conclusion turns above are not proof of this.

Guidance continuity also needs precise wording: `established` passages are used by `for_topic`
only when the selector fails. A successful different selection overrides them. In the fresh
wide-floor pair, two eligible passage titles are used across turns, without changing the actual
variant, so both turns pass. Do not claim that exact passage identity is pinned. A scripted wrong
successful selection can still override an established canonical passage; that is a selector
precision limit, not a new live failure on this candidate. Keep explicit variant-change controls.

## Reproduction, verification and cost

All raw synthetic questions, replies, independent keys, traces, local SQLite state and private
row checks stay under ignored `data/eval/b3_*`. Turn-by-turn direct grades and reasons are in
`data/eval/b3_review/reviewed_turns.md`; reopening checks in `reopen.json`, card checks in
`cards.json`. PHIA's public-health-derived values remain private under `data/eval/b3_phia`.
Do not rerun the paid commands to reproduce an offline diagnosis.

```bash
# Historical captured outputs against this candidate, no model calls
.venv/bin/python data/eval/922_diagnosis/replay.py
.venv/bin/python data/eval/922_diagnosis/continuation_b3.py
# Remaining controls and replays of fresh failures, no model calls
.venv/bin/python data/eval/b3_audit_code/offline_review.py
.venv/bin/python data/eval/b3_audit_code/replay_live_failures.py
# Independent arithmetic/scope and stored API readback
.venv/bin/python data/eval/r922_code/review_independent_validation.py --bundle data/eval/b3_inputs --out data/eval/b3_results
.venv/bin/python data/eval/b3_review/reopen.py
.venv/bin/python data/eval/b3_review/grade.py
# Required backend checks, rerun on the candidate
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/pytest -q
```

Ruff and formatting passed; **2,498 tests passed in 314.89 seconds**. The earlier focused run
passed 240 tests. Mobile was unchanged in the candidate diff; its required remote check passed.
No mobile UI or production deployment was exercised.

Automatic approval initially rejected the live command because it interpreted the description
of Claude's offline repair round as a no-paid-calls restriction. That command did not execute
and cost $0. The user then explicitly approved up to **$0.65 total** for the frozen conversation
run and PHIA gate. Conversation cap was $0.55, PHIA cap $0.10.

| Run | OpenAI | Jev | Total |
|---|---:|---:|---:|
| 90 fresh synthetic API turns | $0.299549590 | $0.009250332 | $0.308799922 |
| 24-item PHIA B1 gate | $0.041856450 | $0.002011968 | $0.043868418 |
| This audit | $0.341406040 | $0.011262300 | **$0.352668340** |

No new uncertain reservations remain. Including the previous audit/diagnostics and their
unresolved reservations, conservative usage of the shared $2 allowance is **$1.473573942**,
leaving **$0.526426058**. Offline work, preflight, tests and reopening cost $0.

## Next decision

Keep the proven food, scoped coaching, retrieval and deterministic card/evidence repairs. Fix
silent semantic edits first: redo versus interval edit, `other` fallbacks, wrong derived dates
and correction direction; also repair duplicate identity before it can erase another request.
Do not infer model improvements from differing audit decks or green scripted tests. Freeze the
next candidate, replay these now-exposed cases offline, then use genuinely unseen paired cases
under the unchanged acceptance criteria. No merge until the zero-silent-swap gate and the area
targets pass. This candidate's date follow-ups (68.8%) and workout turns (75%) miss their targets.

## Subsequent offline planning review

The [general repair plan](pr-195-general-repair-plan.md) reconciles all earlier audits against this
same SHA. New synthetic controls expose two additional statistical defects: repeated identical
computations can change the adjustment family and significance verdict, and unknown habit
exposures can be assigned to the negative group and produce an unsupported habit result. A
state probe also confirms that a main investigation's side read is omitted from the next turn's
addressable results. These are separate $0 development findings, not new live scores or changes
to the frozen 90-turn grades. They strengthen HOLD. Reproductions and contrasting controls are
under ignored `data/eval/pr195_plan_review/`; the plan restores broader release-audit coverage.
