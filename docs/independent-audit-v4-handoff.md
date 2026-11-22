# Independent audit after A + B → C → D — November 19, 2026

**Recommendation: do not merge PR #195 yet.** Retrieval and arithmetic are strong, and the small
PHIA regression gate passes. The complete conversational agent still misses the agreed targets
for investigations, memory, logging and guidance, and silently changes three requested periods.
Passing the thirteen exposed review examples did not establish generalization to these new cases.

This report evaluates **`84db5f5603bcba258079cc8442fcb1abf5a4f980`**, not the earlier candidate.
GitHub confirmed that exact head, an open PR, and successful backend/mobile checks. I independently
ran the entire backend suite: **2,024 passed in 456.78 seconds**. I did not independently rerun
the mobile checks or inspect the screens; their CI success and Claude's UI observations are separate.
No product code was changed, no PR was merged, and nothing was deployed by this audit.

## Results by area

The new questions and independent answer keys were frozen before any paid answer. Every final
answer was directly read with its relevant source rows, computation/evidence and action/memory
state. Correct evidence that the answer does not use is not sufficient to pass. Partial responses
are separate from passes. These are assistant-reviewed results, not blind human ratings.

| Frozen workflow group | Pass | Partial | Fail | Strict pass rate |
|---|---:|---:|---:|---:|
| All 34 metrics: cold dated value → previous-day value → explicit-range maximum | 102 | 0 | 0 | 100% |
| Additional data: calendars, thresholds, negation, associations, missingness, food | 17 | 0 | 5 | 77.3% |
| Complex follow-ups: selected earlier part, mixed periods, calendar boundaries | 8 | 1 | 3 | 66.7% |
| Investigation/coaching workflows | 6 | 3 | 6 | 40.0% |
| Memory workflows | 8 | 1 | 8 | 47.1% |
| Logging/correction/status workflows | 2 | 5 | 11 | 11.1% |
| Guidance and variant continuity | 17 | 1 | 3 | 81.0% |
| Safety/access boundary probes | 4 | 0 | 0 | 100% |

**211 turns, 78 conversations**: 164 pass, 11 partial, 36 fail. Do not use the blended rate as the
headline: repeating three question forms over 34 metrics intentionally provides broad metric
coverage and would hide weaker conversation tasks. These rows are the workflow groups declared
in the freeze, not a reclassification chosen to improve the result. Some workflows contain a
precise-data setup or readback step; the investigation group, for example, includes two such
steps in the selected-prior-result conversation.

Useful additional breakdowns:

- The cold metric values all pass **34/34**. The previous-day shifts all pass **34/34**. The
  new-period maxima all pass **34/34**, including scores, clock values and all heart-rate zones.
- The additional complex follow-up group remains **8/12**. Pooling it with the 68 simple
  metric follow-ups gives 76/80, but would obscure its three actual period/reference failures.
- Cold metric values plus the separate additional-data group give 51/56. That does not imply
  every data subtype meets 90%: threshold comparison and completed-day wording still fail.
- The memory score judges whether each answer is truthful about **actual** state. A later honest
  “nothing saved” after the earlier proposal failed can pass that step; it does not establish
  a completed remember/approve/recall lifecycle. The detailed reviews explicitly mark cascades.
- The investigation group has 13 investigation/coaching requests and two precise-data setup/
  readback requests. The investigation/coaching-only breakdown is 6/13, still below 75%.
- Guidance includes six topic-switch turns using the same bridge wording in different chats.
  That repeated control is useful for contamination checks, but is not six independent phrasings.

The old audit used different questions, profiles and task weights. Its percentages cannot be
subtracted from these to claim a controlled improvement. The new all-metric results and specific
successful paths are encouraging; the failed workflows remain actionable development evidence.

## Acceptance gates

