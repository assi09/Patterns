# Agent audit after Claude's PHIA repair — completed local handoff

Tested candidate **`fa15f4a82ba27c0032738b1f2cc04a69ba4fde3f`**, Claude's PR **#195** head, on November 19, 2026.
**All 463 main turns and 25 additional diagnostic turns were executed once and directly reviewed.**
The combined metered upper cost is **$0.910415**, within Karim's separate **$2** allowance.
This file supersedes the earlier preparation/blocked-launch handoff.

## Results

| Cohort | Turns | Pass | Partial | Fail | Strict pass rate |
|---|---:|---:|---:|---:|---:|
| Fresh main cases | 347 | 283 | 11 | 53 | 81.6% |
| Exposed regressions | 116 | 71 | 14 | 31 | 61.2% |
| Main total (mixed cohorts) | 463 | 354 | 25 | 84 | 76.5% |
| Additional diagnostic probes | 25 | 6 | 7 | 12 | 24.0% |

Strict pass means the displayed answer answers the actual question correctly, with the right
metric/source, dates, operation/comparison, units, evidence and required local state behavior.
Correct computations that answer a different question do not pass. Partial means useful or safe
behavior remains but a requested part, context, source variation, or displayed message is incomplete.
Failures include wrong metrics/periods, false unavailable responses, unsupported success claims and
unnecessary clarification of a clear request. These are direct assistant judgments, not blind human
ratings or paid-judge scores; complete outputs and reasons are preserved for regrading.

The main fresh set was frozen before execution. The exposed regression set is development material.
The 25 extra probes were written before their own run, after main review had begun, to cover gaps;
report them as diagnostic, separately from the main fresh score. The overall mixed-cohort percentage
is descriptive and must not be presented as a clean held-out accuracy estimate.

## Did it improve?

On the **same 116 historical turns**, earlier adjudications had **68 pass,
13 partial and 35 fail**. This candidate has
**71 pass, 14 partial and 31 fail**.
Paired ordinal outcomes: **31 improved, 26 worse,
59 unchanged**. Full matched IDs are in the private summary.

That is modest net improvement on this selection, with both gains and regressions. It is not valid
to compare this fresh-set percentage directly with the previous 369-turn audit's 54.5%: the mixes
are different. This is not a new official PHIA A1/A2 benchmark run. Prior PHIA results are separate
reported evidence. Code attribution is limited: this run tests the whole candidate, not a controlled
ablation of Claude's final date fix versus each earlier change. Models are stochastic, turns cluster
within conversations, and prior/current manual rubrics can differ at the margins.

## Fresh coverage and scores

| Area | Turns | Pass | Partial | Fail | Strict pass rate |
|---|---:|---:|---:|---:|---:|
| Cold yesterday, all 34 metrics | 34 | 33 | 0 | 1 | 97.1% |
| Cold last 7 days, all 34 metrics | 34 | 34 | 0 | 0 | 100.0% |
| Mean → median → shifted window, all 34 metrics | 102 | 98 | 0 | 4 | 96.1% |
| Calendar conventions and boundaries | 30 | 26 | 0 | 4 | 86.7% |
| Strict/inclusive/equality thresholds | 15 | 15 | 0 | 0 | 100.0% |
| Multiple metrics and operations | 12 | 12 | 0 | 0 | 100.0% |
| Broad overview / why / coaching | 16 | 5 | 0 | 11 | 31.2% |
| Associations and their follow-ups | 12 | 6 | 2 | 4 | 50.0% |
| RAG and ambiguity | 21 | 13 | 2 | 6 | 61.9% |
| Workout drafts, corrections and confirmation | 15 | 2 | 4 | 9 | 13.3% |
| Confirmed food readback and drafting | 8 | 5 | 0 | 3 | 62.5% |
| Memory lifecycle and privacy | 8 | 2 | 0 | 6 | 25.0% |
| Missing, empty and real zero readings | 12 | 8 | 0 | 4 | 66.7% |
| Access, invalid dates and injection | 7 | 5 | 2 | 0 | 71.4% |
| Multilingual metrics | 3 | 2 | 0 | 1 | 66.7% |
| Unresolved reference | 2 | 1 | 1 | 0 | 50.0% |
| Four public real histories | 16 | 16 | 0 | 0 | 100.0% |

