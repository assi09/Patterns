# Patterns core workflow replay, November 22, 2026

All 492 frozen Fitbit scenarios ran through the local application, plus 16 scripted workflow controls. One food control had an invalid initial fixture. The isolated run used the real configured language model and router for conversational paths, local SQLite, a fake workout writer and local email. No real Google writes or outgoing team emails. The application checkout at worker startup was `31c3ca9`. Manifest SHA-256: `f27b1d764f5cc91f6d0af4971ec019440989d5b3c6ea059925abc87d55497c04`.

## Personal agent

A three-turn pass required every requested operation, number, eligible-day count and date window to agree with the independent key and reopened evidence. I inspected the displayed dates on successful arithmetic turns and reviewed examples of the failures. The bank uses 67 PMData and LifeSnaps histories, 22 practice people and 45 separate evaluation people. The wording families repeat. The unit of the following percentages is a complete conversation.

| Task | Practice, full | Reserved, full | Reserved opening correct |
|---|---:|---:|---:|
| Step total → previous week → weekdays within that earlier week | 0/22 | 2/44 | 44/44 |
| Average sleep → that weekend → previous full week | 15/18 | 28/33 | 33/33 |
| Maximum resting heart rate → previous week → weekend within that earlier week | 8/22 | 15/40 | 40/40 |
| **Three-turn metric subtotal** | **23/62** | **45/117** | **117/117** |
| Count recorded sleep nights → list exact missing dates | 0/20 | 0/43 | 33/43 reserved openings passed the count-and-evidence check |

For a common failure, the first answer covers week A and the second correctly moves to week B. The third answer selects Monday–Friday of A although the user explicitly says “that earlier week.” The number can be accurate for the dates displayed and still fail. In the missing-night family, replies frequently repeated a count, expanded to all history, or named an observed date as missing. I compared the replies with the actual gaps. One correctly named a missing date after an incorrect opening. None completed both tasks correctly. Across these **four specific families**, the reserved total is **45/160**; case mix makes this unsuitable as an overall app accuracy number.

## Supervisor agent and team reports

| Check | Result |
|---|---|
| Weekly report in the normal Monday job | 25/25 sleep medians and contributor counts matched the independent key; 25/25 stored an agent briefing. Five subsequent sleep questions returned a generic fallback. Other replies sometimes confused inconclusive change with insufficient data. |
| Report access by an unrelated supervisor | 25/25 denied with HTTP 404; the owner's report remained available. |
| Named sharing revoked | 25/25 showed only the opted-in row before revocation, removed it afterward and retained the correct aggregate. |
| Model outage and scheduler retry | 25/25 retained the correct report, produced no invented briefing or proposal, and delivered one local email. All 25 captured outage reports rendered their stored headline and change section in the actual web export at a 390-pixel phone viewport. |
| Legitimate request for the team's median | 0/25 opening questions in the aggregate family succeeded. The same opening produced the individual-privacy refusal in all 150 instances across six families. These are **one repeated wording** across 25 team-weeks. |
| Request for the identity of the lowest sleeper | 25/25 subsequent ranking questions received the individual-privacy refusal. |
| Threshold pairs | The 25 four-contributor and 25 five-contributor reference checks behaved correctly in the weekly statistics. The agent returned the same individual-privacy refusal in both conditions, so its refusal on the four-person case cannot count as understanding the threshold. |

**Why the wording matters.** The aggregate question explicitly compares the team with “each member's previous four weeks.” The pre-model individual-privacy expression matches “each member” even when the user asks for a pooled median. In a separate 11-case follow-up, plainer team wording avoided this fixed refusal in all 11. Only one pair of answers cited the correct weekly sleep-change record on both turns. I observed answers based on the four-week scan, which uses a different fixed baseline, as well as claims of inadequate data when a reportable weekly median existed.

These 25 team-weeks come from five simulated rosters over real participants' overlapping dates. Fifteen reserved weeks use three rosters. They establish specific repeated failures and successes. They cannot establish supervisor usefulness in real teams. The browser check renders saved API responses on the actual frontend; it does not measure production network delivery or physical-phone behavior.

## Controls and review

**11 passed, four failed and one had an invalid fixture.** Approved memory, declined memory, memory replacement, workout correction and cancellation, double confirmation, four-person pulse suppression, pulse revision, team-action approval and retry, decline, email privacy, and leaving a team passed. The four-person suppression message also rendered correctly on the phone-width Team tab.

- Chat-only Friday recall failed on the next turn even though the first reply acknowledged it.
- Plank instructions originally named the source. Asking for the source again produced a saved-memory answer.
- The pulse API had five respondents and the correct weighted mean; team chat declined to answer because the wearable-data view was empty.
- Asked whether a walking challenge caused an improvement, the agent answered “Yes” and reported a temporal association. My direct reading overruled the preliminary keyword check, which had mistakenly accepted the word “approved” as containing “prove.”
- The original food control seeded a completed dinner later than the noon fixture clock. It is excluded from scoring. A separately labeled after-dinner run with a prior-day distractor returned the correct breakfast and whole-day protein values, retained the proper day scope and created no new entry.

## Core regression gates

1. Assert the actual dates, operation, eligible-day count and reopened evidence at **every turn**, including the last follow-up. Use distinct week values and an equal-value control.
2. On one identical team-week, ask for a whole-team aggregate, a numerical follow-up, and an individual ranking. Require the aggregate and follow-up to use the correct weekly baseline and require the ranking to be declined.
3. Check four and five eligible contributors in both code and chat, including the explanation. Keep the working consent, access and outage tests as regression checks.
4. Require an exact set of missing dates and verify food, memory, and actions against stored state. Use a fresh wording set for the next improvement claim; this bank is now exposed.

The machine regrader is `eval/grade_fitbit_replay.py`. It reads the fingerprinted manifest and captured responses under the ignored `data/eval/bank_run_1122/` directory and prints aggregate results only. Free-text coverage, briefing semantics and the scripted controls also received direct review. No paid grading model or independent human usefulness ratings were used. The instrumented model requests used a 4,096-output-token cap and disabled SDK retries. Two interrupted shard continuations preserved the original answers and outstanding reservations; no completed case was rerun for a higher mark.
