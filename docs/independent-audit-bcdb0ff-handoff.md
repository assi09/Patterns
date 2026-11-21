# Independent review of bcdb0ff — November 22, 2026

**HOLD PR #195.** The fresh matched comparison improves 138/152 → 146/152, including 7/12 → 12/12 successor blocks. Coaching rendering, compound dispatch and duplicate state still fail independent controls; semantic reader misses remain. No fresh release audit ran.

Frozen candidate: `bcdb0ffb205effdc4e3145d89400a0454eab2482`; baseline reader:
`e1c1eec0535c013b103ad33088bf41492ef24f1c`. GitHub independently confirms the frozen
head, open/unmerged state, and successful required backend/mobile checks. No production code
changes, commits, pushes, merges, deployment, real-health inputs or Google traffic/writes.
The two pre-existing untracked handoffs remain untouched.

## Findings for Claude Code

### 1. The renderer repair does not reach coaching observations

**P1 — `backend/app/agent/ask.py:946–958`, `one_coaching_conclusion` and final investigation assembly.**

`code_claim` now correctly dispatches by record type, but `said_observations` still routes every
record containing `difference` through the old window-only `finding_claim`. Investigation
coaching calls `one_coaching_conclusion`, which calls this old renderer. With actual sufficient
change-point, weekday-split and tag-effect records, and input claims accepted by the verifier,
that production assembly still emits **“Steps went up:  against .”**. The generated tag claim
also fails verification again because its kind changes to `change`.

This is the same underlying renderer-coverage issue in a second output path, not a new reader
mistake. The successful explanation probes do not cover coaching's final assembly.

**General repair:** use one typed, record-aware renderer for every observation that can reach a
reply. Remove the independent `difference`-key dispatch from coaching. Skip records that cannot
be stated, preserve an honest omission note, and keep observations separate from habit options.
Check all seven real tool record types through both explanation and coaching assembly, including
missing figures, insufficient data and rejected unsupported personal assertions. Reverify the
claims that final assembly actually publishes. Preserve correct comparison figures, option counts,
and unsupported-commute/outcome controls.

Private reproduction: `data/eval/bcdb_review/coaching_render_probe.py` and its JSON output;
no provider requests.

### 2. Compound repeats flatten an overview into an executor that cannot render it

**P1 — `backend/app/agent/requests.py:721–723`, `backend/app/agent/ask.py:752–767`.**

The new compound-repeat resolver obtains the repeated request correctly, then retains only its
parts in `request.reads`. This discards its investigation kind and focus. `_with_reads` forces
those parts into the precise-data executor. An overview is represented by `metrics=[]`,
`operation=describe`, two preserved periods; the precise executor iterates no metrics and emits
no statement or evidence.

Independent end-to-end `ask` reproduction, entirely offline: an earlier whole-registry comparison
followed by “Repeat that all-measure comparison. Also tell me whether the entry is saved.”
returns only the entry status, with **zero notes and zero claims**. The same correctly formed
repeat beside plank guidance also produces an empty side result. A precise steps mean beside
the identical status clause retains its numeric note and one inspectable claim.

**General repair:** preserve the semantic kind, scope, focus and presentation settings of each
repeated component through composition and dispatch each through the executor that implements
it. A list of precise `ResolvedPart`s is insufficient for arbitrary repeated investigations,
coaching or guidance. If a combination is unsupported, ask clearly rather than silently dropping
it. Add final-answer tests for overview + status/recall/guidance, alongside the existing precise
read + status case and repeat-alone control. Preserve no-write status behavior and the guard
against replaying unrelated stale results.

Private reproductions: `data/eval/bcdb_review/independent_probes.py` and JSON output.

### 3. Equivalent clauses are stored twice and create false ambiguity next turn

**P2 — `backend/app/agent/requests.py:721–723` and `1456–1476`.**

The candidate live reading for `investigate_lowwear-02/t4` emits both a redo and an investigation
for the same three-option follow-up. The main investigation correctly retains its periods,
coaching focus and count. The new compound path adds the identical broad part to `reads`,
because it deduplicates against reads only, not main parts. Both identical results are saved in
`data`, with answer counts of one main plus one side result.

Independent continuation using that actual candidate state: a correctly scripted “Why did those
changes happen?” with `same_as_earlier` gets “Which earlier measurement or period do you mean?”
because `_prior` sees two entries. With only the duplicate removed, the same continuation
resolves to the original two periods. This is a persistence defect, even though the immediate
formatting answer may still show the right coaching count and dates.