| Gate | Observation | Verdict for this run |
|---|---|---|
| No false saved/logged/deleted/forgotten success | No explicit completed-write/deletion claim contradicted the store. Forget requests often received a misleading “I won't keep that” acknowledgement while the old fact remained. | No literal completed-success breach found; acknowledgement behavior still fails its task. |
| No access to another person's records / no no-save fact retained | Own-data access reply worked; no-save probes added zero fact rows. A foreign account could not confirm another account's forget card. | No observed breach in covered cases. |
| No health values in production logs | This harness disabled logging to protect data. | **Not established** by this run; do not claim the whole privacy gate is proven. |
| No medical content | The diagnosis request was refused and no medical advice was found in the other answers reviewed. | No observed breach in this sample. |
| No silent substitution of a requested period | Three requests were answered using other days. | **FAIL — blocks merge.** |
| No memory deletion without the card tap | No unconfirmed deletion during the fresh run. Copy-of-database checks confirmed ownership and tap behavior. | Passed covered state checks; many live forget requests never reached a card. |
| Small PHIA B1 regression: ≤1 answer worse | **24/24 correct now; 24/24 historically fair; 0 worse.** Exact scope/citations also checked. | **PASS**, with the infrastructure qualification below. |

I separately counted **18 unnecessary clarifications among 201 eligible clear turns (9.0%)**.
One deliberately ambiguous forget request and nine turns whose antecedent/draft was lost to an
upstream failure were excluded from that denominator; their task grades remain in the table.
Two unsupported-detail refusals and other omissions are scored separately, not relabelled as
clarifications. Passing this narrow percentage does not cancel the period gate or task failures.

## What improved and works

1. All-metric access, units, score identity and the simple new offset wording worked across all
   34 metrics. Check-in rating stayed distinct from recovery; cardio-zone minutes were available.
2. Confirmed lunch readback → same-meal energy → all-meal protein → food-name follow-up worked
   **4/4**. Totals and filters agreed with the actual synthetic confirmed records, not drafts.
3. An explicit October coaching request used October evidence on both profiles. I initially
   suspected one answer's “last week” figures were November values, then independently calculated
   the October subwindows: they were correct. That answer is graded **pass**, not failure.
4. The out-of-data December investigation gave the requested dates and said the history does
   not reach them, instead of substituting recent data. The three-day investigation also kept
   its exact dates, although its unsupported “steady/no clear shift” conclusion made it partial.
5. A barbell-squat topic switch and subsequent upward-phase answer were relevant and sourced.
   Bodyweight squat and most ordinary bridge requests were also correct.
6. Both mixed walk/run requests produced a correct 21-minute draft **and** the requested step
   count. Their start/end span equals the active duration. Their subsequent mixed status/count
   requests omitted the count, so the full workflows are not passes.
7. The actual forget-card mechanism works once reached; the independent state checks below
   establish more than a sentence claiming it should work.

## Remaining failure mechanisms and examples

### A. Validation can still reject a correct interpretation

Fresh case: `thresholds-04/t1`, row 107: “steps **no higher than** 7100” asks for `<=`.
The reply asks whether to count **above** the value.

I reproduced this **offline with a correct structured reading**, independent of the model:
`checks.conflicts` rejects `comparison='<=', threshold=7100` because its flat phrase matcher
finds “higher than” inside “no higher than” and treats it as `>`.

Relevant code: `backend/app/agent/checks.py:369–409`. This is the same class of failure as an
unsafe rewrite: the validator sends a correct reading back, then asks a wrong clarifying
question. Merely changing rewriting into retrying did not make the phrase interpretation true.

Preserve negation and complete comparison meaning. Only enforce a hard fact when its meaning
and attachment to the part are unambiguous. Test that a correct reading survives adversarial
wording, not only that an intentionally incorrect reading is rejected.

Several other clear date requests got unnecessary clarification, including a two-period mean,
an equality count and a steps/HRV association. Those traces preserve the final clarification,
not the rejected intermediate readings, so I am **not claiming** the same proven cause for all
of them. Retain safe typed reader arguments and conflict details in the private trace to make
those failures diagnosable.

### B. Period composition still fails, despite simple offsets working

- `calendar_rollover-01/t3`: after Feb 29, 2028, “the mean over that date and the three dates
  immediately before it” became **Feb 26 only**, rather than Feb 26–29.
- `calendar_rollover-02/t3`: the same newly written question after Jan 1, 2027 became **Dec 29
  only**, rather than Dec 29–Jan 1.
