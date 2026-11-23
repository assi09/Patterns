# Review of the uncommitted audit fixes — November 19, 2026

> **Historical record** (added to the repository on 2026-11-19), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

This is a **new offline code review**, separate from the completed 488-turn paid audit. It does
not change the earlier scores or claim a new live-agent accuracy. The shared working tree is
still based on `fa15f4a`, with Claude's uncommitted changes. The reviewed source and test files
were copied into an isolated snapshot before testing. No product source was edited by this review.

## Assessment

The changes target real defects and several address the underlying invariant: keeping an existing
score's definition, sending recognized confirmations to the waiting card, reporting nonmissing
counts explicitly, and distinguishing a constant series from absent paired observations.

They are **not ready to treat as generally fixed**. The latest copied snapshot has two failing existing tests,
and seven additional independent deterministic counterexamples fail. One initial count-parsing
regression was narrowed by Claude while this review was underway; that old test now passes. The new tests for the known
audit examples pass, but surrounding valid inputs expose regressions and an execution error.
The pasted Claude transcript itself ends mid-work with failing tests; it is not a completed
verification report.

## Checks actually run, at $0

- Initial offline pytest on `test_audit_v3_fixes.py`, `test_broad_questions.py`, `test_requests.py`,
  `test_compare_day.py`, and `test_analysis_tools.py`: **178 pass, 3 fail** (181 checks).
- After copying the newer coverage-parsing changes and three added tests, the same related suite
  has **182 pass, 2 fail** (184 checks). Including the seven independent counterexamples, the
  latest copied snapshot has **182 pass, 9 fail** (191 checks).
- The same three failing existing cases on the clean original `fa15f4a` candidate: **3/3 pass**.
  These are introduced behavior changes, rather than pre-existing red tests.
- Seven new deterministic counterexamples against the copied uncommitted source: **0 pass, 7 fail**.
- No paid calls, live Google activity, production database or user health values were used.
  Python socket connections were blocked. The complete backend/mobile suites were not run.

The additional tests drive structured request normalization/rendering and the output guard directly.
They demonstrate code-level failures; they do not measure how often a live reader produces each
intermediate representation. In particular, the explicit correction test supplies a schema-valid
explicit date with a redundant previous-anchor field; it checks defensive handling of that input.

## Findings to fix before another paid validation

### 1. Calendar repair overwrites other parts' explicit dates

`backend/app/agent/requests.py`, `anchored_by_code`, around lines 201–208.

For **Average steps this week, and sleep duration on November 2, 2026?**, start with the correct
structured interpretation: one calendar-week steps part and one explicit November 2 sleep part.
The override finds “this week” anywhere in the question and assigns its November 16–19 interval
to **every** part with one period, including the explicit November 2 part. That changes a correct
single-day answer into a different period.

Likewise, **the week before last week** with a correctly interpreted two-weeks-back calendar
period is overwritten with last week. A substring match should not override a more specific
relative period or an unrelated explicitly dated part. Apply a deterministic calendar repair only
to the part/period to which the phrase belongs, preserving explicit dates and modifiers.

Repro tests: `test_calendar_override_keeps_other_parts_explicit_dates`,
`test_week_before_last_week_is_not_last_week`.

### 2. Five-metric coverage raises KeyError

`backend/app/agent/requested.py`, around lines 185–189, and
`backend/app/analysis/tools.py`, around lines 102–103.

The renderer enters its joint-coverage branch for any list longer than one, but `coverage` only
creates `days_all_present` for **two through four** columns. Five valid recorded metrics therefore
raise `KeyError: days_all_present`. The request schema allows up to eight metrics.

Define joint coverage consistently for the supported number of selected metrics and keep the
renderer/tool contract aligned. “Both” also needs suitable wording when there are more than two.

Repro: `test_five_metric_coverage_does_not_crash`.

### 3. The fallback success guard is still tied to surface wording

`backend/app/agent/ask.py`, `FALSE_SUCCESS` and `no_false_success`, around lines 303–315.

- **I’ve logged your walk.** with the common curly apostrophe passes the guard unchanged.
- **I have added the source citations below.** is incorrectly replaced with a nothing-waiting-to-log
  message even though it describes the answer's citations, not a provider write.