**General repair:** canonicalize equivalent resolved components before execution and persistence,
including main-versus-side equivalence; calculate stored answer counts after normalization. Keep
truly different metrics, periods and goals separate. Do not globally relax ambiguity checks:
those are needed for genuinely distinct results. Test immediate output and one more turn.
Private reproduction: `data/eval/bcdb_review/duplicate_scope_probe.py` and JSON output.

## Offline repairs and controls

The explanation path now correctly states actual change-point, weekday-split and tag-effect
records, with complete figures and appropriate group wording; their generated claims pass the
verifier again. The prior malformed explanation output is repaired in that path.

An independent deterministic sweep passes 276 block-before/block-after/whole-shift boundary
checks spanning leap days, year boundaries, one-day and wider periods, several lengths and
positive/negative offsets. Twelve two-period controls retain the single-period ambiguity guard.
These check date arithmetic given correct semantic fields; they do not establish model selection
of those fields. Existing offline legacy/grounding/count/correction controls were also replayed
into new output files.

## Matched-reader comparison

Both arms use the same 152 exposed synthetic inputs, same order, dates, states and card fields.
The original twelve incomplete claim attachments are replaced up front with the actual complete
stored synthetic claims in both arms. The expected whole-history representation is accepted up
front. No output-dependent fixture or scorer changes are planned.

Input SHA-256: `04c807d8eee447f2ef9228082e2122ad4c2da83667cfdb45d01ef45e58f56980`.
Freeze, baseline source archive, runner hash and raw outputs are under
`data/eval/bcdb_matched`; scripts under `data/eval/bcdb_review`.

This measures exposed development request constraints, not held-out answer accuracy. It does
not measure final assembly, execution, retrieval or full sequential conversation reliability.
Read-back and provider retries are off; interpretation retries are retained. Both arms are run
fresh, once per input, with no paid judge. Combined phase ceiling: $0.75 under the existing shared
$5 authorization, starting at $2.101757752 cumulative usage.

## Artifact provenance

All prior available audit artifacts were hashed before this review's scripts ran. New scripts
write only new output locations. Claude reported that its earlier run overwrote the original
`e1c1eec_review/render_probes.json`; the original file is unavailable. The old committed handoff
and the captured audit description retain the original three malformed outputs. The currently
present old JSON is a later repair replay and must not be represented as the original evidence.
The new reproduction files above independently establish the current behavior. A separate
`reconstructed_e1_render_probes.json`, regenerated from the archived e1 source, independently
reproduces all three historical failures. It is labelled a reconstruction, not the lost original.
All 255 prior available artifacts retained identical hashes through this review.

## Verification

Independent local backend verification: `ruff check .` and `ruff format --check .` pass;
**2,685 tests pass in 312.24 seconds**. No backend tests called paid APIs. The full suite includes
the 50 new repair tests; those are not additional live reader cases. No mobile source changed;
required mobile CI is independently confirmed green.

## Completed matched results

All 304 arm/input executions completed, with 324 provider completions (166 baseline, 158
candidate, including interpretation retries). No provider failure, cap block or unresolved
reservation occurred. Candidate clauses always reached a resolved request; that includes the
semantically wrong ones. One baseline request ended in ambiguity. No case was rerun or excluded.

| Reader slice | Baseline | Candidate | Improved | Spoiled |
|---|---:|---:|---:|---:|
| metric_date | 59/68 | 66/68 | 7 | 0 |
| format | 12/12 | 11/12 | 0 | 1 |
| calendar_date | 23/24 | 23/24 | 1 | 1 |
| french_operation | 2/2 | 2/2 | 0 | 0 |
| threshold | 10/10 | 10/10 | 0 | 0 |
| return_after_guidance | 4/4 | 4/4 | 0 | 0 |
| memory | 15/16 | 15/16 | 0 | 0 |
| status_and_data | 1/2 | 2/2 | 1 | 0 |
| workout_edit | 8/8 | 7/8 | 0 | 1 |
| main_after_side | 0/2 | 2/2 | 2 | 0 |
| lag | 2/2 | 2/2 | 0 | 0 |
| new_duration_basis | 2/2 | 2/2 | 0 | 0 |
| Common-field total | 136/150 | 144/150 | 11 | 3 |

Including the two duration-basis cases, the result is **138/152 → 146/152**. On the common 150
fields: 133 pass both, 11 improve, three spoil and three fail both. These are paired development
observations, not a claim that all gains are caused by the schema or that failures are gone.
The same old reader previously scored 135/152 and now scores 138/152; one completion per input
cannot establish a stable probability or a permanent fix.

