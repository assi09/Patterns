# Independent review and matched-reader comparison of e1c1eec — November 22, 2026

> **Historical record** (added to the repository on 2026-11-22), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

**HOLD PR #195; do not spend on a fresh release audit yet.** The three findings from the
462f700 review now pass their independent offline controls. The new reader improves overall
on the exposed matched slice, but sharply regresses successor blocks. There are also unresolved
target/composition failures and a new deterministic renderer coverage bug.

Frozen candidate: `e1c1eec0535c013b103ad33088bf41492ef24f1c`, verified locally and remotely;
PR open/unmerged, required backend and mobile CI successful. Reviewed code `c4b3e13` and its
handoff commit `e1c1eec`. No production code edits, push, merge, deployment or Google traffic.
The two pre-existing untracked handoffs were preserved.

## 1. What the three repairs now establish

- **Grounding:** the captured bad summary and the two unsupported assertions placed inside a
  valid steps claim (feeling “run down”; walking to work) now produce only code-written facts
  from the cited record. Neither assertion reaches the displayed explanation. A supported
  comparison retains its figures. The remaining issue is correct rendering of *other record
  types*, below, not continued publication of these model-authored assertions.
- **Legacy state:** the actual captured plank-only state no longer reopens its older resting-HR
  read. Modern guidance with a real side read still retains it, and an explicit older-result
  selection stays available.
- **Response count:** a three-point coaching request repeated without a new count keeps three;
  an explicit two-point edit becomes two. Formatting stays in conversation state rather than
  durable personal memory.

Ruff check and formatting check pass. Local full backend suite: **2,635 passed in 315.31 seconds**.
The targeted **293 passing tests** are a subset, not extra live accuracy cases.

## 2. Matched-reader method and results

This is **exposed development material, not held-out release accuracy**. Both arms ran once on
152 inputs selected from the prior 689 synthetic audit, with identical captured questions,
request-state histories, clocks and pending-card fields. The baseline is `689fa7c`, the last
broadly audited reader; the candidate is `e1c1eec`. This is not a comparison with the intervening
462f700 reader, whose schema was already the same as the candidate's.

The selection is predeclared in `data/eval/e1_matched/freeze.json`: all 68 metric date follow-ups,
24 calendar replacements, 12 formatting turns, 16 memory-intent/scope turns, 10 threshold edits,
eight workout edits, four explicit returns after guidance, and paired lag, status/data,
main/side and French-statistic cases. Two paused-duration-basis cases measure a newly expressible
field separately. Inputs were shuffled with seed 2026112121, in the same order for both arms.

Input hash: `e1fd342873b5798a9e12a023ec2e25e9ef4ee36869c37793b6dc394c9df3a93a`.
The frozen baseline source was extracted without changing the working tree. Read-back was off
in both arms, provider retries were off, and first/retry raw clauses were retained. The combined
new-spend ceiling was **$0.75**, enforced through the existing shared-$5 meter. No paid judge,
embeddings, external lookup, real-health records, analysis tools or Google writes were used.

Scores check request kind, metric, operation, dates, applicable threshold/lag, recall scope,
format count and untargeted correction fields. They do not grade final prose, memory persistence,
action execution or retrieval. Historical bad answers/states were not healed to favor either
reader. New-state persistence is checked separately offline. This slice does not establish
exercise-variant extraction, summary folding, full conversation reliability or PHIA performance
on the current SHA.

| Reader slice | Baseline | Candidate | Improved | Spoiled |
|---|---:|---:|---:|---:|
| Metric date edits | 44/68 | 58/68 | 23 | 9 |
| Calendar date edits | 14/24 | 22/24 | 10 | 2 |
| Format count and scope | 11/12 | 12/12 | 1 | 0 |
| French statistic edit | 1/2 | 2/2 | 1 | 0 |
| Threshold edits | 9/10 | 10/10 | 1 | 0 |
| Return to data after guidance | 2/4 | 3/4 | 1 | 0 |
| Memory intent and scope | 12/16 | 15/16 | 3 | 0 |
| Repeat status plus data | 0/2 | 1/2 | 1 | 0 |
| Workout edits | 8/8 | 8/8 | 0 | 0 |
| Main comparison after side read | 1/2 | 0/2 | 0 | 1 |
| Preserve lag | 1/2 | 2/2 | 1 | 0 |
| **Common-field total** | **103/150** | **133/150** | **42** | **12** |
| New duration-basis field, separate | 0/2 | 2/2 | — | — |

