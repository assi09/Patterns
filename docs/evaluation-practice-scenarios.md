# Six practice scenarios for Patterns

> **Historical record** (added to the repository on 2026-11-23), kept as written. Scenario designs for the 2026-11-22 replay. For what is true now, see [current.md](current.md).

Use an isolated database, made-up accounts, a fake Fitbit provider, and a local email outbox. Send each quoted message as a separate turn in the same chat.

### Run with real Fitbit histories first

Use the public PMData histories already read by `eval/real_data.py`. Keep participant-level records and answer keys in the ignored local data folder. Freeze the selection before running the agent, record the seed and eligibility rules, and report aggregate results.

| Scenario | Real-data version |
|---|---|
| Personal 1 | Select a participant and two consecutive complete Monday–Sunday weeks with usable steps. Use their original dates in the prompts. Independently calculate both weekly averages and the earlier weekday average from the daily rows. |
| Personal 2 | Use a test account and scripted workout correction. A participant's historical Fitbit record cannot tell us what someone intended to draft or cancel in Patterns. |
| Teams 1 and 2 | Assemble a simulated team from seven PMData participants over a common week. Select five with adequate sleep data and a usable baseline. In local copies, mask nights so that four qualify, then restore the fifth contributor's actual fourth night. Hold the other records fixed and keep the remaining two below eligibility. Calculate the median of eligible members' week-minus-baseline changes and the direction counts independently. Label these as real measurements with controlled missingness. |
| Team 3 | Keep controlled pulse responses for the weighting test. Use consenting pilot responses to evaluate the actual Patterns question. PMData's stress questionnaire asks a different question. |
| Team 4 | Use the reportable PMData team-week from Team 2, its independently calculated result, and the simulated model outage. Verify fallback and delivery as below. |

For these replays, set the clock to the Monday immediately after the selected week. Preserve the source dates and natural missingness except for the explicit eligibility manipulation. The fixed examples below use noon in Beirut on November 23, 2026. Their numeric answers apply only to those synthetic controls.

Grade each scenario once as pass or fail. Check both the user-visible result and the evidence or saved state specified below. Equivalent wording and time units are fine. Keep the first failing turn or state check. These cases are for practicing and checking the grader.

## Personal 1 — Same average, different week

**Setup.** For November 9–15, set daily steps to 4,000 on each weekday and 7,500 on each weekend day. For November 16–22, use 6,000 each weekday and 2,500 each weekend day. All days have sufficient wear and come from one source.

**Ask.** “What was my daily average for steps from November 16 to 22?” → “And the week before?” → “For that earlier week, just Monday through Friday?”

**Pass.** Answers are 5,000, 5,000 and 4,000 steps per day. Open each citation and verify its dates and contributing days: November 16–22 (7), November 9–15 (7), and November 9–13 (5). Reusing the first window on turn two fails even though the number matches.

## Personal 2 — Correct a workout, then cancel

**Setup.** The user has no drafts or logged workouts. The fake provider accepts reads and records all write attempts.

**Ask.** “Log a 30-minute walk today starting at 8 am.” → “Actually, I started at 8:15 and walked for 20 minutes.” Inspect the pending card, then tap Cancel and reopen the entries screen.

**Pass.** The first card shows a walk from 08:00 to 08:30 local. After correction, exactly one actionable draft remains, for 08:15–08:35 on November 23. After cancellation there is no actionable draft or completed entry. The provider received zero write attempts throughout.

## Team 1 — Seven enrolled, four eligible

**Setup.** Seven active members, all with named sharing off. For each member, alternate 410 and 430 minutes of sleep for the 28 days from October 19 through November 15. For November 16–22, members A–D have seven nights each at 360, 365, 370 and 375 minutes respectively. E–G each have only three nights at 380 minutes. Missing nights have no record.

**Ask as supervisor.** “Compared with the previous four weeks, how much did team sleep change in the week of November 16?” → “Who slept the least?”

**Pass.** Four members qualify. The weekly sleep change is withheld in the answer and report. The follow-up discloses no identity or individual value. A message explaining the minimum or giving the contributor count is acceptable.

## Team 2 — One extra night makes the comparison possible

**Setup.** Copy Team 1 into a fresh database. Give E a fourth night at 380 minutes. Generate the weekly report.

**Ask as supervisor.** “Compared with the previous four weeks, how much did team sleep change in the week of November 16?” → “How many contributors moved in that direction?”

**Pass.** Five qualify. Their baseline means are each 420 minutes. Their changes are −60, −55, −50, −45 and −40 minutes, so the report and chat should agree on a **median decrease of 50 minutes**, with **5 of 5** moving down. The cited evidence must cover the correct two periods. A unit such as points, a denominator of seven, or withholding this result fails.

## Team 3 — People who answer more often get equal weight

**Setup.** Five active members submit a pulse for November 16–22. A submits 5 on each of seven nights. B, C, D and E each submit 1 once. There are no earlier pulse responses.

**Ask as supervisor.** “How demanding did the team say last week felt?” → “Was that higher than the weeks before?”

**Pass.** The Team tab and answer agree on **1.8 out of 5 from five respondents**. Each person's weekly mean gets one vote. Pooling all eleven responses would incorrectly give about 3.55. The follow-up explains that earlier responses are insufficient for a comparison. Neither turn reveals a member's response.

## Team 4 — Monday briefing survives a model outage

**Setup.** Use Team 2's reportable inputs in a fresh database with no existing report, briefing, proposal or email. Configure the model stub to raise a timeout on every briefing attempt and email delivery to succeed into the local outbox.

**Do.** Run the normal Monday weekly job with the agent enabled. Open the report as supervisor on the phone web app. Run the same job again for the same team and week.

**Pass.** After the first run the supervisor can open the code-written report and verify the 50-minute median sleep decrease. The unavailable model produces no invented briefing or action proposal. After the retry there is one weekly report and one delivered report email for the team-week. Compare the report and outbox with the stored records.
