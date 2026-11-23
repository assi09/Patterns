# Deferred agent issues after the final PR #195 audit

**Status: recorded for later work; no new repair/audit round is started.** The team chose to
finish the final audit and move on to other deliverables. Candidate:
`910da27c912486dac18c7901ce6548df91a258fe`. See the
[completed report](independent-audit-910da27-final.md): matched full results improved
504/592 → 563/592, new wordings 42/48 full, PHIA 24/24.

The priorities below identify what matters when work resumes. They do not imply the original
release gates passed. Concrete per-turn grades and raw attempts remain private under
`data/eval/910_final_review` and `910_final_results`.

## Higher-priority correctness gaps

1. **Relative-period boundary roles.** A three-day block ending on the old first date can be
   read as starting there; a four-day block beginning two days after the old last date can be
   read as ending there. These are accepted, internally consistent wrong windows, not arithmetic
   errors. Examples: `metric_strain-02/t2`, `date_endzero-02/t2`. Future work should bind semantic
   boundary roles and protect explicit requirements, with contrasting start/end/before/after
   controls. Do not globally flip endpoints: most current controls pass.
2. **Whole-message policy survives composition.** Offline preflight shows that promoting a
   repeated overview beside status/recall drops `medical`, `fabricate`, `mix_sources` flags.
   Fabrication/source-mixing refusal flags are bypassed in the supplied-reading controls; those
   controls do not demonstrate invented figures or actual source mixing. Preserve message policy
   independently of primary answer kind. Source: `requests.py::_composed`.
3. **Protected retry counts.** Offline preflight: a null replacement of a three-day length is
   restored, but replacement with one is accepted; replacement with two changes even the
   clarification to two. Protection must cover changed values and semantic period identity,
   without indiscriminately freezing a mistaken first interpretation. Source:
   `requests.py::_lengths_kept`.
4. **Food source, nutrient and meal-filter edits.** Correct breakfast openings can be followed
   by false unavailable-metric questions when protein or all meals are requested. An explicit
   tracker-energy switch may clarify or return food intake. An edit to both intake/expenditure
   panels can ask which result despite “both”. Treat source, nutrients, filters and whole-answer
   scope as independent editable dimensions. Examples: `final_food_breakfast-01/t2–t3`,
   `final_food_morning-01/t2–t3`, `food_unknown-01/t3`, `food_unknown-02/t3`,
   `food_filter-02/t2`, `food_both-01/t2`, `food_both-02/t2`.
5. **Memory replacement and misleading duplicate acknowledgement.** “After dinner now, rather
   than before breakfast” is treated as already kept although only the old preference remains.
   The expected replacement card is absent, so later recall/forget steps fail the intended
   workflow. The more explicit “replace ... with ...” wording works. Preserve positive new
   content separately from the negated old target. Examples: `memory_replace-01/t1–t3`.
   No unconfirmed deletion occurred; the old fact remains until an explicit valid tap.

## Other intent, continuity and completeness gaps

6. **Recall versus other memory actions.** A no-save statement plus approved-profile recall can
   produce an unrequested Forget proposal; chat-only recall can ask about measurements; recall
   after deletion can deny an earlier chat reference. Durable deletion and conversation history
   must remain distinct. Examples: `memory_crosschat-01/t3`, `memory_chatonly-01/t2`,
   `memory_delete-02/t3`.
7. **Return to the broader result after selecting a side read.** Both explicitly dated
   all-measure returns ask which measures instead of returning the comparison. Whole-answer
   target semantics and operation inheritance still disagree in this path. Examples:
   `main_side_scope-01/t3`, `main_side_scope-02/t3`.
8. **Exercise identity and source continuity.** After declining a moving-surfboard push-up,
   “standard floor movement” becomes barbell floor press. One bodyweight-squat continuation
   also adds a box-squat variant. Examples: `guide_unknown-02/t2`, `guide_squat-01/t2`.
9. **Status/read requests versus edits or acknowledgements.** A pending-card read is interpreted
   as a failed correction; “before confirming” overrides a confirmed-food-total read with status
   only; “do not store” can override requested plank instructions. Missing-card corrections ask
   for unrelated measurements. Examples: `workout_paused-02/t4`, `food_draft-02/t2`,
   `long_context-01/t2`, `workout_nocard-01/t2`, `workout_nocard-02/t2`.
10. **Food-draft false fabrication refusal.** One wording of a supplied custom snack is refused
    as fabricated evidence, leaving no draft for the later status step. Another wording works.
    Both use the fixture name “synthetic crackers”; test ordinary custom names before inferring
    a general real-food failure rate. Examples: `food_draft-01/t1` and cascading `/t3`.
11. **Coverage and explanatory completeness.** A recorded/missing-sleep question becomes an
    all-metric change overview; low-wear quality caveats can be omitted; descriptive averages can
    be called “steady” without a change test. A newly worded causal-limits question can repeat
    the comparison without answering the limits part. Examples:
    `coverage_gaps_sleep_minutes-02/t1`, `coverage_lowwear_steps-01/t1`,
    `coverage_gaps_sleep_minutes-01/t1`, `final_coaching_changed-01/t2`,
    `final_coaching_quiet-01/t2`.
12. **General coaching scope.** Two three-point answers include a public healthier-snack
    suggestion beyond the agreed sleep timing/load/rest/movement coaching scope. Source labels
    are correct, and no personal efficacy is claimed, but source availability is not sufficient
    relevance/scope validation. Examples: `investigate_lowwear-02/t4`, `investigate_gaps-02/t4`.

13. **"That earlier week" picks the opening week (measured limitation).** In the Fitbit replay,
    "For that earlier week, just Monday to Friday?" after "And the week before?" pointed at the
    opening week in 63 of 66 readings. An order selector resolved by code (branch
    `fix/reference-by-order`, not merged) raised the right week to 16 of 66 and exact weekdays to
    12 of 66 in a reader-only check: the reader's choice, not the resolution, is wrong. Decided
    2026-11-23 not to merge it or spend more on this week. Known limitation: when calendar order
    and conversation order differ, "earlier" can be read as the week asked about earlier. See
    [experiments.md](experiments.md#picking-an-earlier-week-by-order-2026-11-23).
    Three more attempts the same day separated the causes: showing each result with its question
    (steps 2 to 32 of 66, but heart rate and sleep fell), the large reader (about 60% right), and
    a calendar week of an earlier result with weekday and weekend parts (dates right, week still
    the opening one). None is merged: the remaining cause is how the model reads an ambiguous
    phrase, and every answer states its dates. See
    [experiments.md](experiments.md#that-earlier-week-model-and-representation-2026-11-23).

## Keep the improvements

Preserve evidence versioning and inspectability, correct zero/missing handling, approval-only
memory changes, no-write text confirmation, paused/overnight workout calculations, record-aware
rendering, two-period coaching scope, honest source limits, side-read persistence, deduplication
and formatting state separate from durable memory. All 42 checked workout payloads and all
1,566 reopened citation references passed in the final audit. Improvements should not be undone
while addressing a rarer wording failure.
