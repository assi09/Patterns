# PR #195: general repairs before the next independent audit

Prepared November 21, 2026 for Claude Code. The reviewed local and remote PR head remains
`b3d64ca33f7da5992890b20dd290c6bace660955`; the PR is open and unmerged. No newer repair commit
was available. This planning pass made no production changes or paid calls.

**Objective:** close failure classes across dates, metrics, wording, data availability and
conversation transitions. Keep working computation and persistence behavior. A larger audit
will measure the result; it cannot substitute for fixing the contracts between interpretation,
execution, final rendering and storage. No finite evaluation can guarantee that every future
question will work, but the known defects below have reproducible boundaries and controls.

## 1. What the audit history establishes

Reviewed the first November 18 audit, the 369-turn v2 validation, v3 and its supplemental probes,
the two independent offline implementation reviews, v4, v5, v6, b730, a196, 922 and b3, together
with the post-922 reader/selector experiments. Historical examples are development material.
The current code and current reproductions determine whether a defect is still open.

| Historical finding | Evidence now | Treatment |
|---|---|---|
| Same-day/range/operation references drift (first audit, v2 onward) | Five wrong scoped follow-ups in b3; `redo` and `other` account for different failures | Open; repair semantic edits and dispatch together |
| Global phrase overrides corrupt another clause (offline v3 reviews, v4) | The old global overrides are gone; correct-plan preservation tests pass | Preserve removal; do not bring global regex rewriting back |
| Strict/inclusive/equality operators, coverage versus threshold counts (first audit through v6) | Dedicated coverage/count execution and tests exist; latest narrow live deck did not retest breadth | Restore broad live coverage; fix only newly reproduced failures |
| Recovery score baseline changes with expert-visible columns (v3) | `_scored` preserves an already computed score; dedicated invariant test passes | Preserve; recheck across all derived scores in broad controls |
| Constant/missing/disjoint associations get the wrong explanation (v2, v3 supplement, v6) | Reason-specific handling and individual/joint coverage exist in `requested.py` | Implemented, broad live confirmation still needed |
| Intake/expenditure swap and stale meal filter (v3 through 922) | b3 original-output replay and 10/10 fresh food-chain turns pass | Keep; expand to nutrients, empty days and mixed requests |
| Confirm/status claims success without stored state; side reads lose citations (v3–v5) | State-bound replies and `side_claims` exist; v6/b730 exercised mixed/state paths successfully | Preserve; restore the full lifecycle and failure tests |
| Date-only workout edit changes pause or anchors to today (a196) | Card patch preserves time/pause; b3 still misreads the signed correction direction | Keep patch; fix interpretation of correction versus reported error |
| Memory intent/listener/forget/approval provenance (v3–v5) | API dispatch/consent gates and confirmed lifecycle exist; v6/b730 passed broader cases; b3 only tests a subset | Preserve; restore replace/cancel/delete/no-save/cross-chat and background checks |
| Scope lost across investigations/coaching/format (v3–922) | b3 retains both windows and explicitly discloses focal-only coaching | Keep gains; address last-turn identity and response constraints below |
| Reopened evidence returns another adjustment family (b730) | a196, 922 and b3 readbacks pass; b3 matches all 288 citation occurrences | Keep immutable versions |
| Duplicate records presented as extra measures (a196) | `render_overview` deduplicates displayed metric/window pairs | Display improved; statistical hypothesis identity is still open |
| Stress-tag association described as a tested wind-down routine (a196) | `permits="watch"` and bound wording now distinguish monitoring from intervention | Preserve; test all levers and unknown exposures |
| Wrong exercise variant / topic / permissive fallback (v2 onward) | b3 16/16 across four families; canonical title reaches actual selector cap; unsafe unmatched fallback removed | Preserve; restore nonexercise, ambiguous, unavailable and multilingual controls |
| Unsupported prose beside valid claims (first audit, v2, v5) | b3 explanation adds an unreported “run down” outcome despite correct comparison claims | Still open; final factual text must have support |
| Out-of-range, low wear, missing data, access/medical/injection boundaries | Repairs and tests exist, but recent focused decks omit substantial coverage | Restore to release audit; do not presume old defects either remain or are solved |

