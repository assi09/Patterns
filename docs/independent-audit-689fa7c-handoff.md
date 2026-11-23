# Independent audit of 689fa7c — November 21, 2026

> **Historical record** (added to the repository on 2026-11-21), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

**HOLD PR #195.** Frozen candidate: `689fa7c4df53acf2ef76450bd0ecad18ba50b96e`.
The 592-turn synthetic audit, offline verification and separate 24-item PHIA gate are complete.
PHIA is 23/24, one regression within its predeclared allowance. The named-period zero-tolerance
gate fails. Do not merge on the strength of passing CI
or offline reproductions.

## What improved, and what that establishes

The matched **development** reader comparison on 22 exposed historical inputs improved from
14/22 on b3 to 19/22 on this candidate: date edits 12/16 → 13/16, point-count/scope formatting
0/4 → 4/4, signed workout corrections 2/2 → 2/2. Twelve inputs passed both, seven improved,
two formerly correct inputs were spoiled, and one failed both. These are matched extraction
checks, not held-out answer accuracy. The format subscore checks extracted constraints, not
whether retrieval and final assembly actually produce the requested options.

The three original offline planning probes now pass: unknown bedtime exposures no longer form
an artificial comparison group; an identical statistical retest does not alter the adjustment
family; and a side read remains addressable. Contrasting controls remain intact. The full backend
suite passed locally: **2,521 tests**, Ruff check and formatting check. Sixteen separate offline
failure controls passed, covering provider/guard errors, budget accounting, failed-message
persistence, trace persistence and unknown write outcomes without replay. They are not added to
live accuracy. No production code changed during this independent audit.

## Method and coverage

The release deck froze **234 fresh synthetic conversations / 592 turns**, two wordings per
family, before live release calls. All 34 supported metrics are covered, with separate direct
openings and semantic date edits. Restored coverage includes strict/inclusive/equality thresholds,
individual/joint coverage, recorded zeroes, low wear, missing/constant/disjoint/lagged associations,
whole-registry investigations, multiple parts and side reads, memory approval/replacement/
cancellation/deletion/chat-only/cross-chat, meal filters and nutrients, draft/status/correction,
exercise and nonexercise guidance, source/ownership/medical/injection boundaries, Arabic/French,
and twelve-turn topic switching. Leap-day and year-boundary controls are included.

Freeze ID: `9e8f5fdb449d38223802b3f50dd0850b65f7bdb34c165e4c7958b6626854e0d5`.
The 24-item PHIA B1 gate remains the same historical regression sample, separate from fresh
conversation results. Public-derived source values remain private. There is no paid judge.
All phases share the user's new **$5 maximum across subsequent audits**; old remaining balances
are not added. The harness blocks Google requests and disables external writes/reminders.
Synthetic action cards remain local drafts; memory taps are explicit fixture actions.

The old b3 audit had 90 turns and narrower, sometimes more permissive format expectations.
Its 83/90 result cannot be compared directly with a blended score on this expanded deck.
The matched reader comparison above is the controlled before/after evidence.

## Fresh results and acceptance decision

All 592 delivered answers were directly reviewed against the frozen requests, source statistics,
citations and applicable state. Partial credit does not count as fully correct.

| Area | Full | Partial | Fail | Both wordings full |
|---|---:|---:|---:|---:|
| coverage | 26/28 | 2 | 0 | 12/14 |
| thresholds | 29/30 | 0 | 1 | 14/15 |
| metric openings | 68/68 | 0 | 0 | 34/34 |
| metric date follow-ups | 44/68 | 0 | 24 | 16/34 |
| associations | 43/48 | 4 | 1 | 21/24 |
| calendar openings | 24/24 | 0 | 0 | 12/12 |
| calendar follow-ups | 18/24 | 0 | 6 | 6/12 |
| guidance | 37/40 | 2 | 1 | 17/20 |
| memory | 28/36 | 2 | 6 | 11/18 |
| investigations | 35/48 | 13 | 0 | 17/24 |
| workout | 34/40 | 2 | 4 | 16/20 |
| boundaries | 27/32 | 2 | 3 | 13/16 |
| food | 25/30 | 2 | 3 | 12/15 |
| multipart | 32/36 | 3 | 1 | 14/18 |
| long_context | 19/24 | 1 | 4 | 7/12 |
| multilingual | 15/16 | 0 | 1 | 7/8 |
| TOTAL | 504/592 | 33 | 55 | 229/296 |