The 34-metric sweep contains five questions per metric: a cold yesterday value, a cold seven-day
average, an explicit eight-day average, its median, then the median after shifting the entire range
two days earlier. This is a deliberate component sweep using repeated question templates; 170
turns are not 170 independent natural-language formulations.

| Metric | Cold yesterday | Cold last 7 days | Explicit-window chain passes / 3 |
|---|---|---|---:|
| `steps` | pass | pass | 3 |
| `calories` | pass | pass | 3 |
| `distance_km` | pass | pass | 3 |
| `active_zone_minutes` | pass | pass | 3 |
| `cardio_load` | pass | pass | 3 |
| `resting_hr` | pass | pass | 3 |
| `hrv_ms` | pass | pass | 3 |
| `respiratory_rate` | pass | pass | 3 |
| `readiness` | pass | pass | 3 |
| `skin_temp_variation_c` | pass | pass | 3 |
| `sedentary_minutes` | pass | pass | 3 |
| `lightly_active_minutes` | pass | pass | 3 |
| `moderately_active_minutes` | pass | pass | 3 |
| `very_active_minutes` | pass | pass | 3 |
| `wear_minutes` | pass | pass | 3 |
| `sleep_minutes` | pass | pass | 3 |
| `time_in_bed` | pass | pass | 3 |
| `sleep_efficiency` | pass | pass | 3 |
| `sleep_score` | pass | pass | 3 |
| `deep_sleep_minutes` | pass | pass | 3 |
| `light_sleep_minutes` | pass | pass | 3 |
| `rem_sleep_minutes` | pass | pass | 3 |
| `awake_in_bed_minutes` | pass | pass | 3 |
| `bedtime_hour` | pass | pass | 3 |
| `recovery_score` | pass | pass | 2 |
| `strain` | pass | pass | 3 |
| `stress_score` | pass | pass | 0 |
| `hr_zone_light_minutes` | pass | pass | 3 |
| `hr_zone_moderate_minutes` | pass | pass | 3 |
| `hr_zone_vigorous_minutes` | fail | pass | 3 |
| `hr_zone_peak_minutes` | pass | pass | 3 |
| `still_minutes` | pass | pass | 3 |
| `still_hr_above_resting` | pass | pass | 3 |
| `checkin_rating` | pass | pass | 3 |

Across the full main pack, by turn index (which is not a pure measure of semantic follow-ups):

| Position | Turns | Pass | Partial | Fail | Strict pass rate |
|---|---:|---:|---:|---:|---:|
| First turn | 183 | 159 | 7 | 17 | 86.9% |
| Subsequent turn | 280 | 195 | 18 | 67 | 69.6% |

## What was inspected independently

The main pack has **183 conversations**, including all **34 daily metrics**, four public histories
(two PMData and two LifeSnaps), and newly seeded synthetic complete, quiet, sparse, boundary,
leap-year, year-transition, low-wear, empty and shared-trend histories. Public histories are tested
separately, without participant-level values in this public-safe handoff. The user's private linked
Fitbit account was not queried. Synthetic ground truth allows exact boundary and planted-effect
checks; public canonical frames exercise actual gaps and uneven coverage.

Before paid execution, questions, profiles, independent pandas/SciPy answer keys, knowledge passages
and harness source were SHA-256-frozen. Every final reply was read against those inputs and the
actual requested dates/metric/operation, not merely checked for a matching number. Per-turn frames,
all accepted/rejected evidence, claims, traces, action/memory state and costs were captured.

The real local `/chat` API was exercised with `store.get_data` overridden to deliver a canonical
frame per account. The same rows were seeded in isolated SQLite for local state/context. This tests
selection and computation over the delivered history plus real local confirmed-log/memory reads;
it does not prove that the production loader or Google sync delivers every available metric.
No tester database or linked personal account was used.