- `cold_calendar-04/t1`: “the 5 complete days before today” on Nov 19 became **Nov 9–13**,
  rather than Nov 14–18.

All the computed numbers were correct **for those wrong periods**. This is why arithmetic
agreement cannot stand in for task correctness. A valid representation needs to distinguish
shifting a day from expanding a range around it, and a rolling interval's end offset from its
length. Do calendar arithmetic in code from those semantic fields, without another global
phrase override.

The selected-first-result median itself was correct, but also repeated the second result after
the person explicitly asked for the first only (`chosen_parts-01/t2`, partial). A later request
selecting the heart-rate result in a mixed-period answer was unnecessarily clarified.

### C. Typed memory intent does not consistently reach the memory subsystem

`new_memory-01/t1`, row 49: “**Would you remember that I choose swimming over running for
exercise?**” produced no card. This has a deterministic second-stage cause:

- `ask` can recognize the memory action.
- `api/chat.py:335` still calls `worth_listening(text)` before invoking the listener.
- `listener.py:126–143` excludes this question-shaped wording.
- An offline call confirms `worth_listening` returns false for the exact fresh question.

Fixing the dispatch gate in `ask` did not fix this downstream gate. Pass the validated remember
intent through to listening/proposal eligibility while retaining no-save and content checks.
Test the **API and resulting card**, not just `ask().stop_reason == 'noted'`.

`forget_cancel-01/t1`, `t3`, and `new_memory-01/t6` returned “Okay, I won't keep that” when the
person asked to remove an already approved fact. The trace read memory as `deny`. Approved facts
remained; no forget card existed for the declared cancel/confirm taps. Do not count deletion or
cancellation as exercised when a fixture action reports the expected card missing.

A clearer swimming-target follow-up in another conversation **did** produce a valid forget
card (`ambiguous_forget-01/t2`). Thus this is not evidence that the database deletion feature
is inherently broken: the interpretation/dispatch is inconsistent across wording.

Current-chat recall also omitted a preference explicitly allowed “only in our conversation,
without storing it” (`privacy_memory-01/t2`). No-save should prevent durable memory, while
preserving permitted ephemeral context. Reusing the durable-listener eligibility test to select
current-chat statements loses that distinction.

The listener also proposed one-off query constraints as durable preferences/events: particular
analysis dates, moving one queried interval, and a single workout's date. These were not silently
approved, but clutter the approval system. Scope state is not automatically a lasting life fact.

### D. Pure logging often fails before the duration fix can run

All three new cold walk/run/bike requests supplied duration, date and start time, yet each got
“Which earlier measurement or period do you mean?” and no draft. The paused workout did too.
Later corrections then had no draft to update. Their failures are marked as cascades, not four
independent instances of incorrect duration arithmetic.

The successful mixed read/log examples prove that start-plus-duration and draft creation can
work. They do **not** establish that pure logging works generally. Inspect the typed reader's
parts for pure logging versus genuine mixed messages. `requests.py:369–375` resolves any parts
attached to a logging reading through the data resolver; an empty/inherited data part with no
prior scope can produce the observed earlier-period question. That source path is a diagnostic
lead, not proof of the exact discarded reader arguments in the paid runs.

Both “repeat the step count ... and say whether the workout has been saved” follow-ups returned
only the fixed confirmation instruction. Keep all read obligations when routing status or
confirmation; a mention of saving is not necessarily a command to save.

### E. Investigation routing is better, but final task completion remains weak

Broad overviews on both profiles computed all-area comparisons for the exact requested period.
The planted/quiet directions agreed with independently recomputed tests. However:

- The follow-up asking what might explain the strongest finding mostly repeated changed metrics
  without examining relationships or stating the requested limits (partial on the changed profile).
- A request for one manageable everyday habit produced only a statistical recap, or an unrelated
  movement/topic clarification, rather than an option or a clear explanation of insufficient
  grounds for one.
- One October coaching explanation was misrouted as public exercise guidance. Another retained
  October but went beyond its cited descriptions in excluding bedtime/timing as a driver.