Both complete conversations were fully correct in **63/117** paired families. Unnecessary
clarifications/rephrase requests on clear requests: **10/592** (eight reference/recall/period
questions plus two downstream food-draft rephrase failures). Nonexistent-card ambiguity and
requests to fabricate evidence are excluded from that count; they remain graded for response
quality. Cascaded failures remain in the denominator, including the two wrong-scope medians
after the first long-context wording loses the intended result.

The predeclared follow-up target fails: the dedicated metric date slice is 44/68, and calendar
follow-ups are 18/24. At least the 24 wrong-date metric follow-ups breach the named-period
zero-tolerance gate. Memory is 28/36 versus 90%; investigations are 35/48 versus 75%.
Direct metric openings pass 68/68; workout turns meet 85% exactly (34/40), but retain the paused
correction failures described below. Guidance is 37/40. The total is descriptive, not a single
release score. Broader source and mixed-answer failures also require repair.

Independent source-row verification found **0 discrepancies in 20,146 numerical fields**.
Another **306 food-total/known-value/corpus-identity fields** and **897 run-adjusted records**
agreed with separate offline checks. These checks do not turn correct arithmetic on wrong
scopes into correct answers, nor prove every possible statistical property. Unknown-exposure
and duplicate-hypothesis probes pass. Data/source revisions are not fully encoded in the current
hypothesis key; the fixed-source audit does not establish behavior across changed revisions.

All **592 messages** and **1,250 citation occurrences** reopened with their captured content and
payloads, including **21 versioned citation occurrences**. All **25 card references** reopened
with the captured relevant payload fields; cancelled older drafts remained cancelled. All
**498 cross-account evidence/card access checks** returned 404. Snapshot checks found no new
unconfirmed successful write, approved fact, removal of a kept fact, or fact change on the explicit
no-save turns. No observed false saved/deleted success or prohibited medical answer occurred in
this sample. An extra unrequested *proposed* memory fact is a quality miss, not a confirmed save.
These scoped tests do not constitute a comprehensive security or concurrency audit. The
12-turn workflows did not exercise summary folding; they test topic switching and old references.

The remote PR was rechecked after the run: same frozen SHA, open/unmerged, backend and mobile
required checks successful. No push, merge, deployment, production-code edit or Google traffic.
The pre-existing untracked handoffs were preserved.

### PHIA and spend status

The frozen 24-item PHIA B1 regression gate is **23/24**, with **one regression** against the
stored baseline. It passes the predeclared gate of at most one worse answer. All delivered
answers were directly reviewed; 23 match the cited metric/operation/period/comparator and
source-row result. Independent arithmetic found **0 discrepancies in 620 numerical fields**.
This historical regression sample remains separate from the 592 fresh synthetic turns.

The regression, `B1-021`, asks for the lowest “awake minutes” yesterday. The benchmark's target
is time awake in bed (`awake_in_bed_minutes`), but the resolved request selects time still while
awake (`still_minutes`) and honestly reports that the selected measure is unavailable. Correct
handling of a missing *wrong* metric is still a failed answer. Preserve the distinction between
these measures; resolve ambiguous terminology from the question/context/source vocabulary,
rather than adding a benchmark-specific alias or replacing a missing measure silently.

Automatic approval review initially blocked the PHIA invocation before execution; that cost $0.
The user then explicitly approved the frozen public health-derived payload transfer to the
configured OpenAI service, up to $0.25 within the existing shared cap. The gate ran once after
that approval. No failed question was rerun or replaced.