| Metric date relation | e1 baseline | bcdb candidate |
|---|---:|---:|
| Three days ending on the earlier first day | 10/12 | 10/12 |
| Five days immediately before | 9/10 | 10/10 |
| Four days starting on the earlier second day | 10/10 | 10/10 |
| Four days after the earlier last day | 7/12 | 12/12 |
| Translate the entire interval two days earlier | 12/12 | 12/12 |
| Keep the final two days | 11/12 | 12/12 |

The new successor kinds help on this run without spoiling the other metric relation categories.
Two explicit whole-registry returns now pass, as do both status/data repeats. The previously
flagged chat-only recall and explicit return to steps both pass in both freshly sampled arms;
that does not prove those historical misses are permanently fixed.

### Every candidate miss, including the three spoiled checks

1. **`metric_strain-02/t2`: wrong dates.** “Make the opening date the closing date of a three-day
   block” becomes one day at the old *last* day. The first reading placed both endpoints there
   with length three; code rejected the conflict; retry removed length and accepted one day.
2. **`metric_respiratory_rate-02/t2`: wrong width.** The same request becomes one day at the old
   first day. Again, the retry fixes structural consistency by dropping the explicit length.
3. **`memory_cancel-02/t3`: wrong intent.** “Ask me to confirm removing that walking preference”
   initially copies prior removal/status clauses into the current reading. The provenance guard
   correctly rejects that; retry classifies the current request as `outside_the_app` and resolves
   `other`, instead of a pending forget request. Keep the provenance and confirmation guards.
4. **`workout_midnight-02/t2`: strict field mismatch; action-equivalent control passes.** The
   candidate restates the existing 30 active minutes and zero pause instead of leaving duration
   null. The frozen predicate therefore fails it. Independently passing that request through
   actual `card_edit` gives `active_minutes=None`, `elapsed_minutes=None`, and the correct prior
   day: clock times remain unchanged. This is **not evidence of an actual workout-duration
   regression**. The predeclared strict score is retained, with this practical qualification.
5. **`investigate_lowwear-02/t4`: duplicate scope.** Count, focus and dates are correct, but the
   extra identical side part fails the no-side constraint and causes the independently reproduced
   false ambiguity on the next turn (§3). This is not merely an alternative harmless encoding.
6. **`date_history-02/t2`: explicit history override lost.** “Drop the window and calculate over
   all my available history” is read as `same_as_earlier`, preserving the old seven-day range.
   Baseline passes; candidate fails. This is a real scope regression, not the previously corrected
   `history=true, windows=[]` scorer issue: candidate has `history=false` and the old window.

### Next reader repair: preserve meaning through retries, then measure controls

The remaining common cause is accepting a coherent plan that has lost a current-message
requirement. Validate three distinct things: provenance from the current message, internal
consistency, and coverage of the explicit requested edits. A retry must repair the conflicting
placement without silently deleting the user-stated count. A whole-history override must replace
inherited periods; a current request about forgetting remains a memory action even when copied
history clauses are removed.

Use structured semantic roles and explicit edit-versus-inherit fields, with provenance for the
constraints being preserved. Do not indiscriminately freeze every field from a wrong first
reading, and do not remove the old-message guard. Where intent still cannot be resolved, ask a
relevant question instead of executing a narrower accepted plan. Measure this change as an
experiment, with paraphrases and contrasting keep-same-days/new-period/history controls.

## Repair and validation order

1. Unify all final observation rendering, including coaching (§1), and verify published claims.
2. Preserve typed component meaning through composition (§2), then normalize equivalent results
   before execution and storage (§3). Test a further turn and retain real ambiguity controls.
3. Repair retry coverage, explicit history overrides and memory intent as general interpretation
   invariants; measure against the same anchored/ending/trailing/calendar and memory controls.
4. Only after these deterministic and development gates pass, freeze fresh unseen conversations
   for a broad final-answer audit. Preserve the restored question families; do not spend the
   remaining allowance repeatedly measuring already-known deterministic failures. Keep PHIA
   separate and capped. No full release result exists for this SHA.

## Spend and remaining allowance

Baseline **$0.339550950** + candidate **$0.272442000** = **$0.611992950**, below the combined
$0.75 phase ceiling. All new spend was OpenAI reader completions; no paid judge, embeddings,
external retrieval, PHIA or Google calls. Offline reviews/probes/tests cost $0.

Shared $5 cumulative usage: **$2.713750702** (OpenAI $2.656394410, Jev $0.057356292), with
**$0 unresolved reservations**; **$2.286249298 remains**. Receipts and complete raw attempts are
retained locally. Production code remains unchanged; the PR remains unmerged.