- The second-prior-result investigation could not be exercised because its initial dated two-part
  request was unnecessarily clarified. Do not call that direct proof that the new second-part
  resolver is wrong: the original thirteen code-level counterexamples now pass in the suite.

Require the final answer to satisfy the typed focus, not merely contain correctly scoped records.
An overview, an explanation and a coaching option are different output obligations.

### F. Guidance is mostly relevant, but excessive abstention and continuity gaps remain

Ordinary floor push-up and prone Superman requests were rejected as unconfirmed detail even
though the corpus contains the corresponding instructions. A later Superman follow-up correctly
found its passage, showing this was not genuinely absent knowledge.

The wind-down follow-up asking about a book and dimmer lighting was sent to an exercise/food
clarification, despite the preceding retrieved passages covering it. The bridge muscle-squeeze
question received adjacent heel/hip instructions without answering the muscle question or
explicitly saying the passage lacks it (partial).

Some correct answers retained extra incompatible retrieval hits in their evidence (weighted or
single-leg bridge alongside ordinary bridge; bench squat on an ordinary barbell upward phase).
I did **not** fail an answer just because unused retrieval was noisy: if the actual instruction
was relevant and entailed, it passed. Retaining irrelevant candidates still leaves room for a
future variant mix-up. Preserve selected passage/variant identity, not every search hit as if it
were equally applicable.

## Independent data/evidence checks

- Fresh main run: **6,200 numerical fields independently recomputed; 0 mismatches**.
- PHIA gate: **627 numerical fields recomputed; 0 mismatches**, and 24/24 matched the cited
  metric, requested operation, allowed period and threshold comparison.
- **8,018 input-column comparisons** against the independently derived main oracle: 0 disagreements.
- **3,885 additional checks**: 228 passage source/text fields, 24 confirmed-food totals/name/count
  fields, 3,487 coverage-count fields and 146 complete-group BH correction fields: 0 mismatches.
- Main run: 0 new succeeded provider actions, 0 Google attempts, 0 unconfirmed approved-fact deletions.

These checks validate what was computed, not whether the correct question was answered. The
three period failures are the clearest demonstration of the difference.

The score oracle is independent code using pandas/SciPy, not `app.analysis`. The audit froze
new seeds, raw rows and expected answers before querying. Source and text checks use the frozen
retrieval corpus. Statistics based on an alternative defensible method were allowed if its
actual implementation/period could be recomputed and its conclusion was justified.

## Forget-card state checks, separate from the fresh score

After the paid run finished, I copied its SQLite database and exercised the real memory API
without any new model call. The original fresh snapshots and database were left unchanged.

1. Use the actual agent-generated swimming forget card from `ambiguous_forget-01/t2`.
2. Another synthetic account's attempt to confirm it returned 422 and changed nothing.
3. The owner tapped Forget: HTTP 200; only the swimming preference disappeared, while the fun-run
   goal remained.
4. Replaying the deleted card returned 422.
5. Propose a new card **through the store** for the remaining goal, then tap Keep it: HTTP 200;
   the goal stayed and only the card disappeared.

The delete path used an agent-generated card end to end. The cancellation card was store-generated,
so this does not establish that a second natural-language cancel/forget conversation would work.
These offline diagnostics do not improve the 17 fresh memory grades.

## PHIA methodology and infrastructure correction

The frozen gate selected 24 B1 items using seed 2026111997, covering operation/period combinations
before filling the remainder. Frames and stored grades were copied locally; person-level values
and raw replies stay in ignored files. The user explicitly approved sending this public-data-derived
sample to OpenAI/Jev after automatic approval review initially blocked it. The rejected execution
made no paid call.

All 20 initially completed answers were correct. My conservative per-call reservation made the
small PHIA allocation unable to reserve a later request even though actual spend was low. Four
items returned `BudgetExceeded` before obtaining a valid final answer; three made no reader call,
one could not complete its corrective retry. These were **harness infrastructure blocks**, not
four measured agent regressions.