Of the 150 comparable cases, 91 pass both, 42 improve, 12 are spoiled and five fail both.
The candidate matches 135/152 including the new-field cases. It retains **17 common-field
misses**: ten wrong windows, two date clarifications, two whole-registry failures, one wrong
metric on an explicit return, one unresolved chat-memory recall and one lost status side read.
No blocked calls or incomplete cases are excluded from these counts; all 304 arm/input executions
completed. There were 340 provider completions including interpretation retries.

### Date categories expose the trade-off

| Metric date relation | Baseline | Candidate |
|---|---:|---:|
| Three dates ending on the old first day | 7/12 | 12/12 |
| Five dates immediately before the old range | 2/10 | 10/10 |
| Four dates starting on the old second day | 5/10 | 10/10 |
| **Four dates following the old last day** | **12/12** | **3/12** |
| Translate the whole range two days earlier | 6/12 | 11/12 |
| Keep only the final two dates | 12/12 | 12/12 |

A blended gain does not justify shipping a repeatable successor-block regression. These remain
accepted wrong plans in development; this comparison cannot clear the named-period release gate.

### Scoring/fixture corrections, retained transparently

The initial run predicate treated `history=true, windows=[]` as a mismatch against an expected
full-source interval. That is the correct whole-history representation. Final offline grading
accepts it for the two all-history cases in each arm; the original flags/raw outputs remain
unchanged. This checker issue was logged during the baseline arm before candidate calls.

The initial history attachment copied each captured row's main claims, whereas stored chat
turns include side claims too. Comparison against the original read-only SQLite store identified
12 affected cases (eight format, two status/data, two main/side). The reader prompt itself does
not receive these claim lists. Replaying candidate resolution with the actual stored full claims
changes **zero resolved contracts and zero attempt counts**. Original frozen inputs remain intact;
corrected claim attachments and the check are retained separately. Counterfactual controls below
use the stored full claims where relevant. No provider call was rerun to repair grading or fixtures.

## 3. Next repairs, with the first wrong decision and controls

### A. [P1] The fixed-fact renderer must dispatch by record type and statistic meaning

**Code:** `backend/app/agent/findings.py:63` (`code_claim`) and `finding_claim` at line 38;
`ask.py::said_by_claims`.

Every sufficient record containing a top-level `difference` is currently sent to the
window-comparison renderer. That renderer reads `mean_recent` and `mean_baseline`. Three real
deterministic tool outputs have different meanings and keys:

| Record | Actual fields | Meaning |
|---|---|---|
| `change_point` | `mean_before`, `mean_after`, `change_date` | levels on either side of the detected split |
| `weekday_split` | `mean_weekday`, `mean_weekend` | weekday versus weekend groups |
| `tag_effect` | `mean_with`, `mean_without`, `tag` | tagged versus untagged check-in days |

Independent synthetic probes generate each record with the actual analysis tool and start with
an accepted claim. Each ends up displayed as **“Steps went up: against .”** The tagged-day output
also becomes a `change` claim that the verifier rejects if checked again, although its input
value claim was accepted. Group differences are not automatically longitudinal changes.

**Fix:** select rendering by the record's tool/schema and preserve the statistical contrast's
meaning. Use the proper formatted figures and, for a split or groups, the appropriate split/group
labels. Only emit claim kinds supported by that record. Unsupported/missing required fields must
produce an explicit limit/unsupported result, never empty figures or a guessed comparison.
Preserve code-written factual text; do not restore model-written claims as fallback.

**Controls:** every supported record type, sufficient/insufficient records, significant and
non-significant tests, all relevant unit kinds, and generated claims passed back through the
verifier. Include the unsupported commute/outcome controls to preserve the grounding repair.
A fixture matrix over real tool outputs would catch this boundary before another paid call.

### B. [P1] Resolve period relations without the old/new endpoint role collision

`metric_hrv_ms-02/t2`: “use the next four calendar dates after the block” should select September
20–23. The candidate emits `new_last_day = old_last + 1`, length 4, and accepts September 17–20.
Nine of the twelve successor-block metric cases take this wrong side. The separate calendar
case “four dates beginning two dates after that last day” similarly returns October 19–22
instead of October 22–25.

The raw fields identify the error: the new period's **last** day is placed where its **first**
day belongs. Both its width and offset can be internally consistent. Existing arithmetic and
endpoint-consistency checks cannot detect this semantic role mistake. Offline replay changing
only that placed endpoint yields the intended dates; do not change the arithmetic or globally
flip last to first (the ending/trailing cases now work).

