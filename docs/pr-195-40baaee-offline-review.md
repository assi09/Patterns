# Offline implementation review of PR #195 at 40baaee

**Not ready for the next paid audit yet.** The implementation addresses several real contracts,
but independent offline probes find five deterministic edit/state gaps, a still-open answer-assembly
case and an unchanged prose-grounding gap. Passing the submitted reproduction tests does not close these neighboring cases.

Reviewed code commit `d23ebc2` and its documentation commit `40baaee` against the previously audited
`689fa7c`. Remote PR head was verified as `40baaee9f0f08f699c12cb73192ebd8dd5a02d9c`, open and
unmerged, with both required backend/mobile CI checks successful. This is a review of the
current head, not a claim that the user has frozen it for a live run. No production code changes, paid calls, push, merge, deployment or Google traffic occurred.
The existing untracked handoffs were preserved. Shared audit spend remains $1.530053752 of $5;
$3.469946248 remains.

## What the implementation improves

- Redo now carries periods, metric/statistic edits, comparison, threshold and nullable lag rather
  than a self-reported keeps-the-data boolean. This removes the old deterministic swallowing of
  edits *when the reader supplies the correct new fields*.
- Date relations can place first/last endpoints separately; code rejects inconsistent endpoints
  and widths. A backward-compatible adapter retains old captured period readings.
- Metric omission after earlier data no longer automatically becomes a registry overview.
  Older result parts and count/lag parameters are exposed to the reader.
- Paused corrections carry active and elapsed durations into the proposal tool, including the
  fallback path. Ordinary 33-active + 9-paused edits now resolve to 42 elapsed minutes.
- The typed date binds downstream log checks, fixing the second recognizer's compact-date
  refusal. A typed exercise type binds drafting. Pending-card descriptions use stored values.
- Forget selection receives conversation context; memory extraction receives its own clause.
  The empty-memory reply now describes current state rather than denying past approval.
- Coaching retrieval uses resolved metrics/tested outcomes, general additions have labels and
  sources, and the normal assembly path reports shortfalls. Food readback carries requested
  nutrients and distinguishes unknown from zero. Constant-series explanations cite evidence.
- Source-mixing/fabrication flags select code replies; a base movement can be carried in the
  guidance topic and an empty eligible exercise selection can refuse rather than fall to web.

These are substantive changes. New reader fields, altered date extraction, memory interpretation,
base-movement extraction and new refusal flags are still model-dependent. Their scripted tests
establish downstream behavior, not extraction quality. The new date representation needs a matched
reader comparison after the deterministic gaps below are repaired, before an unseen release audit.

## Required fixes before spending on another audit

### 1. [P1] Explicit zero lag is mistaken for no edit

**Code:** `backend/app/agent/requests.py:470`, `_changes`.

After a one-day-lag correlation, a valid redo asks for the same dates and same measures but
`max_lag=0` (same-day association). With `earlier_result=null`, `_changes` tests the lag's truthiness,
returns false, and `_redo` copies the old result with lag **1**. The accepted explicit edit is lost.

Offline controls: null correctly retains 1; an explicit lag 2 correctly becomes 2. Only zero is
ignored. This is a sentinel/value bug, not a reader miss. Check presence (`is not None`) rather
than truthiness. Cover both data and redo clauses, implicit-last and indexed references, and
same-day → lagged → same-day transitions.

### 2. [P1] An explicit statistic after an investigation is overwritten

**Code:** `backend/app/agent/requests.py:497`, `_redo`.

After a steps investigation for October 1–14, a valid redo for “Keep those dates, but give only
the median steps” contains operation `median` and metric `steps`. Because the prior operation
is `describe`, `_redo` forcibly replaces the requested operation with `describe`. The result
remains an investigation instead of the requested statistic.

Inherit the prior investigation operation only when the edit says `inherit`; an explicit query
operation must win. Preserve whole-investigation formatting/coaching, and apply the normal
single/two-period ambiguity guards when an explicit statistic needs a selected comparison side.
Test investigation → precise mean/median/count, side selection, and unchanged investigation redo.
Do not repair this with another wording rule.

### 3. [P1] Explicit active/elapsed edits can be discarded as restatements

**Code:** `backend/app/api/chat.py:560`, `card_edit`.

For a synthetic card with 31 active minutes, 9 paused and 40 elapsed:

- “Set active time to 40 minutes” with `duration_is=active` and no newly stated pause should yield
  40 active / 49 elapsed. The code returns no duration edit.
- “Set elapsed time to 31 minutes” with `duration_is=elapsed` should yield 22 active / 31 elapsed.
  The code also returns no duration edit.
- A new active time of 33 correctly produces 33 active / 42 elapsed.

The restatement shortcut compares the number against **either** old duration before considering
its explicit basis. Matching the *other* duration is a real edit. With an explicit basis,
compare only against that basis; reserve the existing cross-duration restatement safeguard for
an actually unspecified basis. Keep date-only paused controls and bind the resulting pair to all
proposal/fallback paths. Include equal-to-the-other-duration and changed-pause cases.

