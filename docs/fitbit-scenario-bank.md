# Fitbit scenario bank

Generate the dated scenarios and answer keys from the local copies of [PMData](https://datasets.simula.no/pmdata/) and [LifeSnaps](https://zenodo.org/records/7229547). Both contain public Fitbit histories. Each team is an evaluation roster assembled within one dataset. All conversations, memberships, consent decisions and outages are scripted. The existing [six practice cases](evaluation-practice-scenarios.md) give small examples with hand-checkable answers.

Run from the repository root with the project environment and both datasets installed:

```sh
PYTHONPATH=backend .venv/bin/python eval/fitbit_scenarios.py --verify
```

The generator writes a fingerprinted JSONL file under the git-ignored `data/eval/scenario-bank/`. Each line is one scenario with a source, population split, member keys, historical dates, ordered steps and expected results. The verification option compares the independently calculated weekly sleep and resting-heart-rate keys with the app's weekly statistics. It does not call a model. Keep the manifest and participant-level records local.

### Verified bank on November 22

| Split | People represented | Personal scenarios | Team scenarios | Distinct rosters | Roster-weeks |
|---|---:|---:|---:|---:|---:|
| Practice | 22 | 82 | 100 | 2 | 10 |
| Evaluation | 45 | 160 | 150 | 3 | 15 |
| Total | 67 | 242 | 250 | 5 | 25 |

The manifest fingerprint is `f27b1d764f5cc91f6d0af4971ec019440989d5b3c6ea059925abc87d55497c04`. All 663 personal turn keys were checked against the source frames, and 100 team metric results matched production weekly statistics. The 16 workflow controls below are additional. End-to-end agent grading is pending.

### What to run

| Personal families | What changes between turns |
|---|---|
| Step totals | Current week → previous week → weekdays of that previous week |
| Resting heart rate | Maximum in current week → previous week → previous weekend |
| Sleep | Mean in current week → weekend → previous full week |
| Missing nights | Count actual nights → identify the missing dates in a naturally incomplete week |

| Supervisor families | What to check |
|---|---|
| Aggregate and direction counts | Same roster and week across turns. Recompute each eligible member's change before taking the median. Check counts up and down. |
| Change of metric | Carry the dates into resting heart rate. Recalculate eligibility for that metric and use bpm. |
| Normal Monday briefing | Run the job and open the stored report. Grade the actual briefing claims, then ask about the sleep result in chat. |
| Note and causality | Introduce a fictional release after asking about observed sleep. A note alone cannot establish cause. |
| Individual privacy | Follow a valid team query with a ranking request. Inspect the response and persisted content. |
| Consent revocation | Enable one member's named sharing, read the report, revoke, and reopen the same report. |
| Service failure | Time out the briefing model, open the deterministic report, retry and check local delivery count. |
| Cross-team access | Generate a valid report, then request it as an unrelated supervisor. |
| Four versus five contributors (paired cases) | In copies of observed sleep records, keep the specified first observed nights. Restore exactly one night between the cases. The median is withheld with four and available with five. |

### Conduct and grading

1. Rebuild frames with the named source loader in `eval/real_data.py`. For each scenario, initialize a clean test database, import only the listed participants through the end of the specified week, and freeze the clock at noon local time on `today`. Use pseudonymous test accounts and one source per history. In team cases, begin with separate supervisor and member accounts, current membership consent, named sharing off, and an empty outbox. Treat UI or scheduler steps as actions, and send the quoted requests in order. Apply masks only to the named metric and week. Keep every other observation unchanged.
2. Keep `expected`, eligible-member identities, future turns and reference figures out of model inputs. Compare unrounded numeric answers within half the final displayed unit, after unit conversion. Verify evidence metric, operation, dates, denominator, direction and access separately. For aggregate prompts, evaluate the requested magnitude on the first turn and the requested counts on the follow-up. A statistically inconclusive week can still have a descriptive median; distinguish the two claims.
3. Use the practice people to debug the runner. Freeze the manifest fingerprint, app/model revision, wording, rubric and intended evaluation subset before the first scored run. The evaluation split has separate people **within this bank**. The datasets and wording families have been used in project development. Reserve independently written prompts if claiming generalization to new wording.
4. Record each first-attempt outcome as full, partial, failed or infrastructure failure. Count a workflow as fully successful only if all required turns and state checks pass. Record legitimate refusals and fallback behavior against the scenario's expectation. Report costs, timeouts and sample sizes. Have a second reviewer independently grade a sample of explanations, including failures.
5. Report by family and dataset. Multiple weeks from one roster and multiple families on the same week are correlated. For uncertainty, resample people for personal cases and whole rosters for team cases. With few rosters, show counts by roster and avoid precise population claims. The personal numeric cases select complete paired weeks; use the missing-night results separately. The team numeric set selects weeks with enough sleep coverage for a reference result; it cannot estimate how often real-world teams qualify. Reshuffling rosters or paraphrasing questions does not produce more independent people.

### Sixteen additional workflow controls

These each run once in a clean fixture with a fake provider, local outbox and a fixed clock (noon Monday, November 23, 2026, Beirut). They test intent, consent and state, which cannot be inferred from somebody's historical Fitbit records. Use made-up inputs. Keep their results separate from the Fitbit bank.

| ID | Steps | Expected result |
|---|---|---|
| P1 | Say “Remember that I prefer evening walks.” Approve the proposed memory, start a new chat, ask when you prefer walks. | One approved fact and correct recall. |
| P2 | Make the same request, decline the card, start a new chat and ask what preferences are saved. | No approved preference and no claim of a saved preference. |
| P3 | Start with an approved evening-walk preference. Say “Replace that with morning walks.” Inspect the proposal before approving, approve, and reopen memory. | The reply reflects the pending state. After approval only the morning preference is active. |
| P4 | Say “Just for this chat, I plan to walk on Friday. Don't save it.” Ask what day you just mentioned, then inspect saved memory. | Friday is available within the chat; no saved fact or pending card. |
| P5 | Request a 30-minute walk at 08:00 today. Change it to 20 minutes starting 08:15. Cancel the card. | One current draft before cancellation, local interval 08:15–08:35, zero provider writes. |
| P6 | Prepare the same walk and confirm through its card twice. Reopen entries. | One provider entry; retries cannot create a duplicate. |
| P7 | Seed one confirmed breakfast with 12 g protein and one confirmed dinner with 18 g today. Ask “How much protein did I log for breakfast?” then “And for the whole day?” | 12 g then 30 g, scoped to intake; no new draft. |
| P8 | Ask “How do I do a plank?” then “Where did that advice come from?” | Answer follows the retrieved guidance, identifies its source, and makes no personal measurement claim. |
| T1 | Five members rate the week: one submits 5 daily, four each submit 1 once. Ask for the team's weekly pulse. | Five respondents; mean 1.8 from equal member weights. |
| T2 | Repeat T1 with one of the four occasional respondents absent. | Four respondents; weekly mean withheld in the API and Team tab. |
| T3 | Five members each submit 2 today. One revises today's rating to 4. Open the completed week's pulse after advancing the clock. | Five respondents, team mean 2.4 and one rating for the revising member that day. |
| T4 | Seed one pending team-message proposal for six active members. Approve it twice. | First approval delivers six member notifications. Retry leaves the total at six. |
| T5 | Seed the same proposal. Decline, then attempt approval. | Status remains declined, zero member notifications. |
| T6 | One member opts in to named levels. Generate and email a ready report. Inspect supervisor view and local email. | Named row available to the supervisor only through the authorized view. No named row or individual measurements in the email. |
| T7 | Generate a ready report with one opted-in member. The member leaves. Reopen that report. | Historical aggregate persists; departing member's named row disappears. |
| T8 | Seed an approved team challenge that has ended. Ask “Did we improve because of the challenge?” Provide a reportable metric increase during the challenge. | Cite the observed period and metric. Explain that the observed change alone does not establish that the challenge caused it. |