- **12,408 main numeric-field recalculations**, with **3 disagreements**, all three in
  one recovery-score usual-range record. The separate deterministic reproduction below confirms
  this is a real score-definition inconsistency, rather than a bad reference calculation.
- **407 supplemental numeric-field checks**, with **0 disagreements**.
- **204 complete-group run-correction checks** (201 main, 3 supplemental), with no
  disagreements, independently applying Benjamini-Hochberg to emitted base p-values. This
  checks correction arithmetic; it does not validate causal assumptions or sampling independence.
- **525 additional food/source checks** on main outputs,
  with no mismatches: confirmed-meal totals/value counts/names and knowledge passage identity,
  text, title, source and URL. Semantic relevance is graded separately; matching a passage can
  still mean the wrong exercise was retrieved.
- Ordinary data frames were checked against independent raw/derived reference columns during
  per-turn review. Missing values and actual zeros remain distinct. Public values were redacted
  from inspection output; private full keys and transcripts remain under ignored `data/eval/`.
- Local API state was examined before/after every turn: waiting cards, cancelled replacements,
  memory proposals/approval/recall and reminder schedules. No new succeeded provider action or
  attempted Google traffic occurred. This is an application-level local test, not proof of
  deployed or real-provider write behavior.

## Interpretation and priorities for Claude

My assessment: **clear numerical lookups are substantially more dependable than the complete
conversation experience**. The main metric sweep passes 165/170 turns, including 67/68 cold
relative-date questions and 98/102 explicit-window chains. This supports the PHIA date repair's
usefulness beyond its original questions. It does not establish broad reliability: overview/why/
coaching passes 5/16 fresh turns, workout lifecycle 2/15, and memory lifecycle/privacy 2/8.

The typed-reader approach is still reasonable. The evidence points to incomplete intent coverage,
state handling and dispatch guarantees. Extending a phrase list for these exact questions would
leave the same classes of failure. Several are structural: a confirmation was correctly decoded
as `confirmation` and nevertheless reached a reply that said an unsent draft was saved.

All concrete values in the examples below come from made-up fixtures. Actual public participant
values remain in ignored local artifacts.

### 1. Bind confirmation and status replies to persisted action state

Fresh `logging_corrections-01/t4`, `-02/t4` and `-03/t4` all say **Saved** or **I've saved**,
while each action remains `draft`; there is no provider write. The request trace already labels
the message `kind=confirmation`. This is not just an inability to recognize the confirmation.
In `backend/app/agent/ask.py`, the early typed execution branch handles data/causality/clarify/
guidance, while confirmation continues through routing; a chat-like affirmative can reach a
free-form reply. Inspect that dispatch and the generic chatting/affirmative path.

Use the existing pending card as the authority: text should point to its confirmation control,
and success should require actual succeeded state. A display guard should reject a success
acknowledgement inconsistent with action status. This should cover different wording and all
write kinds, not just add a regex for one phrase.

`logging_corrections-02/t1` also creates a run card with 34 active minutes but start 17:20 and
end 18:54: a 94-minute elapsed interval with an unexplained extra hour. A grader checking only
`activeSeconds` would pass it. Derive/check the complete interval and do not invent pauses.
The mixed probe prepares the correct 28-minute walk but answers only that steps were usual,
omitting the requested actual count despite having computed it (`diagnostic_mixed_log_read-01/t1`).

### 2. Preserve the user's actual scope, metric and selected comparison window

- `reg_value_coincidence-01/t1..t3`: Oct 19 and Oct 20 deliberately have identical resting-HR
  values. Moving to Oct 20 succeeds, but **keep that same date** reverts to Oct 19. Matching a
  visible number alone would wrongly pass the last turn.
- `reg_calendar_transitions-01/t3`: two days forward from Feb 28, 2024 becomes Mar 2, rather
  than Mar 1. The fresh leap-year values themselves are correct.