Shared new-$5 ledger: matched development **$0.074579400**; 592 fresh turns **$1.409913034**;
PHIA **$0.045561318**. Combined **$1.530053752** (OpenAI $1.472697460; Jev $0.057356292),
unresolved reservations **$0**. Remaining **$3.469946248**. Offline tests, numeric checks,
adapter probes, reopening and the rejected PHIA invocation cost $0. The former approximately
$0.526 balance is not added. The synthetic release blockers still require HOLD.

## Remaining repairs, in dependency order

### 1. Preserve query edits through interpretation and clause adaptation

**Locations:** `backend/app/agent/clauses.py::reading_from`, `_whole_registry`,
`backend/app/agent/requests.py::_redo`, `_data`, period resolution.

The new `keeps_the_data` boolean is supplied by the same reader that chooses `redo`. Captured
first attempts mark it true for explicit translations and resizes. For example,
`metric_still_hr_above_resting-01/t2` requests a two-day translation of the complete block;
the raw clause is `redo`, `keeps_the_data=true`, and `_redo` repeats the original interval.
This is a circular semantic check: valid structure plus an affirmative flag does not establish
that there was no query edit. Many metrics reproduce this failure, while paired wording works.

Other date failures are actual bad relation fields. In `metric_very_active_minutes-01/t2`,
“three dates ending on the first date” becomes `its_first_day`, offset **-2**, `ends_there`,
length 3. Offset should be zero; code correctly executes the wrong tuple. Do not change the
calendar arithmetic to compensate for an extraction error. The new traces make this diagnosis
possible without another provider call.

A separate deterministic failure occurs before resolution: `date_lastweek-02/t2` emits a data
clause with `operation=inherit`, calendar week -1, no metric and no explicit result index.
`_whole_registry` interprets this omission as every measure; the adapter converts it to
investigation/describe. The resting-HR mean becomes an all-measure screen with an extra baseline.
An offline adapter replay reproduces that conversion. Explicitly new dated overviews must
continue working; omission must not erase a valid inheritance request.

**General repair:** resolve a typed referent and an explicit query transformation independently
of response formatting. Inherit every unchanged field from that object; current explicit edits
win. Do not use a phrase list or another global text rewrite. Preserve width, edge, offset,
calendar anchor and comparison-side identity as constraints, then calculate endpoints once.
Validate compatibility before executing, and clarify only genuinely unresolved constraints.
A clear question getting a clarification remains a miss. The same issue is not English-only:
`french_sleep-02/t2` explicitly asks for the median and receives the previous mean; query edits
include operations and units, not only dates.

**Controls:** vary metrics, seeds, widths and both wordings for translations, preceding/following
blocks, endpoint-preserving resizes, zero-offset edges, complete days, calendar weeks/months,
leap/year boundaries, explicit new metrics, all-history and cold overviews. Include formatting
alone and formatting plus a query edit. Score the raw reading and delivered answer separately.
A hand-written correct tuple proves executor behavior only.

### 2. Preserve the complete referent and every query parameter across turns

**Locations:** `requests.py::_redo`, `_prior`, state persistence; secondary API dispatch.

Side reads now survive and explicit retrieval often works. The last answer still does not have
a general complete identity: `_redo` special-cases guidance, then reuses `state.data`.
`mixed_log-01/t3` requests both the pending status and steps result again, but drops status.
`long_context-01` returns to explicitly dated personal steps after guidance and receives plank
instructions or a general population step count; later edits inherit the wrong surviving result.
The paired twelve-turn wording works, so this is not proof of a context-length limit.

Parameter inheritance must extend beyond dates. `assoc_lag-02/t2` asks whether the preceding
one-day-lag result proves causation. It silently reruns the same-day test and changes the
association. `threshold_4-01/t2` changes only the boundary but loses equality in favor of
strictly above; both happen to count one date. Numeric coincidence does not make the plan right.

