# Independent live audit of 9228fe6

> **Historical record** (added to the repository on 2026-11-21), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

**Hold PR #195.** The independent run on `9228fe678e804ecfd0fe85b004f86cd408214b3a` confirmed the workout repair and passed PHIA B1. The zero-tolerance period gate failed. No candidate code changed during the audit.

## Sample and results

The suite froze 38 synthetic conversations (88 turns) before calling the agent. Each scenario used two wordings. The 12 direct metric questions in each wording used a fresh seeded series. Six different interval edits were each used on two metrics. Food fixtures included two days of confirmed breakfasts, a lunch and an unconfirmed snack. The workout fixture distinguished elapsed time from active time. All Google writes were disabled. A separate, previously frozen 24-item B1 regression sample used the historical public rows. The two suites answer different questions and are scored separately.

| Area | Full | Partial | Fail | Both wordings fully correct |
|---|---:|---:|---:|---:|
| metric openings | 24/24 | 0 | 0 | 12/12 |
| adjacent follow-ups | 16/24 | 0 | 8 | 5/12 |
| workout | 8/8 | 0 | 0 | 4/4 |
| guidance | 0/4 | 2 | 2 | 0/2 |
| memory | 6/6 | 0 | 0 | 3/3 |
| investigations | 3/16 | 0 | 13 | 1/8 |
| food | 3/6 | 0 | 3 | 1/3 |
| All conversations | 60/88 | 2 | 26 | 26/44 |

The PHIA gate scored **24/24**, matching the stored baseline. The 24 delivered answers included the expected value, operation and unit, and a cited record matched the requested metric, period convention and applicable comparator. The independent row checks found zero discrepancies in 627 numerical fields. The synthetic suite found zero discrepancies in 3,648 checked numerical evidence fields. A wrong window can still produce numerically correct evidence for that window. Every synthetic reply reopened with the same text and evidence IDs. All 254 cited payload occurrences matched their captured contents.

Ten of 88 turns unnecessarily asked the user for clarification (11.4%, above the 10% target). Two of those followed an earlier failure to establish the requested comparison. A suggestion of a reminder after an answer was excluded from this count. The memory test covered proposing, tapping Keep, recalling and requesting a forget card. Deletion/cancellation, mixed log-plus-read messages, medical boundaries, cross-account access and all 34 registry metrics were not comprehensively retested on this SHA. No release-wide pass is implied.

## Findings for the implementer

1. **Paused workout dates now work in this sample.** All four drafts and all four corrections passed, including “I put it two days too early” and “three days too late.” In all four chats the original card became cancelled and precisely one replacement remained pending. Its time was 14:07–14:53, with 37 minutes active and 9 paused. Reopening the chat and fetching each linked action through the API reproduced the captured workout fields. The earlier a196 run had failed both date-only corrections. Keep this implementation.

2. **The remaining interval failures have different causes.** Of eight missed follow-ups, five calculated a metric mean over incorrectly placed dates, two returned a default all-measure overview and one asked about logging. In the clearest example Aug 27 was day zero. Days −4 through −1 meant Aug 23–26. The delivered reply and its citation both used Aug 20–23. A second wording for this same case unexpectedly asked what to log. The relative resolver recorded a successful first reading in the wrong-date case. Its retained trace records the period kind but omits landmark, offset, boundary and length, so the exact raw tuple is unknown. Capture those four non-personal enum/count fields in a private synthetic replay. In clauses.py, try an explicit pair of endpoint offsets for requests that specify both offsets relative to one landmark. Compare against the current schema with paired trailing-window and whole-range-shift controls. Separately test the routing/reader outcome on an elliptical follow-up with an active metric. A new interval encoding alone cannot repair the switch to logging or overview.

3. **A comparison should survive a change in the question being asked about it.** Three of four openings produced the right comparison of Sep 1–14 and Oct 2–15. None of the twelve follow-on why/coaching/format turns passed. On a successful opening, both wordings of “why” sometimes generated two adjacent-period edits. The single-window guard then asked which period to count from. On a failed opening a follow-up silently used default recent/baseline dates. All four format follow-ups cited habit evidence from Sep 2–Oct 31. In requests.py, an unchanged two-window comparison needs a direct reference to the entire comparison, separate from editing either side. Carry it through why, coaching, and format-only requests. Require cited coaching tests to cover the scope of the request, and describe insufficient scoped evidence when necessary. If a prior comparison failed, recover its explicit dates or ask for the unresolved detail. Re-running on default dates loses the user's question.