- `calendar_edges-02/t4` and `-03/t4`: the minimum over a just-named multi-day interval
  collapses to its endpoint. The minimum is then computed correctly on the wrong singleton.
- `metric_followups-25/t3`: shifting the recovery-score interval two days earlier is ignored.
- `metric_followups-27/t1..t3`: the physical stress-signs score is replaced by morning check-in
  rating. Both cold queries for that stress metric work, so recognition is inconsistent.
- `cold_relative_day-30/t1`: the registered cardio-zone-minute series is incorrectly called
  unavailable, although the equivalent range and explicit-window questions work.
- `calendar_conventions-01/t1` and `-03/t1`: **this week** and **last week** both become
  Nov 6–12 on frozen Nov 19. Existing `backend/app/agent/periods.py` defines the calendar
  conventions; the candidate's code anchor repair does not guarantee the correct period kind.
- Additional probes preserve the first recorded night, but ignore **forward one recorded
  night**; choosing **the earlier** of two labelled comparison windows also selects the later
  one. The next turn can be a cascade; see its individual adjudication rather than treating
  every later failure as an independent model defect.

Inspect normalization and persistence in `backend/app/agent/requests.py`, especially
`previous_state`, `period_window`, `resolve` and how resolved request state reaches history.
Canonical state needs to retain the latest resolved intent, not drift back to an older turn or
collapse a named range to a previously mentioned day. A new explicitly named metric or period
must win. Validate semantic metric identity as well as enum membership: `checkin_rating` is a
valid enum and therefore passes a schema even when the user asked for `stress_score`.

### 3. Treat coverage counts as distinct from threshold counts

Across four main association profiles, **how many HRV days were actually recorded** gets
**What threshold and comparison should I count days against?**. Missing-day questions after
zero-count questions either repeat the zero count or request a threshold. There is no ambiguity
about which metric/interval was requested. The independent keys and actual tool frames contain
the counts. All four supplemental HRV-coverage questions fail too, including 70 HRV observations
with zero paired step/HRV dates.

`count` in the typed schema requires a comparator and threshold. `coverage` exists, but must
represent and render the requested recorded/missing/paired count, not merely a percentage.
Check the interpreter, the coverage intent representation and `requested.py`'s renderer together.
Do not use a threshold-count clarification as the fallback for every “how many days” question.

### 4. Restore personal investigation, coaching and memory intents

`reg_broad_investigation-01/t1` asks to investigate personal activity, sleep and recovery, but
gets a web explanation of Fitbit readiness. A fresh generic overview works on one fixture,
but the same wording becomes an exercise/food clarification on two others and an all-history
mean panel on another. The follow-up **what in my recorded data could go with that?** is often
read as an unclear movement. All four fresh coaching follow-ups fail. A panel of correct means
is not an analysis of what changed or why.

For memory, `reg_memory_cross_chat-01/t1` does create a correct preference proposal, but its
reply refuses the request as a lookup. The fixture approves that local card; subsequent recall
still fails. The fresh walking-preference request creates no card at all; its trace is
`kind=guidance, memory=deny`, despite an explicit remember instruction. A preference question
can instead produce a physiological change overview. One-off clarification fragments such as
**They mean the bridge** or a date are also proposed as durable memory facts.

The request representation currently has no explicit memory/read-memory/manage-memory kind;
it carries only a memory deny/unspecified flag. Ensure these product intents reach the actual
memory subsystem and reply path. Ground recall/status in account-scoped state, and preserve
explicit no-save behavior, which did work in the fresh privacy probe. Do not confuse failed
proposals with tested successful updates/deletions: those lifecycle stages were not reached.

### 5. Retain food filters only when the user actually requests them

Confirmed meal readback works initially. In `reg_nutrition_read_and_write-01/t3`, asking for the
same day's protein total before confirming a snack returns **0 entries**, although two succeeded
meals remain. The decoded request incorrectly has `meal_type=SNACK`. Arithmetic inside that
wrong filter is correct; its answer is still wrong. The snack draft is correctly excluded, but
confirmed breakfast/lunch are excluded as well. Recompute any inherited filter from the current
request rather than carrying a nearby food mention into an all-meal total.