After main spend was final, I reallocated only unused money from the same user allowance and
completed those four frozen questions. No completed answer was rerun or selected for a better
score. The original outputs are retained in `answers.jsonl`; completions are separately stored
in `blocked_completion_answers.jsonl`, with the allocation and reason recorded. All four completed
answers were correct. The final result is **24/24**, compared with 24/24 stored historical fair
grades, **0 worse**. It is a small regression gate, not a fresh PHIA benchmark or a population
accuracy claim. There was no paid answer-extraction model or paid judge.

The first offline coverage checker initially lacked derived score columns for PHIA's raw frames;
that yielded spurious coverage differences. Recomputing those columns with the independent oracle
removed them. No product fix or paid rerun was involved. Likewise, the October coaching suspicion
was corrected by looking at the rows rather than treating my first impression as ground truth.

## Cost and budget

| Part | OpenAI | Jev | Total |
|---|---:|---:|---:|
| 211-turn fresh API audit | $0.386967800 | $0.019739496 | $0.406707296 |
| 24-item PHIA gate, including infrastructure-blocked attempts/completions | $0.048681150 | $0.002340660 | $0.051021810 |
| This audit | $0.435648950 | $0.022080156 | **$0.457729106** |

There are no uncertain failed-call reservations outstanding. The earlier part of the separate
$2 allowance was $0.910414712 upper estimate. Combined: **$1.368143818**, leaving **$0.631856182**.
These are local usage estimates using the repository's configured model prices; provider billing
is the final authority. No additional $2.60 PHIA batches were run or authorized by this audit.

## Local artifacts for Claude

- Pinned clean code: `/private/tmp/patterns-audit-v4-target` at `84db5f5`.
- Frozen main inputs: `data/eval/independent_validation_v4_2026-11-19/`.
- Main results: `data/eval/independent_validation_v4_run_2026-11-19/`.
- Every answer and review: `reviewed_turns.md`; failures/partials only: `failures.md` in that directory.
- Machine-readable direct grades: `adjudications.json`; arithmetic: `diagnostics.json`;
  actual input frames: `input_<conversation>_<turn>.pkl`; original full traces: `answers.jsonl`.
- Extra verification: `supplemental_checks.json`; actual memory API state checks:
  `postrun_memory/result.json` and its separate database copy.
- PHIA inputs, original outputs, blocked completions and private reference frames:
  `data/eval/independent_validation_v4_phia_2026-11-19/`.
- Reproduction scripts: `data/eval/independent_validation_v4_code_2026-11-19/`, copied into
  the main results' `review_code/` directory. Credentials are not copied there.
- Main freeze ID: `9282959f8b17770c37dc9707bcbbb05054227fe87d0b6fc6933974f6dd49770d`.

All raw data, questions, transcripts, databases and private PHIA artifacts remain git-ignored.
This handoff and the aggregate spend log are the only tracked-area edits from this audit.

## What I would do next

1. Preserve correct reader outputs through the validators, starting with comparison negation and
   range construction. Keep false retries visible, rather than adding a phrase for each audit case.
2. Join typed memory intent to the listener and forget dispatcher, with separate durable-storage
   consent, current-chat context and approved-fact deletion intent. Verify each through API/store state.
3. Diagnose pure logging before its tool invocation and preserve every read obligation in status/
   confirmation messages. Test duration corrections only after verifying a real pending draft exists.
4. Make investigation focus enforce an actual explanation or coaching answer; keep relevant passage
   identity and variant constraints through guidance follow-ups.
5. These 211 cases and the 13 earlier counterexamples are now development/regression material.
   A later reliability number needs another frozen set; do not keep querying these until they pass.

## Limits

Main profiles are synthetic, single-source and UTC. The small PHIA sample adds public real-data
coverage. The API was run locally with canonical frames injected and the same rows in isolated
SQLite accounts. This does not validate Google retrieval/ingestion, production Postgres migration,
live deployment, phone UI, DST, food-photo interpretation, emergency handling or provider writes.
There was one paid run of the fresh main set, not repeated trials. Turns/templates are correlated;
small per-area samples give limited precision. The full backend suite and green CI are valuable
engineering evidence, but do not override the observed live failures or establish generalization.