4. **One food-to-tracker failure is traceable to deterministic code.** In energy-02/t2 the user explicitly said to keep the date. The trace shows a tracker metric, inherited operation, reference 0 and no new period. The referenced food answer contains Oct 17. In requests.py the source-switch block calls part_windows before inheriting the prior dates, chooses sum, and the later history calculation treats an empty period list as all history. A one-day read became a 150-day total. Resolve the scope once before selecting source-specific operations. Test inherited date, explicitly changed date, explicit whole history, and a cold tracker query together. Returning to breakfast also failed in both wordings, once by including lunch and once by asking which day and meal were meant.

5. **Exercise identity can still change after the reader gets the topic right.** For a plain floor push-up, the reader produced “plain floor push-up”, but the selected and cited passage was “Push-Ups With Feet Elevated”. The delivered instruction required a bench. The corpus does contain “Pushups”. Another opening prescribed close or wide hand positions. Both follow-ups gave relevant torso cues but cited a hand-position variant, so they earned partial credit. In world.py inspect the candidate expansion, the 25-title limit and the permissive fallback in for_topic. The trace establishes the wrong passage was selected but does not isolate which internal choice caused it. Log candidate titles and the variant decision in a synthetic replay. Prefer an identified canonical exercise entry for plain form and retain its identity across follow-ups. Test plain, explicitly elevated, explicitly wide and unavailable variants side by side.

## Decision and scope

The earlier a196 deck scored 15/24 on interval follow-ups and this one scored 16/24. The questions differed. A one-turn difference is insufficient evidence of improved reliability. The development 36/36 measured overlapping reader inputs and did not exercise every end-to-end route. The 3/16 investigation result includes downstream failures in the same conversations. Both synthetic profiles had no significant changes on the particular two blocks used, so these investigation cases do not measure performance on a true positive overview. The guidance result is specific to one exercise family.

The paid conversation run cost **$0.232728534**. PHIA cost **$0.036339018**. Total **$0.269067552** against the $2 audit cap. No paid retries of the evaluation or model-based grading. The ignored local bundle is under `data/eval/r922_inputs`, freeze ID `85756b3bd1f9790e923bdb4a591fb14a24bbc2ee7b2a55c8733d5ed35257fd85`. The turn reviews, source checks, reopened evidence comparison and action checks are in `data/eval/r922_review`; PHIA artifacts are in `data/eval/r922_phia`. Only aggregates from public wearable histories appear in this handoff.

## Continuation: offline root-cause checks, November 21, 2026

**Decision remains HOLD.** Local HEAD and the remote PR #195 head were both
`9228fe678e804ecfd0fe85b004f86cd408214b3a` when checked. There is no new candidate to grade.
No production code changed, no paid call was made, and no push, merge, deploy or Google write
was performed. The existing working-tree changes and untracked handoffs were preserved.
The fresh release results above remain the release results; all checks below are exposed
**development replays**, not additional release passes.

### Reproduce this continuation

From the repository root, with the existing environment and ignored synthetic audit bundle:

```bash
.venv/bin/python data/eval/922_diagnosis/replay.py
PROBE_BACKEND=data/eval/922_diagnosis/prototype/backend .venv/bin/python data/eval/922_diagnosis/replay.py
.venv/bin/python data/eval/922_diagnosis/continuation_offline.py
PROBE_BACKEND=data/eval/922_diagnosis/prototype/backend .venv/bin/python data/eval/922_diagnosis/continuation_offline.py
cd backend
../.venv/bin/pytest -q tests/test_clauses.py tests/test_requests.py tests/test_guidance_followup.py tests/test_investigate_and_memory.py tests/test_edits.py
```

The new offline script saves `continuation_frozen.json` and `continuation_prototype.json` under
`data/eval/922_diagnosis/`. It exercises 23 named control groups, with 11 baseline assertions and
14 prototype assertions, all passing. Some groups deliberately reproduce failures; this is not
an accuracy denominator. The selected production tests passed **224/224**. The existing isolated
full-suite log `/tmp/r922-full-proto2.log` still reports **2,482 passed**; that historical full
run was inspected, not repeated. Neither suite measures reader quality on fresh language.

### 1. Food-to-tracker date loss: deterministic repair justified

Actual failed turn: `energy-02/t2`, switching from logged intake to burned energy while retaining
the date. Earliest demonstrated wrong value: `resolve` calls `part_windows` on an empty period
list before inheriting the referenced scope, chooses `sum`, then sets `history=True`. The prior
food result has October 17. `requested.execute` faithfully fills the empty scope with the
wearable history, producing a 150-day total. This is a resolver defect, not statistical arithmetic.

