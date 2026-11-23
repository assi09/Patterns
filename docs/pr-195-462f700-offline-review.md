# Offline implementation review of PR #195 at 462f700

> **Historical record** (added to the repository on 2026-11-21), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

**The first six repairs from the 40baaee review hold in independent offline controls. The seventh
fix removes the original bad summary, but does not yet enforce grounding of all personal factual
text. Replay also has a legacy-state regression and loses the prior option count.** Repair these
grounding/replay boundaries before paying
for another audit. This is not a live accuracy measurement.

Reviewed code commit `9e6e317` and documentation commit `462f700` against `40baaee`. Local reviewed
head: `462f700031ea34c58c06d04a6a993c8a7d7fe5f2`. The remote PR matches, is open/unmerged;
mobile CI passes and backend CI was still running at the final check. No production code changed, no paid calls or Google
traffic occurred, and nothing was pushed or merged. Pre-existing untracked handoffs were preserved.
Shared spend remains $1.530053752 of $5, leaving $3.469946248.

## What now holds

| Prior finding | Independent offline result |
|---|---|
| Explicit zero lag ignored | Fixed in the original correlation redo: null keeps 1; explicit 0 gives 0; explicit 2 gives 2. |
| Median after an investigation forced to describe | Fixed: the same supplied median edit resolves to data/median on the original dates. |
| Active/elapsed edit equal to the other old duration ignored | Fixed: on a 31-active/9-paused/40-elapsed card, active 40 gives 40/49, elapsed 31 gives 22/31; active 33 remains 33/42. |
| Whole-answer replay loses components | Fixed for the reproduced mixed memory/data, status-only and guidance/side-read cases. New states persist the answer's component counts and recall/topic/status metadata. The legacy adapter has the separate problem below. |
| Reordered retry swaps food/tracker fields | Fixed: exact unique clause words identify the source fields. Reordered and original-order controls both resolve to one food read and one steps value. Ambiguous matches are not transplanted. |
| Unavailable periods bypass option constraints | Fixed in the no-source control: the correct data limit remains and notes explain no personal option and the requested count shortfall. The test blocks network and supplies no passages; it does not measure retrieval quality. |
| Unsupported personal outcome beside valid claims | Original summary fixed: `said_by_claims` removes the uncited “run down” sentence from the old output. The neighboring claim-text control still fails below. |

The new tests also cover indexed selections, same-day → lagged → same-day, comparison-side
ambiguity, pause/date controls, source-preservation ambiguity, general tips, missing-topic limits
and replay without repeating memory mutations or card confirmation. Those are useful controls.
The new request-state metadata is a broader repair than another isolated kind check.

## Remaining finding 1 — [P1] Free claim text is still not grounded by joining claims

**Code:** `backend/app/agent/ask.py:527` (`said_by_claims`), and deterministic claim/text validation
in `backend/app/agent/verifier.py` / `backend/app/agent/agent.py`.

The new assembly joins `Claim.text`. Those strings remain model-authored; accepting the claim's
metric, direction, p-value, citations and numerical values does not establish every adjacent
personal assertion in that string.

An independent neighboring control takes the captured, valid synthetic steps-change claim and
adds an unreported personal outcome **inside the claim**:

> Steps went up from 7,184 to 12,780. You have been feeling more run down.

The same evidence has no report or measurement of that outcome. The current verifier accepts the
claim (one accepted, zero rejected); all the deterministic summary/text checks report no problems;
`said_by_claims` then publishes the entire assertion. A second nonmedical control adds “You have been walking to work” to the same steps-change
claim: it too is accepted, produces no deterministic text problems, and is published. Steps
measurements contain no commute information. The original unsupported summary is removed,
but moving an unsupported assertion into a claim preserves it. No model call is needed to demonstrate
this acceptance/assembly gap. This is an extension of the existing grounding invariant, not a new
benchmark requirement or a measured claim about how often the writer will do this.

The Jev guard checks medical content and sees sentences without the person's evidence; it is not
a personal-fact grounding check. The probe does not make a paid guard call or assume its verdict.