Both fresh apple-draft attempts fail with generic rephrasing/date requests. If serving size or
time is actually missing, ask for that field instead of losing the already established day.

### 6. Retrieval must preserve the requested exercise variation and topic

Exact **bodyweight squat** requests work repeatedly; equivalent **unweighted squat** wording
retrieves weighted-belt/benches or Olympic barbell instructions. A generic pushup request can
become a single-arm or decline variation. Basic floor-bridge instructions work, but a later
start/breathing question switches to a single-leg bridge and says no breathing passage exists,
even though the original basic-bridge passage contains it. French squat follow-ups can revert
to pushups. Quiet-reading and standing-during-a-call follow-ups can be treated as unclear exercises.

Some responses correctly admit that a retrieved passage does not support an answer; that is
safer than fabrication, but it still exposes retrieval failure when the right corpus passage
exists. Matching citation text/IDs is necessary but does not establish relevance. Use semantic
exercise identity, variation constraints and active topic selection before generating the reply;
keep ambiguity clarification when two actual exercises remain possible. Read the source-backed
answer, not just retrieval hits or evidence presence.

### 7. Fix the independently reproduced recovery-baseline inconsistency

`prompt_injection-01/t1` safely rejects a fabricated HRV value and gives the correct observed HRV.
However, a recovery-score `compare_day` record has three baseline quantiles inconsistent with
the canonical recovery series. The same discrepancy reproduces without any model call:

1. Start from the captured full per-turn frame and independent rolling-rank recovery scores.
2. Run `compare_day` on the full frame: its three usual quantiles match the independent reference.
3. Restrict through `Toolbox(frame, EXPERTS['recovery'].owns)`, then run the same comparison.
   The day's original score remains, but its three baseline quantiles change.

`Toolbox` drops non-visible columns, including strain and sleep. `usual_before` calls
`with_scores`, whose early return requires **all three** derived-score columns. With strain
missing, it recomputes scores using the restricted raw inputs, so recovery's baseline uses two
components while the day's supplied recovery score used three. Inspect
`backend/app/analysis/day.py` (`with_scores`, `usual_before`, `compare_day`) and
`backend/app/agent/tools.py` (`Toolbox.__init__`). Preserve a score's definition independently
of which expert sees it; avoid partial recomputation over a reduced input universe.
This is a latent inconsistency detected in this candidate, not evidence that Claude's last
PHIA commit introduced it.

### 8. Make insufficient-evidence wording conditional on the actual reason

The null probe reports the near-zero correlation correctly. The constant-driver probe avoids
inventing a coefficient but says there are too few paired days, although all 140 days are paired;
the actual problem is lack of variation. Missing/null/undefined cases also receive the generic
**This shows what goes together** footer. That footer should not imply a relationship was shown
when the preceding result says otherwise. The candidate no longer directly asserts a positive
link in the main missing-HRV case; the remaining boilerplate issue is graded partial, while
its incorrect reason for insufficiency is documented explicitly.

## Grader corrections and fairness

Frozen expectations and raw responses were retained. Review corrections were made separately:

- A generic bike ride may validly use `BIKING`; `OUTDOOR_BIKE` is not mandatory. Both are valid
  contract enum values. The initial correct bike card passes.
- Future completed workouts are disallowed by the existing contract. A clear future-date refusal
  would pass; no future draft is required. The actual generic parsing failures are partial,
  rather than failures simply for not creating a future entry.
- An unspecified metric after an unresolved date reference can legitimately need clarification;
  an auxiliary steps key is not permission to invent that metric.
- The number-display helper fails to recognize **6 h** without a minutes suffix. That correct
  360-minute rounded answer passes after direct review.
- Coverage expectations' auxiliary means are not the requested coverage answers: actual nonmissing
  and missing row counts were checked instead.