The captured diagnostic reader output reproduces that behavior unchanged on frozen code.
The identical output on the prototype produces operation `value`, October 17 only, and a
one-day delivered answer. The smallest demonstrated repair is the prototype's insertion of
`Period(kind="inherit")` when an explicit prior reference has no new periods, before deriving
the source-specific operation. Prefer resolving the scope once and passing that same scope to
operation selection, execution and persistence.

Close controls rerun here:

- Explicit whole-history span remains `sum`, empty windows, `history=True`.
- Explicit October 18 replaces October 17 and remains a one-day `value`.
- Cold unscoped tracker total remains a history sum; it does not invent a prior date.

These executor controls support the code change. They do not prove that the reader reliably
recognizes explicit whole-history language; that belongs in the next fresh conversation gate.

### 2. Breakfast: omitted filter and polluted predecessor are distinct

Actual failed turn `energy-01/t3`: “Now the calories I ate that morning only?” Its original
stored request has `meal_type=None`; the original reader outline already has `meal=False`.
That is the earliest visible loss. `requested.execute` passes the filter to
`analysis.logs.food_entries`, which correctly includes every meal when no filter is supplied.
Replaying the stored request against isolated made-up breakfast/lunch/next-day rows reproduces
lunch inclusion. Changing **only** `meal_type` to `BREAKFAST` excludes lunch and the next day.
The filtering implementation does not need replacement.

The original raw clause was not retained, so the precise model reasoning behind the omitted
morning restriction is unknown. The later diagnostic reread explicitly supplies `BREAKFAST` and
a date; it is a different model output and cannot establish what the original reader said.
Next repair: make current-turn meal restriction recognition reliable, retaining the distinction
between “that morning/breakfast only” and “all my food for that date.” Do not globally inherit a
meal filter: an all-meal request after breakfast must still include lunch. Morning as a clock
range versus a meal category can need an explicit product rule; this audit's frozen fixture
expects breakfast, and does not establish a general clock-time-to-meal equivalence.

Actual failed turn `energy-02/t3`: “On the intake side again, isolate breakfast for that date.”
The original reading is `other`, with no data parts; it therefore cannot execute a food read.
The diagnostic reread correctly supplies `BREAKFAST` but uses a one-day edit relative to result 0.
Its predecessor is the incorrect whole-history tracker result with **no windows**. That captured
reading raises `Ambiguous` on frozen code and the prototype alike. Replacing only the predecessor
with the corrected October 17 tracker result makes the same breakfast reading resolve correctly.
This proves a scope-contamination contribution, not that fixing the predecessor guarantees a
future live reading will stop choosing `other`. Retest the complete three-turn chain and an
all-meals control through the normal API.

### 3. Investigation openings: narrow coalescing works, another opening remains broken

Captured diagnostic `screenshift-01/t1` contains an all-measure `DataClause(compare)` and an
`InvestigateClause` with identical explicit windows and reference. `reading_from` leaves the data
clause in `also`. `resolve` resolves that side read before the investigation. Because the data
clause has no named metrics, `unnamed` makes `inherited=True`; `_prior` then requires an earlier
result even on this cold question with explicit dates. Replaying the exact raw output reproduces
the spurious earlier-result request. This particular duplicate came from a later diagnostic
reading; the original live opening passed and must not be relabelled a failure.

The prototype's `_every_metric_looked_into` coalesces only the identical whole-registry comparison.
That exact captured output now resolves as one investigation. A side mean of steps over the focal
window survives unchanged. Changing one comparison endpoint prevents coalescing, as it should.
The differing-window control still errors: preserving a distinct request is not proof it executes.

Crucial remaining counterexample: diagnostic `screenflat-01/t1` has explicit dates on the data
clause and an investigation with **no periods**. Both frozen code and the prototype still raise
the cold prior error. Original live `screenflat-01/t1` also failed, but its reduced trace cannot
prove it had this exact clause pair. Claude should preserve an explicit whole-registry side
comparison without falsely inheriting metrics, and define how an unscoped accompanying
investigation binds to it. Do not drop every data clause whenever an investigation exists.
Test identical duplication, shared-scope explanatory clause, genuinely different windows and a
named side statistic separately. The prototype is a justified narrow fix, not the whole repair.

### 4. Whole-comparison follow-ups, format requests and coaching need separate repairs