The first audit is `data/eval/independent_audit_2026-11-18/report.md`; v2 is
`data/eval/independent_validation_v2_run_2026-11-18/report.md`. Both remain ignored local records.
Later results are in [v3](independent-audit-v3-handoff.md),
[offline fix review](audit-v3-fix-review.md), [offline live review](audit-v3-live-review.md),
[v4](independent-audit-v4-handoff.md), [v5](independent-audit-v5-handoff.md),
[v6](independent-audit-v6-handoff.md), [b730](independent-audit-b730fda-handoff.md),
[a196](independent-audit-a196c6d-handoff.md), [922](independent-audit-9228fe6-handoff.md),
and [b3](independent-audit-b3d64ca-handoff.md).

## 2. Why successive fixes have not closed the problem

The deterministic executor can express the requested periods. Prior oracle-input checks passed
48/48; the last live deck still failed five date edits. A unit test supplying the intended
structured fields establishes executor behavior, not that the reader extracts those fields.

Four interfaces remain incomplete:

1. The reader can emit a schema-valid **wrong speech act or transformation**. A date-width edit
   becomes formatting; an elliptical metric question becomes `other`; a reported date error
   becomes a move in the wrong direction.
2. **Dispatch can replace a missing interpretation with another investigation.** A typed `other`
   reading still reaches routed personal-data tools. This turns a parsing miss into a confident
   answer about recent steps rather than the original metric/dates.
3. **Conversation state does not identify the complete last answer.** It keeps a surviving data
   slot alongside guidance, and `parts or reads` makes side results disappear from the next
   turn's addressable objects when main parts also exist.
4. **Later rendering and statistical grouping use different identities.** Answer formatting is
   reconstructed from free text and can be overwritten. A record/version ID is also treated as
   a statistical test identity, although multiple records can describe the same computation.

Two current prompt/schema overlaps add avoidable ambiguity: `redo` and `other` both claim
“give three options / label general tips,” while `RedoClause` uses “shorter” without explicitly
separating answer length from data-window length. These conflicts are present in
`requests.PROMPT` and `clauses.OtherClause`, not conjectures about hidden model reasoning.

## 3. Fix order and acceptance invariants

Implement these as focused changes with independent controls. Prefer the existing internal
request-state JSON and a backward-compatible adapter over public API changes, heavy dependencies
or another agent framework. Keep the current statistical/date executors unless a failing
executor property is demonstrated. Any new semantic representation is a candidate to measure,
not an assumed improvement.

### A. Capture the first wrong decision before further reader tuning

**Files:** `agent/requests.py::interpret`, `outline`, the synthetic audit harness.

Wire `keep_readings=True` into the isolated synthetic harness, not ordinary production tracing.
Retain first and retry raw clauses, accepted request, reference object, transformation fields,
executed tool arguments, returned evidence, final response constraints and stored state. Include
which authority supplied each field: current message, clock, prior result or pending card.
Production-safe diagnostics may retain enum/flag/count information; do not log personal text,
health values, raw arguments or credentials.

A reduced `beside/previous` outline cannot tell whether a wrong interval came from landmark,
offset, boundary or width. Do not infer those fields after the fact. Record enough to replay
one stage at a time. Keep the first failed reading even when a retry succeeds.

**Exit check:** inject a wrong boundary, wrong request kind and wrong correction sign separately;
each trace identifies the first mismatch and reproduces it without another provider call.

### B. Make interpretation authoritative, with distinct query and response changes

**Files:** `agent/clauses.py`, `requests.py::PROMPT`, `resolve`, `_redo`, `ask.py` dispatch.

Use three separate concepts within the current reader contract:

- **Referent:** a prior data result/comparison, guidance answer, action card, memory object, or a
  genuinely new request. A whole comparison is one referent; editing one side selects that side.
- **Query/action changes:** metric/source, statistic/comparator, dates, meal filter, draft fields.
  Unchanged fields stay inherited only from the selected object; explicit new fields win.
- **Response changes:** number of points, brevity, units, personal/general allowance and labels.
  They do not silently change the query. A message can contain both kinds of change.