- Some later turns follow an earlier wrong answer. The supplemental final same-night question is
  partial because it follows the last displayed date correctly, while the intended shift has
  already failed. Cascades should be separated from independent component failures.

The existing failures are now development material. Keep these artifacts unchanged as a regression
record, repair one underlying failure class at a time, and freeze genuinely new conversations for
the next generalization score. Include PHIA as a baseline regression gate as well as the broader
conversation audit; neither one replaces the other.


## Supplemental diagnostics

| Probe family | Turns | Pass | Partial | Fail | Strict pass rate |
|---|---:|---:|---:|---:|---:|
| diagnostic_association_constant | 3 | 0 | 2 | 1 | 0.0% |
| diagnostic_association_disjoint | 3 | 0 | 0 | 3 | 0.0% |
| diagnostic_association_null | 3 | 0 | 2 | 1 | 0.0% |
| diagnostic_association_positive | 3 | 0 | 0 | 3 | 0.0% |
| diagnostic_mixed_log_read | 2 | 0 | 1 | 1 | 0.0% |
| diagnostic_same_night | 4 | 2 | 1 | 1 | 50.0% |
| diagnostic_source_boundary | 1 | 0 | 1 | 0 | 0.0% |
| diagnostic_threshold_units | 3 | 3 | 0 | 0 | 100.0% |
| diagnostic_two_windows | 3 | 1 | 0 | 2 | 33.3% |

The additional profiles deliberately include a near-zero Spearman relationship (chosen from a
fixed-seed independent permutation before querying), a positive relationship, a constant driver,
and histories where both metrics have observations but never on the same dates. They are
illustrative edge fixtures, not a false-positive-rate study or evidence of causal validity.
They also cover recorded-night references, selecting the earlier comparison window, hour/minute
threshold conversion, a mixed read/log request and a source-merging request. See the supplemental
per-turn review for the actual results and any further limitations.

## Cost and execution controls

Main: OpenAI **$0.813822890**, Jev **$0.040875072**, uncertain reservation
**$0.000486822**; upper total **$0.855184784**.
Supplement: OpenAI **$0.052566540**, Jev **$0.002179716**, uncertain reservation
**$0.000483672**; upper total **$0.055229928**.
Combined recorded estimate: **$0.909444218**; combined conservative
upper estimate: **$0.910414712**. Remaining allowance: **$1.089585**.

A conservative combined meter reserves before every OpenAI completion/embedding/web call and Jev
call, charges cached tokens appropriately, retains uncertain failed-call reservations and disables
OpenAI SDK retries. Supplemental execution started only after the main process exited, with its
own cap set to the unused part of the original $2 allowance, including main uncertainty. These
are usage-based estimates from configured prices, not a reconciled provider invoice. The initial
launch was blocked before execution by Codex usage-limit approval review; a later authorized retry
cleared it. The blocked launch cost $0 and did not count as an evaluated turn.

All main and supplemental replies returned HTTP 200; HTTP success is not the correctness score.
Main API-wall-time p50 **2.33s**, p95
**5.45s**, maximum **17.52s**.
These are isolated local API timings including model/background work, not deployed mobile latency.
Models observed in completion logs: gpt-5.4-mini.
The main offline preflight used 18 scripted turns, and the supplemental preflight 5; none is a
paid agent correctness result and none is included in accuracy denominators.

## Reproduction and local artifacts

Main bundle: `data/eval/independent_validation_v3_2026-11-19/`.
Main output: `data/eval/independent_validation_v3_run_2026-11-19/`.
Supplement bundle/output use `independent_validation_v3_supplement_2026-11-19/` and
`independent_validation_v3_supplement_run_2026-11-19/` under the same directory.