Actual failed `screenshift-01/t2` and `screenflat-02/t2` refer to both blocks, but the retained
outline contains two `beside/previous` spans. `requests.period_window` correctly rejects each
single-window edit against a two-window prior. Do not weaken that guard: “move the first edge”
after two candidate windows genuinely needs a selected side. Later diagnostic `screenshift-01/t3`
captures two `from_earlier` spans and reproduces this same failure in `resolve`.

Control: the existing `_investigation` already inherits **both** windows when given an explicit
reference with no date edits, or `Period(kind="inherit")`. Both controls succeed on frozen code.
Thus a new comparison storage subsystem is not justified by this trace alone: the current state
can represent the correct request. The next smallest repair is to distinguish reuse of the
whole result from editing a selected window in reader output, and retain that object while the
response goal changes. A true new broad question remains a necessary default-scope control.
The raw parameters of the original why-turn edits were not saved; their exact landmark and
offset cannot be inferred from the reduced outline.

Actual failed format follow-up `screenflat-02/t4`: “Could you give me up to three options here,
saying which are personal versus general?” The original request and diagnostic readings become
`other`, with no parts/focus. `clauses.OtherClause` explicitly includes answer instructions, and
`reading_from` returns `other` for them. `resolve` returns early for this kind; `_investigation`
never gets a chance to inherit the comparison. `ask` then follows the routing strategy, not the
typed investigation path. Fix the distinction between a response edit on the current answer
and unrelated small talk, preserving requested count and personal/general constraints. Keep
`about_them=False`: these turns created no memory candidates on this SHA. Do not undo the
working separation between a one-turn format command and an autobiographical preference.

Independently, `ask` constructs `named` only when `investigating` is true, and passes only
`named[0]` to `strategy.coaching_evidence`. The latter defaults to the latest 60 days when its
single `window` argument is absent. Offline tool calls confirm the default is September 2–October
31 here, while explicit focal scope produces October 2–15 records. These match the out-of-scope
habit citations in the actual format answers. Even a correctly inherited two-window request
cannot by itself make this single-window tool test both blocks.

Repair the tool boundary explicitly: keep both comparison windows in the response context. If
coaching is based only on the focal period, say exactly that and report scoped limitations;
if the answer claims a comparison explanation, compute evidence for that comparison. Do not use
the enclosing September–October range, which adds days the user did not request. A deliberately
new unscoped coaching question should still exercise the 60-day default. Opening coalescing alone
repairs neither this issue nor the format classification. Preserve the existing measured-exposure
versus intervention restrictions while changing scope.

### 5. Date interpretation: model upgrade and schema replacement are not supported

Recomputed from the saved diagnostic artifacts:

| Reader/probe | Historical exact passes | Both wordings fully pass |
|---|---:|---:|
| Production small reader reread | 18/24 | 7/12 |
| gpt-5.4 reread | 18/24 | 6/12 |
| Independent endpoint-offset probe | 12/24 | not used as a release measure |
| Calendar-table probe | 9/24 | not used as a release measure |

Calendar controls passed 9/12 separately. The stronger reader fixes three small-reader misses
and breaks three small-reader passes; both pass the same 15 cases and both miss three. There is
no demonstrated net gain from paying for the larger model on this slice.

The small reader's six misses separate into two wrong date mappings, three `other`/clarify
outcomes and one investigation instead of a mean. In `deep_sleep_minutes-01/t2`, raw
`its_first_day, offset=-4, ends_there, length=4` makes days -7 through -4, not -4 through -1.
The correct boundary is `starts_there` for that tuple. In `time_in_bed-01/t2`, it returns offset
-4 ending at the last landmark instead of days +1 through +5. Calendar arithmetic executes
these accepted tuples correctly; a width-only check cannot catch them.

The stronger reader's misses include four requests retaining data kind but wrong dates, a
memory-primary request despite a correctly scoped side read, and an `other` request. That
memory-primary case is an extra semantic failure even though a statistic may survive beside it.
Inspect operation/speech act separately from date arithmetic. These are later reader-only
outputs, not reconstructions of every original live failure. The original `calories-01/t2`
wrong tuple remains unknown; its diagnostic reread actually gets the dates right.

Next work should target the earliest wrong field and operation classification with close
controls, using the current executor as an oracle-input control. Neither proposed alternative
encoding earned replacement on these experiments. Exclude the reasoning-effort run entirely
from model-quality comparisons: it produced no usable reading, and the separate transport probe
reproduced HTTP 400. Keep its uncertain charge reservation until reconciled.

### 6. Guidance: improved candidate recall, unresolved variant precision and fallback