### 4. [P1] Complete-last-answer replay is still special-cased

**Code:** `backend/app/agent/requests.py:483`, `_redo`; saved request state.

The new status-plus-data branch fixes the audit's status example. A mixed **memory recall plus
data** answer still fails the same invariant. Given `last=memory` and a same-scope sleep mean,
a valid unchanged redo for “Repeat both the saved preference and that sleep result, briefly”
resolves to data only, with no recall action. The preference is dropped. The state retains data
parts and a kind, not the complete delivered request. A pure status answer with no data also
reaches the no-previous-data ambiguity before the status branch; a guidance answer with a data
side read replays guidance with zero side reads. Both are independently reproduced.

Persist/replay the actual last request's supported components rather than adding isolated cases
for status and guidance. Preserve selected older data references separately. Replaying memory
should recall state, never repeat a mutation or auto-confirm a card. Cover mixed recall/read,
status with/without data, guidance/read, prior-data → memory-only → redo, and explicit one-part
selection. Keep consent, ownership and current-state truthfulness.

### 5. [P1] Retry field preservation can swap the sources of reordered clauses

**Code:** `backend/app/agent/requests.py::kept_fields`.

The new food-date retry holds source, operation, meal filter and nutrient fields from the first
reading. It matches old and corrected data clauses by list position, without checking identity.
If a two-part retry changes `[food, steps]` to `[steps, food]`, the supposedly preserved fields
are copied onto the wrong clauses. This is legal clause order in the schema.

The independent probe starts with a food read missing its date plus a correctly dated steps
read. The corrected reading supplies the food date and reorders the two reads. Field preservation
turns the steps clause into food and the food clause into tracker/value. The adapter then makes
the latter a whole-registry investigation. Final resolution is an investigation plus food,
with **no steps-value request**. The retry itself had the correct two sources before preservation.

Match preserved fields to a stable clause identity, not position. If identity cannot be matched
uniquely, do not transplant fields from a different clause. Preserve the already-correct source
and meal fields when order is unchanged as well. Cover reordered, inserted, removed and repeated
same-type clauses, alongside the original one-clause food retry control.

### 6. [P2] Unavailable personal periods bypass option shortfall handling

**Code:** `backend/app/agent/ask.py:1168` and the fixed-reply path, before `_fill_points`.

A resolved coaching request with three requested personal/general options and an October window,
on a synthetic source containing only November days, still returns only the out-of-range data
limit. It has no options and no explanation of the requested option/source shortfall. The normal
`_fill_points` improvement is never reached. This reproduces the old short-profile format case
without any provider calls, even with a correctly interpreted request.

Preserve the honest personal-data limitation and the requested response constraints through the
early-return path. If general guidance is permitted and has a resolvable topic, use vetted sources;
otherwise explicitly explain why the requested options cannot be supplied. Never invent a
personal option or silently switch the data window. Test unavailable/empty periods as well as
ordinary coaching with sufficient, insufficient and guard-rejected guidance.

### 7. [P2] The prior unsupported personal outcome still passes prose checks

**Code:** `backend/app/agent/agent.py` summary validation and
`backend/app/agent/verifier.py`; the verifier is unchanged in this repair.

Replaying the captured `investigate_main-01/t2` answer through the current deterministic claim
and summary checks still accepts all four structured claims and produces no summary problems,
while its adjacent prose explains feeling “more run down,” an outcome the user did not report
and the tools did not measure. The valid comparison statistics do not support that added
personal assertion.

This replay does not predict how often the new writer will emit the sentence. It establishes
that the known unsupported output is still not rejected by these checks. Do not count this
failure class as closed merely because valid claims have evidence IDs. Bind the complete
personal factual narrative to the provided question and computed evidence, retaining legitimate
uncertainty and general guidance. Use the old output plus supported/unsupported paraphrases as
development controls, then measure unseen explanations. A single banned-phrase rule would not
fix the class.

## Verification and limits

- Targeted tests from `backend/`: `tests/test_689_reliability.py`, `test_clauses.py`, `test_edits.py`,
  `test_requests.py`: **242 passed**. The first root-directory invocation had six Alembic fixture
  setup errors because it could not find `alembic.ini`; the correct backend-directory run passes.
  Those setup errors are not product defects.
- Ruff check and formatting check pass. Full backend suite: **2,584 passed in 473.06 seconds**.
  The 242 targeted tests are a subset, not extra tests added to that total.
- Independent probes and results are ignored local files:
  `data/eval/40baaee_review/probes.py` and `probes.json`. They call the actual clause adapter,
  resolver, card edit and answer functions; no production monkeypatch or paid model is used.
- These are deterministic contract reproductions with supplied reader fields. They do not claim
  a live failure rate or measure the new reader schema. No paid calls were made in this review.

After these fixes: rerun their contrasting controls and the existing suite, freeze the new SHA,
then use a capped matched-reader step to measure the new schema. Only then freeze a fresh paired
conversation audit. Keep old audit questions as development material, never held-out evidence.
No finite review or audit can promise that every future question will work; these specific gaps
can be closed before another provider call is necessary.
