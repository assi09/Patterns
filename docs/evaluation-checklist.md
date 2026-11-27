# Human evaluation preparation checklist

**Draft protocol. Owners: Jad and Karim. Prepared 2026-11-27 against `2b31471`. Not run.**
Prepare the rubric, sampling and result format now; grade final outputs after the candidate and
scope are agreed. The [current team scope](pivot.md) takes precedence over historical personal
chat plans. The 51-answer blind sheet, roughly 50-answer judge calibration and roughly 40-answer
pilot review are separate assignments in [the plan](plan.md) and [evaluation](evaluation.md).
Overlapping samples must be labelled and never counted as independent evidence twice.

## Scope before sampling

- [ ] Freeze the candidate, enabled features, questions, expected evidence and baseline versions.
  Separate a team-product release check from historical evaluation of personal chat.
- [ ] Decide which older grading assignments still support the final report. Preserve their
  measured revision; grading old outputs does not create a result for the new app.
- [ ] Check eligibility and consent before any pilot-answer review. Use approved access inside
  Railway; do not copy private answers, health rows or identities to a laptop or repository.
- [ ] Agree sample size, selection seed, exclusions and the rubric before reading results.
  Do not select only successful turns. Keep refused, incomplete, timed-out and failed turns.
- [ ] Agree any real-model budget before execution. Writing questions or grading stored outputs
  does not require a paid API call; do not rerun benchmarks during this preparation.

## Evaluation cases

| ID | Assignment | Preparation and expected record |
|---|---|---|
| EVAL-01 | Blind grading of 51 saved answers | Prepare a shuffled anonymous sheet from `eval/results/phia_blind_2026-11-10.csv`; hide system and automated score until independent ratings are locked |
| EVAL-02 | Judge calibration on about 50 replies | Freeze common rubric and sample; both people grade independently; compare judge and human ratings only after lock |
| EVAL-03 | Manual check of about 30 automated readings | Sample judgments before inspection; check whether the grader interpreted the answer and evidence correctly; retain disagreements |
| EVAL-04 | Fresh independent questions and multi-turn conversations | Jad or TA writes cases and expected outcomes before Karim runs; keep development, replay and held-out roles distinct |
| EVAL-05 | Pilot review of about 40 answers | Read only consenting testers' eligible answers through approved in-place access; publish aggregate rubric scores only |
| EVAL-06 | Final report and limitation review | Every reported number names revision, denominator, scope, baseline and exclusions; deferred and retired features stay labelled |

Each case remains `not run` until executed. Historical totals in [current.md](current.md) and
[test-results.md](test-results.md) retain their own scope and revisions. A scripted MCP client,
a real assistant, an app screen and a tool-only benchmark are different surfaces and should
have separate scores.

## Rubric to agree before grading

Use the question, the dated evidence and the relevant permitted action as the reference.
For each criterion below choose `met`, `not met` or `not assessable` and a reason. Do not turn
missing evidence into a pass. For subjective presentation scores, agree examples before use.

| Criterion | Met when |
|---|---|
| Addresses the request | Correct team, operation, week and requested follow-up are answered or a warranted limit is explained |
| Correct | Figures, directions, units, cohort and dates match the independent reference |
| Complete | Required parts are covered; missing data and withheld figures are stated |
| Supported and within scope | Claims cite the right evidence; no invented cause, medical conclusion or unauthorized disclosure/action |
| Useful | Human score 1 to 3: unusable, partly useful, or useful for the stated task |
| Clear | Human score 1 to 3: confusing, needs interpretation, or understandable with dates and limits |

Freeze the exact criterion encoding and aggregation before use. For a valid refusal, judge
correctness against the access/scope rule rather than penalizing the absence of a data answer.
An outage is a task failure, not a valid refusal. Evaluate privacy failures separately even if
the rest of an answer reads well.

## Independence and agreement

- [ ] Jad and Karim complete separate ratings before seeing the other person's or judge's scores.
- [ ] Lock original ratings; record adjudication in a separate field instead of overwriting them.
- [ ] Report exact agreement for each common criterion and Cohen's kappa for categorical ratings
  where defined. If using weighted kappa for ordinal scores, freeze weights in advance.
- [ ] Compare both human raters with each other and the judge with each rater; label any
  adjudicated reference separately. Report the number of assessable pairs for every metric.
- [ ] If kappa is undefined because all scores occupy one category, report that fact and raw
  agreement. Do not substitute a perfect kappa or suppress the denominator.

## Writing fresh cases

Use synthetic teams and independent expected answers. Cover normal, edge, adversarial,
historical-failure, ambiguous, long-horizon and tool-failure scenarios. Include the same words
with a different prior week, cohort, pending decision or role so context actually matters.
Follow-ups should cover a finding, its evidence, missing coverage and an earlier decision.

Do not read router or guard prompts to derive attacks. Keep fixture, expected dates/units/state
and scoring rule fixed before Karim executes the candidate. Once a case informs a repair,
label it development/regression and reserve new cases for subsequent independent validation.
Personal-chat cases are optional historical work while `FA_PERSONAL_FEATURES` is off; record
any exclusion rather than claiming those features pass on the team release.

## Result template and report handoff

The private grading record contains case id, source revision, anonymized system label, rater,
criterion scores, actual outcome, evidence reference and disagreement notes. It stays in the
approved environment for participant data. Public output contains only counts, rates,
agreement measures, scope, revisions and non-identifying limitations.

- [ ] Report numerator and denominator, including exclusions, blocked cases and missing ratings.
- [ ] Keep initial result and post-fix retest separate; identify reused versus fresh questions.
- [ ] Give Jad's report sections the threat review, failure/QA results and unresolved risks;
  Karim supplies the core system evaluation and integrates the final report.
- [ ] Ask both reviewers to verify factual claims and privacy before the report or PR is shared.