Actual failed `floorpress-02/t1`: a plain floor push-up received feet-elevated instructions.
The topic was already correct. In `world.title_neighbours`, equal shared-word scores retain corpus
order before the 20-neighbour cutoff. Reconstructed candidate lists for all four audited turns
omit the ordinary `Pushups` passage. Changing only the prototype tie-break brings `Pushups` into
the top neighbours (position 1 for the plain-floor control). This justifies the recall repair.
The prior live selector probe reported choosing it on all four plain-form readings, but admitted
`Incline Push-Up Wide` on the wide-push-up control. That is a precision miss, not a solved gate.

Full path checked in code:

- `world.answer` adds active passages before primary search results; a secondary topic search
  runs only if the topic phrase is not already in the query. That secondary search is not
  separately traced, so the old primary trace cannot reconstruct every candidate exactly.
- Title expansion runs only when the candidates already contain an exercise passage. Therefore
  title ranking cannot rescue an empty/nonexercise primary result by itself.
- `for_topic` exposes only the first 25 distinct exercise titles to the selector. A constructed
  26th-title canonical control remains invisible even with the ranking fix. The historical
  reconstructed lists had 22–23 titles, so this cap is a prospective failure, not the proven
  cause of the audited miss. Ensure relevant recall survives this cap before changing its size.
- Selector failure (`None`) enters lexical fallback. No exact token-subset match returns all
  candidates. Tokenization also differs: title expansion normalizes `push-up` to `pushup`, while
  fallback splits it into `push` and `up`; `Pushups` becomes `pushup`. Even adding `Pushups` to
  `plain floor push-up` does not make that fallback choose it. The offline controls reproduce
  this permissive fallback. A valid empty selector result instead removes exercise candidates;
  it is not the same as selector failure.
- `world.answer` narrows successful citations to writer-selected passages and `ask` retains those
  IDs only after a successful lookup. A wrong accepted variant can therefore carry into the next
  turn. An absent or empty Sources list retains the candidate records; invalid/out-of-range numbers also
  fall back to retaining them. Failed lookup does not establish a new successful passage set.

Keep the ranking change as a tested starting point. Next enforce same-variant behavior on
plain, elevated, wide and unavailable/failed-selector controls, using the actual final candidate
list and selector return in synthetic traces. An unavailable or failed selection should not
silently authorize a different variant. Verify the cited and persisted passage IDs on the next
turn. Do not treat this small exercise-family probe as a general retrieval score.

### What Claude should do next, and what stays

1. Carry referenced dates before deriving tracker aggregation. This has an identical-output
   reproduction, corrected delivery, and whole-history/new-date/cold controls.
2. Land narrowly justified duplicate coalescing, then fix the remaining scoped-data/unscoped-
   investigation opening without deleting genuine side reads.
3. Repair whole-result reuse and response-edit classification, then pass explicit scope into
   coaching. Do not broaden or remove the single-window ambiguity guard.
4. Fix omitted meal restrictions and verify the entire intake → tracker → breakfast chain.
   Leave `food_entries` filtering and deliberate noninheritance of meal filters intact.
5. Improve guidance recall, then close variant and failure-fallback controls before claiming a
   pass. Keep cited passage identity inspectable across turns.
6. Keep the current date executor and model pending evidence of a better interpreter. Preserve
   the paused-workout date correction, evidence versioning, confirmed memory lifecycle, and
   distinction between answer formatting and permission to remember.

Before merge, freeze a new candidate SHA, replay these development cases offline, then freeze
unseen paired conversations before live execution. Apply `acceptance-structured-requests.md`
unchanged: zero silent date/source swaps and unauthorized state changes, PHIA no more than one
worse, all area thresholds, and unnecessary clarification at most 10%. Grade delivered text,
exact windows, source rows, reopened evidence, stored cards/memory and paired wording together.
Include both true-change and flat comparisons; this audit's particular comparison blocks were
flat. The existing release scores are still direct 24/24, follow-ups 16/24, investigations 3/16,
food 3/6, guidance 0/4 fully correct, workouts 8/8, memory 6/6, and PHIA 24/24. Neither the selected
224 tests nor the prototype full suite clears the failed release gates.

Cost reconciliation: inspected all six diagnostic meter files. Returned usage totals
**$0.248385800**, unresolved reservations **$0.603452250**, prior fresh audit **$0.269067552**.
The conservative shared-$2 remainder is **$0.879094398**. This continuation spent **$0**; no
reservation was released or new live result claimed.
