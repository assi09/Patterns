# PR 195 fresh live audit, November 20, 2026

**Hold the merge.** On frozen commit `9684d773cc64eb0aa1f8d2d7a7b6002a4ed2b744`, eight metric follow-ups silently used an old interval. An equality count also returned the expected number for the wrong week. The zero-swapped-period gate in [the acceptance criteria](acceptance-structured-requests.md) failed. The small PHIA gate passed.

## What was run and graded

The first cohort comprised 36 turns in 16 chats (28 full, 6 partial, 2 fail). An expanded deck added 218 turns in 98 chats (181 full, 13 partial, 24 fail). Each deck was frozen before its own run. The second cohort deliberately stresses all 34 daily metrics on synthetic histories. The two wordings of each scenario ran in separate conversations. The 24 public PHIA B1 questions were graded separately. The candidate stayed fixed throughout.

For each conversation turn the review considered the final text, expected answer, operation, source, requested calendar dates, cited evidence and applicable stored state. Numerical expectations came from the synthetic source rows. For guidance, the review compared the answer and cited passages to the requested topic and variant. For action and memory cases it checked the database after the turn, including pending cards, corrections, status and saved facts. A correct value attached to the wrong interval fails. A substantively correct answer with an extraneous citation or unsolicited memory candidate can earn partial credit. Partial credit is excluded from the full-pass and paired numerators.

| Area | Full | Partial | Fail | Both wordings fully correct |
|---|---:|---:|---:|---:|
| Direct lookup across 34 daily metrics | 67 | 0 | 1 | 33/34 |
| Adjacent-period follow-up on those metrics | 58 | 0 | 10 | 24/34 |
| Additional interval questions | 4 | 0 | 0 | 2/2 |
| Thresholds and equality | 4 | 1 | 1 | 1/3 |
| Multi-part data questions | 3 | 0 | 1 | 1/2 |
| Coverage and missing data | 5 | 3 | 2 | 1/5 |
| Nutrition | 8 | 1 | 1 | 3/5 |
| Overviews, explanations and coaching | 5 | 4 | 7 | 2/8 |
| Guidance | 11 | 7 | 2 | 3/10 |
| Logging, corrections and status | 18 | 0 | 0 | 9/9 |
| Explicit memory workflows | 20 | 0 | 0 | 10/10 |
| Ownership, boundaries and safety cases | 6 | 3 | 1 | 2/5 |
| **All fresh turns** | **209** | **19** | **26** | **91/127** |

Direct metric questions cleared the 90% target (98.5%). Adjacent-period questions fell below it (85.3%). Investigations reached 31.3% against 75%, and guidance reached 55% against 85%. Action and explicit memory workflows cleared their respective targets. Eight clear turns elicited unnecessary clarification (8/254 across this deck), including cascading failures after a clearly specified opening question. Nineteen turns took multiple reader attempts. These counts measure different behaviors.

Overall, 82.3% of turns passed fully and 71.7% of wording pairs passed both ways. The registry template contributed 136 turns. The other 118 turns had 84 full passes, 19 partials and 15 failures, with 34/59 pairs fully correct. These are designed tests with shared histories and related turns. They do not estimate what percentage of ordinary users will receive a correct answer. The v5 result (66 full, 8 partial, 17 fail) used a different deck, so the difference cannot isolate the effect of the code changes.

## What held up

- Independent recomputation agreed with all 7,491 checked numerical fields in the scored conversation runs. The B1 sample had another 620 checked fields with zero mismatches. These are checks of fields in evidence the agent produced. They include repeated fields and coverage statistics. A calculation can agree perfectly with the source rows and still answer a different question.
- All 18 workout turns delivered the requested action behavior, including the data read beside a draft, an inspectable side result, the corrected duration and actual draft status. No real Google writes were needed.
- All 20 targeted memory turns passed. Recall, approval, cancel and confirmed deletion behaved correctly in the tested flows. The audit found no false success, unconfirmed deletion, disclosure of another user's values or observed medical answer. Unsolicited candidate creation on ordinary questions remains a separate problem. This conversation audit does not certify all deployment logs for privacy.
- PHIA B1 scored **23/24**, matching v5 on this sample and within the allowed one-question drop from the stored 24/24 comparator. The miss confused an awakening-duration question with sedentary awake minutes. The 130 tests in the candidate's v5 reliability regression file also passed in an independent offline run. PHIA exercises wearable-data questions, while the fresh conversations also exercise edits, memory, citations, multiple clauses and scope carried across turns.