**General repair:** bind rendered personal factual statements to the facts the cited records
actually establish, including the subject/outcome. A record establishing a steps change must not
license an extra assertion about how the user feels. The existing deterministic data renderers
provide a starting point for factual clauses; keep the investigator's choice of tests and clearly
qualified explanation/limitations. Preserve the original-summary fix, but do not treat arbitrary
accepted claim strings as proof that every sentence is supported. Do not add a ban on “run down”
alone or shift this check to another unmeasured self-reported boolean.

**Controls:** the original bad summary; the same unsupported assertion inside a valid claim;
unsupported personal-outcome paraphrases; a supported change-only claim; a user-reported outcome
with clear attribution; a computed check-in result; and labelled public guidance. Distinguish
what the user reported, what a statistic shows, and what remains unknown. Validate the delivered
text, not just the existence of evidence IDs.

## Remaining finding 2 — [P2] Legacy replay promotes stale data into a side read

**Code:** `backend/app/agent/requests.py:477` (`_legacy_answer`), especially the inferred read count
at line 486.

Before the new `answer` metadata, a guidance-only turn could leave an older data result in
`state.data`. That slot was addressable history, not necessarily a side read in the last answer.
The new adapter assumes every non-data kind delivered all those results as side reads.

This is reproduced from the actual captured `long_context-01/t6` synthetic state, not a guessed
legacy shape. Its delivered answer contains **only plank guidance**. Its state retains an older
resting-HR mean for October 12–16. With the correct supplied redo for “Repeat that plank explanation
briefly,” current resolution returns guidance **plus that old resting-HR read**. The user did not
ask to reopen it and it was not part of the answer being repeated.

New-state guidance with a genuine side read should still replay both, and currently does. The
error is inventing that relationship when legacy state does not establish it. The new compatibility
test expecting one read from every legacy guidance/data shape codifies this ambiguity instead of
contrasting a genuine side read with stale history.

**General repair:** derive legacy delivered components from reliable last-turn information when
available; otherwise do not assume surviving data belonged to a guidance/memory/status answer.
Keep older results addressable for an explicit selection without appending them to an unrelated
repeat. Do not delete the history or break modern metadata to repair the fallback.

**Controls:** the captured guidance-only legacy state; the same shape after memory-only and
status-only answers; a genuinely mixed last answer with inspectable last-turn evidence; modern
states with zero and nonzero side reads; and explicit selection of an older result. An unknown
relationship should not become a fabricated relationship.

## Remaining finding 3 — [P2] Replaying coaching loses its response count

**Code:** `backend/app/agent/requests.py::_redo`, `_replayed`, and the saved `answer` metadata in
`interpret`.

The modern metadata preserves kind, component counts, focus, topics and recall, but does not
save the requested point count. In an independent two-turn interpretation probe, the first
request correctly resolves coaching with `points=3`. A correctly supplied unchanged redo for
“Repeat that answer briefly” has no newly requested count. It resolves to the same coaching
focus with **points=None**, and the saved answer has no count to inherit. An explicit new count
of two correctly resolves to two. Current assembly uses the new question/request count, so the
unchanged repeat can fall back to one option instead of preserving the three-point response.

Preserve the previous response constraints when the repeat does not change them; an explicitly
new count must win. Keep formatting constraints in conversation state, separate from durable
memory. Cover three-point answer → brief repeat → explicit two-point edit → repeat, and new
questions that should start with their own constraints. This is another incomplete whole-answer
boundary, not an arithmetic or reader-extraction failure.

## Verification and next step

- Ruff check and formatting check pass.
- Targeted backend run: **275 passed** (the new review tests plus clause/request/edit reliability
  tests). These are a subset of the full suite, not extra accuracy cases.
- Full backend suite: **2,617 passed in 386.91 seconds**. The 275 targeted tests are
  included in this total, not additional tests.
- Independent probes and captured-state input: ignored local files under
  `data/eval/462f700_review/`. Network is blocked in the probe process; unavailable-guidance
  retrieval returns an empty source set. No live reader, embedding, web, judge or guard calls.
- Production files, paid-run inputs and earlier audit artifacts remain unchanged. No new spend.

After these boundaries are repaired, inspect the new SHA and rerun the corresponding controls.
The schema and reader changes still need their capped matched-reader measurement before a fresh
unseen paired release audit. Passing these supplied-field tests cannot prove extraction quality,
and no finite review can guarantee every future question. The known deterministic failures should
be closed before the remaining shared budget is used.