Remove contradictory clause descriptions. In particular, “shorten the answer” and “shorten the
interval” need different accepted plans. Preserve mixed-clause handling and allow explicit new
questions even while an old result/card is active. A supporting quote records extraction
provenance; it does not by itself prove that the meaning was correctly interpreted.

For a **typed `other` result**, do not start a fresh personal-data investigation or choose default
metrics/windows. Known small talk can receive its normal acknowledgement. An unresolved request
can receive one concrete clarification tied to the available objects. A genuine new broad
investigation remains available through its own typed path. This closes a deterministic escape
route; a clarification on an otherwise clear edit is still a quality miss, not a successful fix.

**Current failures:** b3 `time_in_bed-02/t2` becomes redo and retains seven days instead of three;
`checkin_rating-02/t2` and `sleep_minutes-02/t2` become other and answer recent unrelated days.

**Controls:** answer length versus window length; same data in another unit versus a different
statistic; a four-day block versus a whole-range shift; real small talk; a newly named metric;
a new broad question; a mixed formatting-plus-date edit. Vary dates, widths and phrasing rather
than matching one quotation.

### C. Keep calendar arithmetic in code; measure semantic date extraction

**Files:** `clauses.FromEarlier`, `period_of`, `requests.period_window`, `api/chat.card_edit`.

The semantic decision is which object/edge the person means, what moves, and which new endpoint
or width is specified. Code should then calculate concrete endpoints exactly once. Reuse the
same resolved window in execution, evidence, rendering and state. Distinguish whole-result reuse,
whole-window translation, leading/trailing blocks, endpoint-preserving resize, and a clock-based
new period. Validate the consistency of any extracted constraints; a correctly sized interval
can still be on the wrong side of the landmark.

For cards, distinguish **an instruction to move a date** from **a report that its recorded date
is wrong**. A recorded date two days too early requires a move later; an instruction to move two
days earlier requires a move earlier. If a small explicit relation type makes that distinction
clearer, let code derive the signed repair. Treat it as an experiment: the existing direct signed
offset already fits the intended correction, and another schema is not proven better.

Keep the working card patch, revision/ownership checks, local-date handling and independent
active/elapsed/pause fields. Untargeted fields must remain unchanged. Preserve genuine duration
edits and reject or clarify active-versus-elapsed conflicts.

**Current failures:** both HRV wordings in b3 resolve wrong windows; the first paused correction
has `card_day_offset=-2` instead of +2. Correct-window and corrected-sign executor controls pass.

**Required development comparison:** replay the same exposed language inputs through baseline
and proposed reader, scoring speech act, referent, landmark, direction, boundary, width, final
endpoints, unwanted field edits and clarifications separately. Randomize clock/old window/width,
include leap/year/DST boundaries, and include new-topic controls. Keep correct readings spoiled
by retries in the result. Use the current small model first. The previous stronger reader tied
18/24, fixing three and breaking three; endpoint and calendar-table probes were worse. Do not
repeat those changes without new matched evidence. The reasoning-effort HTTP 400 is not a model
quality result. Additional verification calls must earn their cost and avoid rejecting good plans.

### D. Persist complete addressable context and coalesce only equivalent operations

**Files:** `requests.interpret`, `earlier_results`, `_redo`, `_prior`,
`clauses._every_metric_looked_into`.

Give the last turn a typed identity and preserve every main and side result with its scope,
source and operation. Track completion/availability so a requested-but-unavailable period is
not confused with a computed statistic or an older successful result. Preserve explicit old
references across topic changes, but bind an unqualified “that answer again” to the actual last
answer. Support legacy state. Resolve objects account-locally, with card revision where relevant.

New scripted reproduction in this planning pass: an investigation plus a steps mean has both
parts in the resolved request, but `answered = request.parts or request.reads` saves only the
investigation. The side mean is absent from `earlier_results` on the next turn. The old
selected-earlier-part failure family therefore needs more than a nicer reader prompt.