- **When it's saved, you can undo it from the entry card.** is incorrectly replaced even though
  it is conditional workflow guidance, not an assertion that saving occurred.

The deterministic recognized-confirmation path is a useful improvement. The global fallback regex
is not a reliable state-truth guarantee. Scope status templates to the actual action/status intent
and persisted state, and test negation, conditional statements, Unicode punctuation and unrelated
uses of words such as added or recorded. Adding only these three exact phrases would repeat the
same generalization problem.

Repros: `test_false_success_guard_handles_curly_apostrophe`,
`test_false_success_guard_does_not_rewrite_added_citations`,
`test_false_success_guard_does_not_rewrite_conditional_instructions`.

### 4. Log-date cleanup can erase an explicit correction

`backend/app/agent/requests.py`, `_log_day_by_code`, around lines 229–235.

A schema-valid correction naming **November 12, 2026**, with an explicit period carrying a redundant
`anchor=previous`, is turned into `log_day=None` because none of the five today/tomorrow/yesterday
phrases appears. Explicit dates should win regardless of irrelevant anchor metadata. Similarly,
relative corrections such as moving an entry one day earlier need actual date handling, rather
than being treated as if no day had been mentioned.

Repro: `test_explicit_correction_date_wins_even_with_redundant_previous_anchor`.

## Existing-test failures and the correction during review

1. `test_requests.py::test_bad_reader_output_asks_instead_of_falling_back_to_all_history[fields1]`:
   a count with no threshold/comparator is now always converted to coverage. For the vague input
   **check this**, this returns an all-history data request instead of clarification. A genuine
   observation-count question can use coverage, but missing count arguments do not themselves
   prove that was the intended question. Claude added `_coverage_by_code`, gated on recording
   language, during review and restored the resolver clarification for other incomplete counts.
   **This particular test passes in the second copied snapshot.** The seven independent
   counterexamples are unchanged and still fail there.
2. `test_requests.py::test_causality_follows_observed_association_state[constant]`.
3. `test_requests.py::test_causality_follows_observed_association_state[missing]`.
   For these explicit causality requests, the response now explains why correlation is unavailable
   but drops the explicit causal-limit answer. Keep an evidence-aware explanation: missing or
   non-varying data cannot establish an association or a cause. The old exact sentence need not
   be mandatory, but the user's causality question still needs answering. Do not simply weaken
   the tests to obtain green checks without reviewing that behavior.

## Scope and next steps

This patch intentionally addresses a subset of the audit. Broad investigation/coaching, memory
routing, exercise-variation retrieval, stale food filters and several follow-up reference failures
remain outside these straightforward fixes. Passing these unit checks would not establish that
those broader areas work. The tests use scripted reader outputs, so a later paid run still needs
to verify that real interpretation reaches the correct path.

Continue repairs in Claude's working changes; this review leaves them untouched. Keep the new
counterexamples as regression material, fix the existing red tests with the intended behavior,
and verify the complete backend suite before freezing another candidate commit. Then use new
conversation wording for any subsequent generalization score. The earlier 81.6% fresh score
continues to describe `fa15f4a`, not these uncommitted changes.

## Local reproduction artifacts

`data/eval/independent_validation_v3_fix_review_2026-11-19/` contains:

- `receipt.json`: base SHA, exact reviewed-file hashes, workspace/snapshot equality and outcomes.
- `reviewed-working.patch`: the copied product-source changes.
- `test_audit_v3_fixes.snapshot.py`: Claude's test file as reviewed.
- `test_independent_fix_review.py`: the seven independent counterexamples.

The latest executable isolated snapshot is `/private/tmp/patterns-audit-fix-review-20261119-v2`.
The first copy remains at `/private/tmp/patterns-audit-fix-review-20261119`. The receipt records
which shared-workspace files still match each reviewed copy; ongoing edits are outside that
copy until separately checked.
Its backend test environment uses the existing project virtualenv. Run the added tests there with
`python -m pytest -q tests/test_independent_fix_review.py`; no live-agent evaluation is involved.