**General repair:** persist all delivered main/side/status/guidance objects and their availability,
source, operation and parameters. Resolve “last answer,” a named old result and a selected part
separately. An unchanged lag/comparator/threshold/meal/source field must remain inherited.
Status/recall requests must not become state-changing requests. Keep account ownership, legacy
state compatibility and the existing single-comparison-side ambiguity guard.

**Controls:** data → guidance → explicitly named old data → operation edit; mixed status/read →
repeat both → repeat one; lagged association → cause question → explicit remove/change lag;
equality and strict/inclusive comparisons with coincident and noncoincident counts. Include new
whole-registry and genuine new-topic controls so stronger inheritance does not trap new requests.

### 3. Carry validated temporal constraints into action validation

**Locations:** `backend/app/api/chat.py::card_edit`, `corrected_payload`,
`backend/app/actions/stated.py::mismatch`, action parsing.

Reported too-early/too-late direction is improved and date-only paused edits preserve the pause.
An explicit edit to **33 active minutes with the nine-minute pause retained** still fails.
The reader correctly extracts 33; `corrected_payload` rejects every duration edit when prior
elapsed time differs from active time. The internal request has no duration basis/pause field.
The correct result is 33 active + 9 paused = 42 elapsed, preserving the date/start/type.
The paired `workout_paused-02/t3` goes through `propose_workout_log` after the patch path cannot
handle it, and creates 33 active = 33 elapsed minutes, silently dropping the retained nine-minute
pause. The old card is cancelled. A constraint must survive the fallback path too; do not
reconstruct an unconstrained new entry after a failed structured patch. Keep rejection for
actually ambiguous or inconsistent durations, not every paused edit.

Food draft `food_draft-01/t1` resolves the correct food/day, then the downstream action guard
claims no other day was named. Offline replay confirms `Oct31` fails `NAMED_DAY` and triggers the
last-24-hours restriction; `Oct 31` passes with the exact same payload. This second recognizer
ignores the date the typed reader already validated. Do not solve this with just one new spelling:
pass validated date provenance/constraints into action checks and retain clock/duration checks.

An explicit new run also becomes generic WORKOUT in one wording (`workout_nocard-01/t3`).
Preserve activity identity through the action parser, and check the resulting payload, not merely
that a draft exists. Keep honest failure replies, pending-card revision checks and tap-to-write.

### 4. Resolve memory identity and state questions before the secondary selector

**Locations:** `backend/app/api/chat.py::forget_from`, `backend/app/agent/listener.py::which_kept`,
memory recall dispatch and clause selection.

Confirmed deletion, cancellation and replacement work in the tested state transitions.
Conversational access is incomplete: a clear approved-preference recall can become a question
about measurements/dates; referring to the just-updated sole fact can ask “which?” without a
forget card. `forget_from` passes only the current message and kept strings to `which_kept`,
without the already selected conversational memory object.

In `memory_cancel-02/t2`, asking whether the cancelled-forget preference is still saved creates
another forget proposal instead of answering status. No deletion occurs; this is a speech-act
failure, not an unconfirmed deletion. `mixed_memory-02/t1` also proposes the data question itself as an extra fact to keep,
alongside the legitimate requested walking preference. It is not approved by the fixture.
Pass only the selected fact clause to memory extraction, and the resolved memory referent and
requested operation through dispatch; preserve the explicit card consent gate. Distinguish a chat mention from an
approved durable fact, including after deletion. Avoid “nothing has been approved” when the
truth is “nothing is currently kept.”

**Controls:** named and referential recall/forget, one versus multiple facts, replacement followed
by recall and forget, cancelled deletion followed by status, approved deletion followed by
chat-only recall, no-save and cross-chat controls. Assert both text and stored state.

### 5. Retrieve and assemble options from the resolved topic

**Locations:** `backend/app/agent/ask.py::_fill_points`, `more_passages`, final assembly.

