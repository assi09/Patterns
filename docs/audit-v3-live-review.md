# Live implementation review — 2026-11-19

> **Historical record** (added to the repository on 2026-11-19), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

Reviewed Claude's uncommitted changes on `978aa31` in PR #195, independently of the earlier paid
agent audit. **The direction is useful, but this snapshot is not ready for a paid success claim
or deployment.** The investigation and memory categories address missing capabilities. However,
new date phrase overrides can corrupt correct reader output, memory actions are intercepted,
and the requested investigation scope is not consistently enforced.

This is a review of work in progress, not a claim that Claude finished the four-item plan.
The inspected changes were five product files and two new test files. Guidance passage retention
and workout interval changes were not present in this snapshot, so those planned items are not
assessed as implemented. No source was edited by this review, no paid provider was called, and
nothing was pushed, merged or deployed.

## What was tested

An isolated copy is at `/private/tmp/patterns-live-review-20261119`; a clean committed baseline
is at `/private/tmp/patterns-live-review-base-20261119`. Explicit `PYTHONPATH` selected the snapshot
package, preventing the shared virtual environment's editable installation from selecting the
live workspace. The seven inspected files still matched their snapshot hashes at review end.

- Existing/new author-written checks: **316 pass, 1 fail**, across requests, investigations and
  memory, follow-up scope, broad questions, listener, profile, store, and audit fixes.
- Independent, deliberately adversarial offline checks: **1 pass, 12 fail**, out of 13. These
  supply valid structured reader output or synthetic data and check the deterministic boundary.
- Baseline check: the existing five date-anchor cases **all pass on committed `978aa31`**;
  one of those cases fails with the live edits.
- Cost: **$0**. This consumes none of the remaining live-audit allowance.

These are targeted development checks, not an accuracy estimate. Scripted readers cannot prove
language generalization, and a check of their downstream tasks/evidence does not grade a real
provider's final prose. No full backend/mobile suite was run in this review.

## Findings and changes needed

### 1. Preserve semantic date transformations; do not overwrite every part from a matched phrase

`backend/app/agent/requests.py:322–336`, `_scope_by_code`.

The correct reading of “Same measure, 24 hours earlier than that day” is `relative`, previous
anchor, offset -1. `SHIFT` does not recognize hours, while `SAME_DAYS` matches “that day”, so
code replaces the correct relative expression with `inherit`. With an active synthetic date
of Oct 20, the result is Oct 20 instead of Oct 19. This also breaks the existing
`test_a_period_counted_from_today_is_anchored_to_today_by_code` case, which passes at HEAD.

A second reproduction: “Shift steps two days earlier, and give my resting heart rate yesterday.”
The reader correctly separates the shifted steps and today's-relative heart-rate day. The
one matched shift is applied to both parts, changing the heart-rate period too.

Keep the semantic reader's anchor, transformation and per-part reference. Use code for actual
calendar arithmetic and validation. If the reader contradicts a constraint, retry or clarify;
applying a phrase-derived period to every part recreates the audit's overfitting problem.
The simple “two days before today” control passes, but does not cover these failures.

### 2. Removing a meal filter does not survive resolution

`backend/app/agent/requests.py:342` and `:609–610`.

Given an active food query with meal `SNACK`, “What is my total protein for that same day
across all meals?” correctly reaches the resolver with `meal_type=None`. The resolver's
`part.meal_type or prior.meal_type` restores `SNACK` anyway. This is an existing resolver
problem that the new clearing helper does not actually fix.

Represent retaining and clearing a filter separately, or stop inheriting meal filters by default.
Test through `resolve` and food execution, not only the helper's intermediate output. Also allow
an explicit reference to the same meal without having to repeat its English meal name.

### 3. Investigation resolution needs the same reference semantics as data resolution

`backend/app/agent/requests.py:451–475`, `_investigation`.

An investigation with `reference=0`, an inherited period, and no newly named metric retains the
period but loses the prior metric. That becomes an all-metric investigation of a question about
one previous measurement. With two prior parts, an explicit `reference=1` is ignored and the
resolver asks which dates, despite an unambiguous structured reference.

Share the reference-resolution logic with precise data requests. Distinguish “no metric named,
look across everything” from “no new metric, explain the referenced result.” Validate unknown
metrics rather than silently discarding some when others are recognized. Preserve which of a
comparison's periods the person selected.

### 4. Investigation dates are recorded but not consistently used by evidence preparation

`backend/app/agent/strategy.py:604–614`; `backend/app/agent/ask.py` coaching evidence path.

The new explicit `window` parameter is useful, but a pre-existing fallback still substitutes the
latest data when the requested period is short or outside the data. Both a three-day September
window and a future December window produced October overview comparisons on the synthetic
fixture. The requested period should remain explicit: report insufficient/missing data or use
suitable descriptive tools, without silently answering another period.

Separately, a correctly read September sleep coaching request produces sleep evidence outside
September. The broad overview excludes coaching, and `coaching_evidence` still chooses its own
recent window. Propagate the resolved investigation scope into coaching/premise preparation as
well as the overview. Baselines may appropriately extend before a focal period; the focal period
itself must still be the requested one. An explicit two-window investigation should also retain
both windows, rather than taking only the first window for the overview.

