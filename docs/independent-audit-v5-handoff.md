# Independent audit of PR 195, November 20, 2026

> **Historical record** (added to the repository on 2026-11-20), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

**Hold the merge.** The candidate at `7ef95c7d16a85835f8e57a592025920e029a8b19` handled direct metric retrieval well. It answered a named January investigation with November data. That single example violates the predeclared period gate. Several conversational areas also fell below target.

## What was tested

54 fresh conversations, 91 user turns, all 34 daily metrics, plus the separate 24-question public PHIA B1 regression sample. Questions, source profiles, expected results, and a guidance corpus snapshot were frozen before execution. Bundle ID: `df68a9ee0353f3a4ee60ebab021abb976377cd4c27734c3c855100a7bd8275c3`. The conversational data were synthetic. Review compared the words shown to the user with the expected scope, independently computed answers, evidence IDs, guidance text and card or fact state. Partial credit indicates a material omission and counts against the full-correct targets.

## Results against the acceptance criteria

| Area | Pass | Partial | Fail | Fully correct |
|---|---:|---:|---:|---:|
| Data opening | 39 | 0 | 1 | 97.5% |
| Data follow-up | 10 | 0 | 5 | 66.7% |
| memory | 6 | 2 | 1 | 66.7% |
| logging | 3 | 3 | 2 | 37.5% |
| safety | 1 | 0 | 2 | 33.3% |
| investigate | 2 | 2 | 4 | 25.0% |
| guidance | 5 | 1 | 2 | 62.5% |

Data openings include a two-part opening, missing data and confirmed food. The follow-up row includes all dependent turns in those same data conversations. For reproducibility, the original frozen families break down as follows.

| Area | Pass | Partial | Fail | Fully correct |
|---|---:|---:|---:|---:|
| follow | 5 | 0 | 1 | 83.3% |
| metric | 41 | 0 | 2 | 95.3% |
| memory | 6 | 2 | 1 | 66.7% |
| data | 3 | 0 | 3 | 50.0% |
| logging | 3 | 3 | 2 | 37.5% |
| safety | 1 | 0 | 2 | 33.3% |
| investigate | 2 | 2 | 4 | 25.0% |
| guidance | 5 | 1 | 2 | 62.5% |

- All 34 named-metric opening questions passed, using mean, maximum or minimum over a six-day interval. This tests breadth of retrieval with a common question structure. Seven of nine adjacent-block follow-ups passed.
- Six of 91 turns asked an unnecessary clarification or restatement (6.6% across the deck, under 10%). One followed an earlier failed food lookup. Two were generic requests to rephrase. The denominator includes repeated direct lookups.
- Independent recalculation found zero mismatches in 3,335 checked numerical evidence fields. This checks the arithmetic on the days actually selected. The separate PHIA check found zero discrepancies in 620 numerical fields and **23/24** fully correct answers against a **24/24** baseline. The one regression confused awake time in bed with still time while awake. The PHIA allowance is one regression. PHIA and conversational results use separate denominators.
- The observed confirmed forget removed the intended fact and retained the unrelated one. Cancel preserved the target. No unconfirmed deletion, explicit false claim of a completed tracker write, medical claim, or disclosure of another person's measurements was observed. One false claim that a workout had been drafted is reported separately. No retained kayaking preference was observed. A readback generated an unrelated preference candidate. These cases do not establish system-wide privacy or the contents of production logs.

## Findings for implementation

1. **Validate the final dates against the requested relation at execution and delivery.** Two metrics moved the old interval one day forward when asked for the next whole six-day block. A leap-day window collapsed to its endpoint while a year-boundary control passed. A threshold follow-up changed the dates and retained equality. Represent what changes independently (threshold operator, interval length, anchor and inclusion). Test these as properties across metrics, calendars and phrasing. For investigations, compare the actual analysis interval with the requested interval before rendering. If January has no coverage, say so. Recent evidence cannot answer that question.
2. **Deliver and persist every clause.** Two correct numeric side reads beside draft-status replies had zero API evidence IDs. In `backend/app/agent/ask.py`, `_with_reads` appends the side summary and merges evidence without merging its claims. `backend/app/db/chat.py:add_answer` persists cited evidence. Carry the side-read claim and evidence through the ordinary answer path, then check the API and the reopened conversation. In the mixed workout case only the step lookup completed. Require a stored draft ID before reporting a draft and a result for each requested clause. A run correction preserved the old duration while a parallel walk correction succeeded.
3. **Select the source the user requested.** Read confirmed meals by meal/date before mapping a nutrition question to daily metrics. The breakfast energy and subsequent all-meal protein requests both failed despite confirmed entries. Distinguish status of an exercise entry from status of an approved memory. A canceled deletion left the correct fact in the store, yet recall answered about the tracker. Prevent a read-only recall from creating a new preference candidate.
4. **Check the complete investigation answer once it is assembled.** On both the changing and stable profiles the coaching answer contained mutually exclusive conclusions. Select one supported option or explain the limit, and verify the entire message including appended text. A variable that includes the outcome by construction (time in bed includes sleep time) adds little explanatory value. Qualify that relationship explicitly and limit exclusions to hypotheses actually tested. Retain the supporting claim IDs for each finding in the overview.
5. **Preserve the guidance topic through routing and verification.** Bodyweight squat and wind-down follow-ups worked. The pushup follow-up asked which movement and the Superman follow-up refused despite relevant source material. Check the active passage and topic at each handoff. Filter citations to passages supporting the actual movement and variant. Include both working control pairs in regression coverage.
6. **Distinguish the subject and the requested response.** Another person's records were correctly declined. Asking for one's own steps while mentioning a partner triggered an unnecessary threshold question. A diagnosis request received unrelated step commentary. Test ownership, operation and question type independently.

## Execution limits and reproducibility

The budget harness initially prevented 22 turns from reaching the reader. Those turns had no card or fact changes. Only those 22 were completed on a copy with the same pinned code and the prior conversation state restored. The other 69 answers were retained. Two generic fallback paths encountered budget stops during the original execution, so their outputs are graded as seen and their production failure rate is unknown. A local focused suite of 75 checks passed. The 2,092 full-suite count comes from the implementation handoff. This is a small targeted sample, especially in logging and guidance. The earlier audits used different prompts, so changes in area percentages are descriptive.

The ignored local directory `data/eval/v5_inputs` contains the frozen deck and key. `data/eval/v5_completion/reviewed_turns.md` contains all 91 questions, replies, per-turn judgements, expectations and evidence references. The companion `answers.jsonl` includes before/after state, claims and trace; `diagnostics.json` contains recomputation details. The PHIA review and scope checks are in `data/eval/v5_phia`. Recalculate offline with `.venv/bin/python data/eval/v5_code/review_independent_validation.py --bundle data/eval/v5_inputs --out data/eval/v5_completion`.

The audit and PHIA cost upper bound was **$0.253334208**, bringing the recorded running total to approximately **$1.7250 of $2**. Keep this deck for regression and judge any subsequent release on unseen conversations.