Coalescing must consider operation, metric set, source, reference identity and **resolved ordered
scope**, not equality of raw span objects alone. Two `same_as_earlier` spans pointing to different
results are not equivalent. A different-window all-registry side comparison must execute without
requiring a previous metric. An omitted metric meaning “all available measures” must stay
separate from an omitted metric meaning “inherit the selected result.”

**Controls:** same/different referent; same/different windows; named and whole-registry side reads;
main+side answer followed by selection of either; guidance after data then redo; data after
guidance then explicit older reference; failed/insufficient prior result; summary folding;
explicit topic switch. Ensure every requested result survives delivery and reopening.

### E. Separate statistical hypothesis identity from evidence/version identity

**Files:** `agent/agent.py::_handle` family assembly, `verifier.run_adjusted`,
`findings.render_overview`, evidence provenance.

The a196 issue was partly a display count, but the statistical grouping remains unresolved.
In b3's stored why turns there are 38–39 overview comparison records for 32 distinct metric/window
computations. Current family assembly deduplicates by evidence ID. Evidence IDs can be random
or versioned, so an identical retest can enter twice.

A new deterministic synthetic control demonstrates the consequence: two hypotheses with raw
p-values 0.03 and 0.07 give the first an adjusted value of 0.06. Add an identical copy of the
first under another record ID: current `run_adjusted` reports three tests and gives it 0.045.
The same information now crosses the code's significance cutoff.

Define a hypothesis key from the actual test definition: tool/method, metric(s), ordered scope,
source/data revision, comparator/lag and other analysis parameters. Deduplicate an exact retest
within a family before adjustment. Keep distinct tests of the same metric. Specify the raw or
previously adjusted p-value convention explicitly at family construction; do not silently mix
records from incompatible adjustment families. Preserve immutable evidence versions and the
family provenance required to reopen each answer as originally judged.

**Controls:** exact repeat with a new ID; same evidence in a new adjustment family; changed data
revision; different lag/method/windows on one metric; order invariance; repeated submission;
32 metrics/39 records. Duplicating or reordering one identical hypothesis must not change its
verdict. A genuinely new hypothesis may change the adjustment. Use multi-seed property tests for
error rate/coverage where statistical behavior is changed, alongside deterministic identity tests.

### F. Exclude unknown exposures before testing habits

**File:** `analysis/coaching.py::_tests`, `_split`, habit evidence coverage.

New deterministic finding from restoring the missing-data review: a bedtime comparison has
20 known sleep outcomes but only ten known bedtimes. The known early and late groups have equal
sleep values. Ten missing bedtimes have different sleep outcomes. `bed <= median` produces false
for missing bedtimes, and `_split` assigns every false row to the other group. The tool reports
5 early / 15 late and supports an earlier-bedtime option. Filtering to known bedtimes gives
5/5 and no support. A genuine known early/late difference remains supported in the control.

Unknown exposure is neither a measured “yes” nor a measured “no.” Align outcome and exposure,
exclude unknown pairs before group assignment, and use explicit positive and negative masks.
Review bedtime regularity, activity, shifted strain and tag levers with the same invariant.
Record individual coverage, paired coverage and group counts so insufficiency can be explained.
Do not fix this by rewording the recommendation: the grouping itself is wrong.

**Controls:** unknown outcomes versus unknown drivers; identical known groups plus differently
valued unknown rows; genuine known difference; shifted exposure gaps; constant exposure;
insufficient groups. Adding rows with unknown exposure must not alter a known-pair result.
Preserve actual zero measurements and recorded false tags.

### G. Assemble the final answer once, with retained response constraints

**Files:** `requests.Request`, `_redo`, `ask._fill_points`, `coaching_by_code`,
`one_coaching_conclusion`, `agent._handle`, `api/chat` assembly.

Persist requested point count, personal-only/general-allowed constraints, units and scope through
resolution. Build eligible blocks: computed observations; an evidence-bound personal option or
scoped limit; separately sourced general guidance; truthful action/memory status and side reads.
Render once after eligibility/guards. Every personal factual sentence must come from a verified
claim or deterministic evidence-bound block; final summary/notes cannot introduce an unreported
symptom or another outcome merely because their other claims are valid.