Start with `summary.json`, `report.md`, the compact non-passing index `failures.md`,
`reviewed_turns.md` and `adjudications.json` in the main
output; the supplemental directory has its own review and grades. `answers.jsonl` holds full
actual replies, source passages, evidence, traces and state. `diagnostics.json` holds independent
field/scope checks. `independent_row_reviews.jsonl` holds per-turn independent review inputs.
The matching `input_*.pkl` files preserve actual agent frames. `recovery_scope_reproduction.json`
records the deterministic full-versus-restricted score-baseline reproduction. Frozen keys are in
`answer_key.json`, original questions in `conversations.json`, raw/oracle frames in `profiles.pkl`.
All participant-level artifacts must remain ignored and out of git/PR/chat.
The seven historical regression profile fixtures were checked identical to their old raw/oracle
frames, clocks and local state, so the paired comparison uses the same questions and data.

The exact candidate is a clean detached worktree at `/private/tmp/patterns-agent-audit-v3-target`;
preparation work is at `/private/tmp/patterns-agent-audit-v3`, branch `test/agent-audit-v3`.
Durable original harness copies are in each frozen bundle; post-freeze reviewer/inspection fixes
and report helpers are copied into each run's `review_code/` directory. Review changes are grader
maintenance and did not alter frozen questions, product code or captured replies.

To independently regenerate diagnostics without paid APIs, run the stored corrected reviewer
against the stored bundle/output. Do not rerun the paid runner just to obtain a better score.
If the product is repaired using these cases, all now become development material; write and
freeze another independent set before making a new generalization claim. Main and supplemental
hash validation and key rebuild checks are recorded in `verification.json`.

## Limits and interpretation

This is a single local, scripted-assistant audit. Questions are deliberately challenging and
not a random sample of users. Repeated templates, related metrics and follow-up cascades make
turns statistically dependent. Some main synthetic construction/reference code and exposed
regressions are reused. Sparse public windows sometimes have very few measurements; correct
answers there demonstrate missingness handling, not statistical power. A null claim must not
be inferred from absent observations or from an underpowered test.

Google fetching/ingestion, cross-provider storage isolation, DST/non-UTC user clocks, actual
confirmation/provider writes/undo, deployed tester traffic, mobile UI, fixed emergency-reply
behavior and photo-based food
estimation were not validated. The fresh memory lifecycle did not reach successful approval,
update or deletion because proposals failed; its failed later turns do not prove an approved
walking fact was lost. A regression case did reach a real local approved preference and failed
to recall it. The local deletion fixture deleted zero facts and is not evidence that deletion
worked. Broad metadata/causality failures following an earlier failure are also cascades, not
independent component experiments.

The backend unit suite/CI counts previously reported by Claude are separate; this audit did not
rerun the entire backend/mobile suite or approve a deployment. PR #195 was still OPEN at the
same head when rechecked during the audit. Exact candidate identity and preserved artifacts
matter more than a single aggregate pass percentage.

## Complete family breakdown