### 5. A correctly classified memory action can be blocked by the old explicit-phrase gate

`backend/app/agent/ask.py:653–654`, before `remembering`.

With reader output `kind=memory, memory_action=forget`, “Please forget my old running goal.”
returns “Do you want me to remember ... or forget something?” A correctly classified polite
“Could you remember that I prefer walking?” gets the same generic question. `is_explicit` was
built for a different purpose and excludes question-shaped wording; it should not veto an
already classified, unambiguous action.

Dispatch remember/recall/forget by validated action. Clarify only when the target/action is
actually ambiguous. Pure deletion needs an identified approved fact and a confirmation flow;
the existing listener mainly proposes facts/replacements, so forwarding forget to it alone is
not a demonstrated delete implementation. Verify approve, recall, replace and delete through
the API/store, including cancellation and no-save precedence.

### 6. Inferred interests are presented as user-approved facts

`backend/app/agent/ask.py:192–201`, with `backend/app/db/memory.py:700` profile construction.

`chat.profile` includes both approved fact lines and a derived “Often looks at: ...” interest
line. `recalled` places all of it under “Kept (you approved these)”. The synthetic interest-only
profile reproduces that false approval claim.

Pass approved facts and inferred interests with separate provenance, preferably IDs/statuses,
not an undifferentiated display string. Keep waiting cards and current-chat statements separate
as the new implementation already attempts to do. Target-specific recall also needs relevant
selection rather than always returning the first five profile lines.

### 7. The new remember early return drops the reader's cost and request trace

`backend/app/agent/ask.py:715–719`.

A supplied reader budget of $0.001 and one call yields a result budget of $0 and zero calls;
there is also no request trace. Normal return paths explicitly transfer these. The API stores
`result.budget.cost_usd` for the answer, so listener charging does not restore the reader's
missing charge. This matters for the spend ledger and daily caps.

Use a common result-finalization function for early returns, including reader budget and state
trace. Cover the failure path too. The $0.001 figure is a synthetic injected budget, not a paid run.

## Other implementation notes

The request-reader prompt still says personal advice/explanations without a precise statistic
are `other`, then later assigns them to `investigate`. Remove that contradiction before testing
real model behavior. Classification tests should include personal investigation versus public
how-to, mixed read/write requests, self versus other subject, and memory commands within questions.

The author's new tests mainly exercise positive category dispatch and exact audit phrases. Add
counterexamples with a correct reader result first: the deterministic stage must preserve it.
For approved/proposed/recalled/deleted memory, test the complete state transitions rather than
only the sentence returned by `ask`.

## Reproduction artifacts and commands

Durable local artifacts (ignored; no health data in git):
`data/eval/independent_validation_v3_live_review_2026-11-19/` contains `receipt.json`, source hashes,
`working.patch`, the independent test module, and detailed pytest outputs. The tests use synthetic
rows, dates, profile text and injected budgets only.

From the isolated snapshot root:

```sh
PYTHONPATH=backend /Users/karimassi/Desktop/503P_Project/.venv/bin/python -m pytest -q \
  backend/tests/test_independent_live_review.py \
  backend/tests/test_investigate_and_memory.py \
  backend/tests/test_follow_up_scope.py \
  backend/tests/test_broad_questions.py \
  backend/tests/test_requests.py
```

The first recorded combined run predates the added coaching case: 145 pass, 12 fail. That
coaching case was then run separately and failed. The additional listener/profile/store/audit
fix checks passed 172/172. Together: **317 pass, 13 fail across 330 checks**, of which 13 are the
independent counterexamples. Do not present this selected mix as real-agent accuracy.

After fixes, rerun these development checks and the normal offline suites. Then freeze a genuinely
new conversation set before any paid run; all examples in this review are now development material.
Keep PHIA/merge on hold until authorized, and retain a basic lookup regression gate before deployment.

## Follow-up verification of Claude's response

After Claude removed the call to `_scope_by_code`, changed the memory dispatch/finalization,
separated approved profile lines, removed meal inheritance and repaired the prompt, I reran
the unchanged 13 independent counterexamples against a second isolated snapshot. **8 pass,
5 fail**, confirming the reported count. The five failures are the two investigation-reference
cases, two explicit-period fallback cases, and the coaching-period case. A forget dispatch
check passing means only that it reaches the next stage; it does not establish a working
confirmed-deletion lifecycle.

Together with the author-written request/investigation/follow-up tests in this follow-up run:
**132 pass, 5 fail, 4 expected failures**. The four expected failures are the unresolved
original follow-up cases; they remain unfinished work and must not be counted as fixes.
The earlier existing hour-offset regression now passes. The full suite was not rerun by this
review. Cost remains **$0**. Artifacts are in the local `update-2/` subdirectory of this review's
ignored bundle. Source hashes still matched at verification time.

The proposed A+B → C → D order is reasonable. Validation must preserve correctly read requests,
attach a constraint to a part only when that attachment is unambiguous, and avoid treating
negated/quoted metric names as requested metrics. A retry/clarification can still degrade a
correct answer, so benchmark unnecessary clarification and completion alongside wrong answers.
Use shared reference resolution for data and investigation. Keep the four expected failures
visible until resolved. A small PHIA regression check belongs before merge; paid runs and
deployment remain on hold.