Currently `RedoClause.options` is only a truthiness switch in `_redo`; count is not a durable
response constraint. `_fill_points` can add valid general guidance, then
`one_coaching_conclusion` removes it while rebuilding a one-option answer. The last audit's
“up to three if supported” cases passed because they honestly reported no supported personal
habit. That is not evidence this rendering path handles a requested mixture of options.

**Controls:** exactly three supported blocks; one personal plus two general; fewer qualifying
blocks with an explanation; no qualifying personal option but general allowed; personal-only;
guard rejects one passage; unsupported subjective prose beside valid comparison claims; rejected
claims and tool exhaustion; mixed action/status/read. Inspect the complete delivered API text,
citations and reopened state, not just the submitted summary or `ask()` result.

## 4. What to preserve and what not to do

Keep deterministic analysis/date arithmetic, one source per series, the original acceptance
gates, immutable evidence versions, state-bound confirmation/status, confirmed memory actions,
meal execution/filter removal, guarded routine/variant retrieval, and measured-action versus
watch-only coaching semantics. The current small reader stays the baseline.

Avoid global phrase overrides, new default metrics to rescue unresolved clauses, silently using
recent dates, dropping genuine side reads, counting records as hypotheses, or relaxing tests to
fit a new implementation. Avoid another universal checker/model upgrade on intuition. Removing
all state or locking every future guidance turn to one old passage would break valid topic
changes. Keep old failure artifacts unchanged and write new replay receipts separately.

## 5. Development gate before the expensive release run

1. Land the deterministic dispatch/state/deduplication/grouping/rendering repairs with close
   positive and negative controls. Replay captured valid/wrong intermediate plans to identify
   precisely what each fix enforces. An executor replay is not a language pass.
2. Reconcile PROMPT, class descriptions and actual supported fields, then make the smallest
   measured reader change. Use the same historical language slice for baseline and candidate.
   Include ordinary unaffected wording and explicit new-topic controls. Preserve all attempts.
3. Require the normal backend checks, relevant mobile/contract checks, and API/store/reopen
   proofs. Document remaining unknowns. The last full suite was 2,498/2,498; this planning pass
   also reran 417 historical regression checks, all passing despite the uncovered invariants.
4. Freeze one candidate SHA and hand it to Codex. Codex freezes genuinely unseen language,
   profiles, keys and grading before any release call. Once graded, that deck is development
   material. A failed family gets a causal diagnosis and another candidate, not repeated runs
   until one output happens to pass.

Local $0 reproductions from this pass:

```bash
.venv/bin/python data/eval/pr195_plan_review/state_probe.py
.venv/bin/python data/eval/pr195_plan_review/hypothesis_probe.py
.venv/bin/python data/eval/pr195_plan_review/missing_exposure_probe.py
.venv/bin/python data/eval/b3_audit_code/offline_review.py
.venv/bin/python data/eval/b3_audit_code/replay_live_failures.py
```

The first three write new diagnostic receipts under ignored `data/eval/pr195_plan_review/`.
They are synthetic deterministic controls, not new live release results. The b3 scripts reproduce
the last audit's live and offline findings. Do not execute the old paid runners for diagnosis.

## 6. Next audit: restore breadth and keep every area visible

Provisional coverage **about 608 fresh turns**, plus the separate 24-item B1 gate. Final counts
and expected cost are fixed before execution; explicit prompts remain unseen by the implementer.
Counts below are planning allocations, not a frozen deck or promised result.