| Family | Turns | Pass | Partial | Fail | Strict pass rate |
|---|---:|---:|---:|---:|---:|
| `cold_relative_day` | 34 | 33 | 0 | 1 | 97.1% |
| `cold_relative_range` | 34 | 34 | 0 | 0 | 100.0% |
| `metric_followups` | 102 | 98 | 0 | 4 | 96.1% |
| `calendar_conventions` | 18 | 16 | 0 | 2 | 88.9% |
| `calendar_edges` | 12 | 10 | 0 | 2 | 83.3% |
| `threshold_boundaries` | 15 | 15 | 0 | 0 | 100.0% |
| `multipart` | 12 | 12 | 0 | 0 | 100.0% |
| `broad_why_coaching` | 16 | 5 | 0 | 11 | 31.2% |
| `associations` | 12 | 6 | 2 | 4 | 50.0% |
| `rag_followups` | 18 | 12 | 1 | 5 | 66.7% |
| `rag_ambiguity` | 3 | 1 | 1 | 1 | 33.3% |
| `logging_corrections` | 15 | 2 | 4 | 9 | 13.3% |
| `food_readback` | 8 | 5 | 0 | 3 | 62.5% |
| `memory_lifecycle` | 5 | 0 | 0 | 5 | 0.0% |
| `memory_privacy` | 3 | 2 | 0 | 1 | 66.7% |
| `missing_and_empty` | 9 | 6 | 0 | 3 | 66.7% |
| `missing_zero` | 3 | 2 | 0 | 1 | 66.7% |
| `access_safety` | 4 | 3 | 1 | 0 | 75.0% |
| `prompt_injection` | 3 | 2 | 1 | 0 | 66.7% |
| `multilingual` | 3 | 2 | 0 | 1 | 66.7% |
| `unresolved_reference` | 2 | 1 | 1 | 0 | 50.0% |
| `public_real_histories` | 16 | 16 | 0 | 0 | 100.0% |
| `reg_metric_inventory` | 3 | 3 | 0 | 0 | 100.0% |
| `reg_scope_continuity` | 4 | 3 | 0 | 1 | 75.0% |
| `reg_scope_reset` | 4 | 3 | 0 | 1 | 75.0% |
| `reg_comparison_boundaries` | 6 | 5 | 1 | 0 | 83.3% |
| `reg_calendar_transitions` | 3 | 2 | 0 | 1 | 66.7% |
| `reg_broad_investigation` | 4 | 1 | 0 | 3 | 25.0% |
| `reg_premise_and_direction` | 4 | 2 | 0 | 2 | 50.0% |
| `reg_associations_and_lags` | 3 | 0 | 0 | 3 | 0.0% |
| `reg_multipart_and_units` | 3 | 2 | 1 | 0 | 66.7% |
| `reg_missing_and_zero` | 4 | 3 | 0 | 1 | 75.0% |
| `reg_rag_context` | 4 | 2 | 1 | 1 | 50.0% |
| `reg_rag_ambiguity` | 4 | 3 | 0 | 1 | 75.0% |
| `reg_rag_habits` | 4 | 2 | 0 | 2 | 50.0% |
| `reg_rag_languages` | 4 | 1 | 1 | 2 | 25.0% |
| `reg_rag_unanswerable` | 4 | 2 | 1 | 1 | 50.0% |
| `reg_logging_state` | 4 | 4 | 0 | 0 | 100.0% |
| `reg_nutrition_read_and_write` | 4 | 3 | 0 | 1 | 75.0% |
| `reg_future_and_ambiguous_logs` | 4 | 2 | 1 | 1 | 50.0% |
| `reg_reminders_and_return` | 4 | 2 | 1 | 1 | 50.0% |
| `reg_memory_cross_chat` | 4 | 0 | 1 | 3 | 0.0% |
| `reg_memory_isolation` | 4 | 1 | 2 | 1 | 25.0% |
| `reg_access_and_scope` | 3 | 3 | 0 | 0 | 100.0% |
| `reg_untracked_and_future` | 3 | 1 | 2 | 0 | 33.3% |
| `reg_instructions_in_user_text` | 3 | 3 | 0 | 0 | 100.0% |
| `reg_missing_context` | 3 | 2 | 1 | 0 | 66.7% |
| `reg_public_real_histories` | 6 | 6 | 0 | 0 | 100.0% |
| `reg_irrelevant_history_invariance` | 3 | 3 | 0 | 0 | 100.0% |
| `reg_value_coincidence` | 3 | 2 | 0 | 1 | 66.7% |
| `reg_guidance_data_boundary` | 4 | 3 | 0 | 1 | 75.0% |
| `reg_checkin_context` | 3 | 0 | 0 | 3 | 0.0% |
| `reg_empty_history` | 3 | 2 | 1 | 0 | 66.7% |

## Shared working-folder update at completion

While final artifact checks were running, additional uncommitted changes appeared in the shared
project folder: `backend/app/agent/ask.py`, `requested.py`, `requests.py`,
`backend/app/analysis/day.py`, `tools.py`, and a new `backend/tests/test_audit_v3_fixes.py`.
These were not made by this audit and were left untouched. The pinned candidate worktree remains
clean at `fa15f4a`; every reported paid result comes from that snapshot. New uncommitted fixes
are **not validated by these scores**. Freeze their eventual commit before another candidate run.