## Remaining work, in priority order

1. **Bind time and source to each requested calculation.** Eight of the 34 second-wording metric follow-ups reused the five-day interval when the user asked for the next two dates. A distance follow-up asked for clarification. A stress-score conversation selected strain. In a separate test the equality count for September 1–7 silently used August 31–September 6. Both periods had the same count. Inspect the reader-to-resolver boundary and `backend/app/agent/checks.py` (`adjacent_said`). Preserve the referenced interval, its endpoint, direction, requested length and inclusion as typed fields. Resolve dates once and compare the execution and the final citation against the requested dates. Distinguish a baseline relative to an interval in the current message from a reference to an earlier message. A future month written with “of” also triggered a question proposing the previous year. Exercise these rules across month/year transitions, multiple earlier intervals, equivalent counts, and the counterexample of moving the whole interval by a day.
2. **Enforce the requested evidence source.** A meal conversation explicitly switched from intake to calories burned. One wording answered from the food logs again, while the paired wording used the wearable record correctly. Trace `_food_source` in `backend/app/agent/requests.py`. Carry intake versus expenditure through resolution, evidence selection and answer verification as separate sources. Inherit a prior food filter only when the new clause leaves the source open. Test switching both directions with unequal totals and pending meal drafts.
3. **Make investigative conclusions verifiable.** A summary correctly named sleep changes and then claimed the rest looked steady despite other significant changes. A second profile reproduced the unsupported blanket statement. In `backend/app/agent/findings.py`, check the domain of phrases such as “the rest” against the complete set of tested metrics before truncating a summary. If only selected findings fit, report those findings with their citations. A cold-start request to compare a named fortnight with the preceding period also produced “Which earlier measurement?” and one coaching follow-up ultimately used 60 days. Preserve the family of question (description, explanation or coaching) and the explicit dates across fallback paths. An explanation should identify a tested relationship or state what the data cannot distinguish. With missing HRV, give the individual coverage as well as the joint-day count and attach inspectable evidence.
4. **Gate memory side effects at the storage boundary.** Ten ordinary read turns created or promoted a candidate/proposal. Examples included a retrospective threshold question and a question about someone else's steps. The latter became a preference about accessing the other person's total. No such value was disclosed or silently approved. Review the `read_only` decision in `backend/app/api/chat.py`. Require an eligible current-turn assertion or an explicit storage request before invoking the listener. Apply that permission per clause so that a real preference beside a lookup can still be saved through its approval flow. Verify the absence of candidates as well as approved facts after a pure question, including after the chat is reopened.
5. **Verify guidance against the requested variant, passage by passage.** A floor bridge got barbell guidance although a bodyweight passage was available. Several correct movement cues cited weighted, kneeling or decline variants. A sitting-break follow-up asked the user to distinguish their work setting from the routine already discussed. Carry the movement, equipment constraints and established routine across retrieval. Select evidence for each instructional claim, removing passages that fail the variant constraints. Grade citation relevance even when the advice sounds plausible.

## Reproduction, cost and limitations

Local files under the git-ignored `data/eval/` retain the frozen questions, profile inputs, answer keys, usage receipts, API state and evidence. `v6_review/reviewed_turns.md` contains each graded question, delivered answer, reference, cited source, state and reason. `v6_review/adjudications.json` contains the machine-readable judgments. Base fixtures and results have the `v6_` prefix, the four expansion shards use `v6x_inputs0..3` and `v6x_results0..3`, and the PHIA review is under `v6_phia/`.

An audit fixture initially marked a pending snack as confirmed. The two affected meal chats (six turns) were rerun with their frozen questions against corrected database state. Only the replacement turns count in the table. Both executions count toward spend. An account-casing issue also stopped three shards at fixture login before their chat requests; setup was corrected before continuing. The expansion is a separate cohort designed after the first cohort. The run samples one live trajectory per wording. Chain failures count because they affect the user, so nearby failures can share one cause.

The conversation runs, fixture correction and PHIA together cost **$0.582463194**. The prior cumulative spend was approximately $1.7250, bringing the authorized $4 total to approximately **$2.3075**, with **$1.6925 remaining**. This handoff concerns the frozen candidate only. The fresh decks now serve as regression material.