| Area | Planned turns | Required distinctions |
|---|---:|---|
| All 34 daily metrics | 136 | Two wordings, cold opening plus follow-up; source/score/zone identity and units |
| Additional dates and references | 48 | Day/night/calendar/complete days, width versus shift, first/last/selected part, two windows, leap/year/DST, intervening topics |
| Thresholds and units | 30 | `> >= < <= ==`, negation, equality ties, changed threshold, count versus value/coverage, hours/minutes |
| Multipart and mixed operations | 36 | Different dates/metrics, chosen main/side result, read+draft/status/memory, either clause order, partial failure |
| Associations and causal limits | 48 | Positive/negative/null, constant, missing, disjoint, same/next-day lags, derived/part-whole relationships, causal questions |
| Coverage and data quality | 28 | Empty/sparse, zeros versus missing, one absent metric, missing baseline, low wear, unknown exposures, five-plus metric coverage |
| Investigations and coaching | 48 | Planted changes/flat/confounded, short/out-of-range blocks, explanations versus monitoring/actions, multiple supported/general options |
| Complete memory workflows | 36 | Propose/approve/recall/replace/forget/cancel/confirm, chat-only/no-save, cross-chat, no unsolicited candidates after background work |
| Workout/action lifecycle | 40 | Walk/run/bike, supplied/missing fields, active/elapsed/pause, real duration/date edits, too early/late, no card, stale/repeated correction, status, confirmation safety |
| Food and source changes | 30 | Meal/nutrient/date, clear filter, intake/expenditure, multiple dates, draft exclusion, unknown values, empty day, mixed logging/read |
| Guidance and retrieval | 40 | More movement families, setup/lowering/breathing, variant change/continuity, ambiguous referent, absent detail, failed selector, nonexercise routines |
| Safety, ownership and source boundaries | 32 | Own versus another person's records, mentioned partner, no-save, injection/evidence fabrication, source separation, fixed medical/urgent boundaries |
| Failures and recovery | 16 | Reader/guard/provider/tool/budget/persistence failures, bounded retries, truthful partial result, immutable earlier evidence |
| Multilingual questions | 16 | Arabic/French plus English controls for data/reference/guidance; score separately |
| Longer conversations | 24 | Topic interruption, older result selection, state after summary folding, correction recovery and cancelled actions |
| **Fresh total** | **608** | Paired wording wherever practical; varied profiles and dates |

Some cases test several boundaries; each turn gets one declared primary cohort, and secondary
checks are reported without double-counting denominators. A repeated template over 34 metrics
measures breadth, not 34 independent wording styles. Add non-template paraphrases in each weak
family. Retest exact requested source rows even when two windows happen to give the same value.
Use synthetic profiles for fresh conversations; keep public B1 values private. Simulate external
write/failure behavior locally; no real Google writes are authorized.

Keep the existing zero-event and area gates in
[acceptance-structured-requests.md](acceptance-structured-requests.md). Report full/partial/fail,
paired-wording consistency, independent versus cascading failures, unnecessary clarifications,
scope/source swaps, state truth, reopened citations, and costs **by area and key subtype**.
Report broad regression coverage and the targeted weak slice separately. An unrun/budget-blocked
case is unmeasured, never a pass. No overall percentage overrides a failed zero-scope gate.

## 7. New budget: $5 across the next audits

The user authorized a **new forward-looking maximum of $5 total**, across subsequent audits,
not $5 per run. Start its ledger at $0 for this planning pass. Do not add the old approximately
$0.526 remainder on top; retain previous receipts/reservations unchanged and separate.

| Allocation | Ceiling |
|---|---:|
| Matched reader/development diagnosis, only when needed | $0.75 |
| Broad fresh conversation audit | $3.50 |
| Frozen PHIA B1 regression gate | $0.25 |
| Uncertain calls / targeted fresh confirmation reserve | $0.50 |
| **Combined maximum** | **$5.00** |

These are ceilings, not spending targets. Use one shared meter across completions, embeddings,
web and Jev, including retries/background work and unresolved reservations. Price the final deck
before launching; if it cannot fit, agree the frozen reduced coverage before calls rather than
quietly dropping expensive or failing types afterward. Reserve capacity for each required family
and PHIA. A later confirmation deck must use remaining money, not a renewed $5 allowance.
No paid judge or full PHIA B2/A3 rerun is planned. Claude's unrelated paid implementation tests
must not silently consume or bypass this shared allocation.

**Requested handoff from Claude:** the new candidate SHA; the invariant each commit enforces;
passing counterexamples and general controls; matched reader results if run, including regressions;
source/state compatibility; full verification; costs and unresolved reservations. Do not describe
scripted decoder/executor tests as a live generalization result. Keep the PR unmerged for Codex's
independent frozen audit.