The reader now extracts the requested three points, and coaching uses/discloses the later
comparison period. Fresh requests for labelled personal/general sourced options still return
only a recap or a no-supported-personal-habit sentence. `_fill_points` sends the elliptical
follow-up itself to `more_passages`, without the resolved investigation topic. Correct point
count extraction is not an end-to-end fix for retrieval and assembly.

Carry the resolved topic, allowed personal/general scope and count through retrieval and final
assembly. Personal options need supported personal evidence; general tips need the actual vetted
passages and clear labels. If sources provide fewer, state the shortfall. Never invent tips to
fill a count. Test with useful passages, none, duplicates and guard rejection, then fresh
contextual wording. Preserve personal-first assembly and the separation from memory intent.

### 6. Bind all delivered factual wording to available sources and requested targets

A request to combine Takeout/API sleep is answered as a combined series in one wording and a
silent single-source trend in the other. The harness supplies only one API history: there was
**no actual source mixing**, but the first answer falsely claims it and neither explains the
required source separation. Enforce source selection and actual availability in the plan and
rendering; never claim a combined source the tools did not read.

A request for protein where the recorded value is unknown repeats energy/carbs/fat and never
answers that protein is missing. Carry the requested nutrient and its known/unknown status into
the renderer; keep unknown distinct from zero. The draft-to-confirmed-read control also fails: `food_draft-02/t2` first emits food-log source,
food operation and no invented meal filter, but resolution rejects its empty metric/reference.
The retry adds an unrequested SNACK filter and reports zero confirmed entries instead of the
existing meals for that date. Food-log scope must be representable without a tracker metric;
retries must preserve already-correct fields. All-meal and breakfast filters must retain their
working execution semantics.

The unknown exercise control also loses identity: `guide_unknown-02/t1` leaves no eligible
exercise passage, uses a web surfing result, and adds ordinary-pushup instructions absent from
its [linked CDC surfing page](https://archive.cdc.gov/www_cdc_gov/healthyschools/bam/cards/surfing.html).
The next “standard floor movement” selects **Calves-SMR with a foam roller**, rather than returning
to the ordinary pushup. Preserve the base movement separately from an unsupported modifier and
failed lookup; require an eligible title/context before selecting a different exercise. Honest
lookup failure remains preferable to a wrong movement. In constant-association cases, the
reason is correct but the computed constancy statement has no inspectable citation; insufficient
statistical results still need their explanatory evidence attached.

Correct comparisons can still acquire an unreported “run down” outcome, and a descriptive
coverage reply calls sleep steady without a change test. One pushup follow-up adds a conflicting
arms-length instruction while descending. Check the complete delivered text against computed
or retrieved evidence, including adjacent prose, rather than only accepted claim objects.
A harmless steps request after an urgent reply is also misclassified as medical in one wording;
classify the current requested act while preserving genuine emergency/medical continuations.

## Local reproduction records

Private, ignored local files (not public evaluation fixtures):

- `data/eval/689_inputs/`: frozen fresh inputs, oracle and hashes.
- `data/eval/689_results/`: delivered answers, raw synthetic reader attempts, evidence and SQLite.
- `data/eval/689_review/manual.json`, `failures.json`, `reviewed_turns.md`: direct judgments and
  first wrong decisions; no paid judge.
- `data/eval/689_review/adapter_probe.py`: three deterministic reproductions with contrasting
  controls (dated inheritance, compact food date, paused active-duration edit).
- `data/eval/689_offline/`: original hypothesis, unknown-exposure and side-state probes.
- `data/eval/689_matched/`: exposed matched reader development comparison.
- `data/eval/689_phia/`: private regression inputs/results, separate from fresh questions.
- `data/eval/689_budget.json`: shared conservative spend ledger.

No finite audit guarantees that no future question will fail. The next changes should close
these contracts across question families, pass the existing reproductions and contrasting
controls, and then earn a new independent result on unseen paired wording. Preserve the small
reader model, statistical executors, evidence versions, one-source rule, paused date-only edits,
consent gates and existing single-period guard. Do not rewrite those working paths to fit one
failed quotation.