Two further malformed date readings exhaust the retry without filling required constraints:
`date_leap-02/t2` places neither endpoint, and `metric_readiness-01/t2` leaves length null on a
whole-range translation that keeps its size.

**Next experiment, not an assumed improvement:** reduce independent semantic choices for common
relations. A whole-window translation should let code keep the old width; predecessor/successor
blocks should let code derive their boundary from the relation and requested count. Keep a
placed-endpoint form for genuinely arbitrary anchored ranges. The existing executor already has
working calendar arithmetic. Measure any reader/schema candidate against the full matched slice,
including protected before/ending/trailing/calendar controls, before adopting it. Do not patch one
phrase, move computations into the LLM, or assume a larger model fixes this; earlier stronger-model
experiments did not establish a net gain.

The other explicit-return miss, `long_context-01/t11`, names steps and October 3–9 but selects the
old resting-HR object with empty/inherited metrics. A selected result must agree with an explicitly
named target; current named fields must not silently inherit a conflicting old metric.

### C. [P1] Preserve target scope and compose redo with other clauses

Both all-registry returns fail with the new reader. `main_side_scope-02/t3` names every metric and
two explicit periods, but emits redo/compare with empty metrics. Redo has no every-registry target
field, so empty means inherit the current steps result; the accepted plan compares **steps only**.
In `main_side_scope-01/t3`, the indexed prior is itself a broad investigation. Changing its
operation to compare loses the empty-list whole-registry meaning and ends in a metric question.

**Fix:** represent target scope independently from operation and inheritance: selected/named
metrics versus the whole registry. Explicitly requesting every metric must be expressible in a
redo, and inheriting an existing whole-registry target must retain its breadth. Route the resulting
whole-registry comparison through the existing overview behavior. Keep named side reads and
explicit one-part selections. Do not silently replace the requested breadth with the last named
metric or ask which metric when every metric was explicit. Offline use of the correct investigation
clause resolves the intended comparison on the same stored state.

`mixed_log-01/t3` exposes a second composition boundary. “Say both again in a shorter answer”
returns a redo clause **and a status clause**. `PRIMARY` selects status; `reading_from` only uses
a redo's part when redo is primary, so the data repeat disappears. With actual stored full claims,
the equivalent single-redo reading correctly retains both status and data.

Support or explicitly validate the composition of allowed clause types; do not silently discard a
redo beside a status/memory/guidance clause. Test single-redo and compound representations for the
same intent, with and without data, plus explicit one-component selection. Keep current-state
status truthfulness and all tap/consent gates. Adding another isolated “both” wording override
would leave the same class open.

### D. Remaining memory intent miss — preserve the safety gain

`memory_chatonly-01/t2` asks what walking preference was mentioned here. Its first reading copies
the earlier no-save statement into a remember clause; the current provenance guard correctly
rejects that. The retry becomes `other/unsure`, so the recall is still missed. This is one of 16
strict memory-intent/scope cases. Do not remove the guard to regain the answer or write a fact
without permission; improve current-turn recall interpretation and use the available chat context.
Keep the distinction between approved durable facts and chat-only mentions.

## 4. Spend, artifacts and release status

New matched-reader spend: baseline **$0.227755200**, candidate **$0.343948800**, combined
**$0.571704000**, below the $0.75 phase ceiling. This phase is entirely OpenAI reader calls.
Shared-$5 cumulative total: **$2.101757752** (OpenAI $2.044401460; Jev $0.057356292), unresolved
reservations **$0**. Remaining **$2.898242248**. Offline review, replays and tests cost $0.

No fresh conversation release audit or PHIA gate ran on this SHA. The earlier 689 PHIA 23/24
result is historical and must not be attributed to this candidate. No merge or release result.

Private, ignored local records:

- `data/eval/e1_matched/`: frozen cases, source hashes, both raw-reading arms, receipts, final
  constraint grades, date-relation slices and retained grading/claim-history corrections.
- `data/eval/e1c1eec_review/probes.py`: independent replay of the previous repair controls.
- `render_probes.py` and its JSON: real-tool renderer reproductions, including tagged-day
  output that fails a second verifier pass.
- `counterfactuals.py` and its JSON: corrected endpoint/scope/compound representations through
  the unchanged executor, without another provider call.

Repair A is deterministic and should need no paid diagnosis. For B/C, preserve all current gains
and measure generalization against contrasting relation/target/composition cases. Only after these
known failures are repaired should the next frozen candidate receive the fresh paired audit from
the remaining shared allowance. No framework migration or production architecture rewrite is
required to establish these contracts.
