# Current state and results

> **Scope change, 2026-11-25:** the app is built around the team feature (two gateways, the
> calendar, an MCP server); the individual side is kept behind a flag, off. See [pivot.md](pivot.md)
> and [escalation.md](escalation.md). The agent results below stand for the code they were measured
> on; they describe the individual side and the analysis tools the team figures share.

**The one page for what is true now.** As of `main` after #235 (2026-11-25). Every result below
names the revision it was measured on and whether it still describes today's code. The history
(audits, plans, negative results, superseded numbers) is kept as it was written, in the documents
listed at the end; where one of them contradicts this page, this page is current.

## What runs now

| Part | Now | Since |
|---|---|---|
| **Product** | **Team first.** Members connect Google Health and join a team; supervisors see the team; HR sees check-in alerts. The individual side (Ask, findings, reminders, smart alarms, memory, logging) is off behind `FA_PERSONAL_FEATURES`; `v0.9-personal` tags the last version with it on | #233, #234, 2026-11-25 |
| **Check-in alerts** | Code only. After each successful sync, for members who opted in; one hour for the person to send or stop; then a nameless notice to whoever holds the supervisor and HR-contact roles, the name on the Check-ins screen only ([escalation.md](escalation.md)) | #235, 2026-11-25 |
| **Calendar** | *Not merged yet*: Google Calendar as daily meeting load, and a team "Meeting load" card (branch `feat/google-calendar`) | — |
| **MCP server, coach** | *Not built yet* ([plan.md](plan.md)) | — |
| Routing | Jev router (`jev-latest`), keyword rule as fallback | — |
| Reading a message | One typed reading per message by the small model (`gpt-5.4-mini`, API default sampling); code resolves dates, references and capabilities. The small-model read-back check exists but is **off** (`read_back_enabled` defaults to False) | #195, merged 2026-11-22 as `2ce08b5` |
| Precise data answers | Deterministic tools build evidence; code writes the answer from it (`app/agent/requested.py`); every number cites an evidence id | #195 |
| Open questions ("why", "how have I been", coaching) | The hybrid: experts inside their area, the general agent for "why", with the experts' notes | #149 |
| Checks | Deterministic verifier on every claim; guard for advice and medical wording | — |
| Memory | Running chat summary; long-term facts only after a tap; "already kept" only when kept in those words; statements in conversation are listened to | #115–#121, #218, #231 |
| Guidance | 1,083 public passages, ranked by embeddings, cited by source | #130–#133 |
| Logging | Food and workout drafts on a card; nothing written without a tap | — |
| Teams | Weekly report with k = 5 aggregates and opt-in named levels, Monday briefing, crunch warning, daily team alerts. **The supervisor chat is retired** (#213): `POST /teams/{id}/chat` no longer exists | #145–#148, #169, #173, #213 |

Added to the reading on 2026-11-23 (all merged): exact missing dates (#217); protected retry
lengths and the message's own flags kept when a repeat leads (#220); "where did that come from?"
answered from the last answer (#221); recall of what was said in this chat, with or without "don't
save" (#223); food follow-ups that change source, meal and nutrient, with "energy" never taken as
food on its own (#225, #229); a calendar week of an earlier result and its weekdays or weekend
(#228). Sentry kept below 3.0 (#222). Statements the router sends to conversation are listened to
again, so a changed fact becomes a replacement card (#231).

## Results, with the revision each was measured on

"Valid now" means the code path the test measured has not changed since in a way that could move
the result. "Changed since" means it has, and the result has not been re-measured.

### Benchmarks and component tests

| Test | Result | Measured on | Valid now? |
|---|---|---|---|
| PHIA, real people, held-out batch B2 (337 questions, 48 people) | Patterns **97.0%** (94.8–98.7) vs single agent 92.3% (p = .0009), chatbot 69.1%, code 99.7%; **re-run on `b3273f8`: 97.9%** (95.8–99.0), the same questions, people and key | 2026-11-17; re-run 2026-11-23 | **Holds** on today's code (#231 since does not touch this path) |
| PHIA, real people, new batch B3 (337 questions never asked, 49 people; the next batch of the same frozen design, which reproduces B1 and B2 item for item) | Patterns **97.6%** (95.4–98.8); single agent 88.7% (Patterns +8.9 points, 38 against 8 questions only one got right, p < .001); chatbot 69.4%; code 99.1% (Patterns −1.5, p = .125) | `b3273f8`, 2026-11-23 | Valid |
| PHIA, PHIA's own users, held-out A1–A3 | about 95% per batch | 2026-11-16/17, before #195 | Changed since, as above |
| Router, 152 held-out questions | **150/152 (98.7%)** vs keyword rule 82.9% | 2026-11-16 | Valid (router unchanged) |
| Guidance retrieval, 35 held-out questions | recall@3 **0.94**, MRR 0.83 | 2026-11-16 | Valid |
| Verifier, 3,184 claims from 61 real people | true claims 1,066/1,066 pass; broken caught **2,117/2,118** | 2026-11-16 | Valid (verifier unchanged) |
| Food matching, 25 held-out foods | **22/25** | 2026-11-16 | Valid |
| Logging, held out (180) | **167/180 (92.8%)**; second held-out after #211: **166/180**, must-not 60/60 | after #195 / after #211 | Valid for logging; food follow-up reading changed in #225 |
| Memory, 20 scenarios, 77 checks | **77/77** | 2026-11-11 | **Did not hold.** Re-run on `b3273f8`: **40/52** personal checks (the 25 team checks used the retired supervisor chat). Same on the commit before the Nov 23 fixes; most of the drop came with #195. With #231: **44/52** |
| Memory, new set of 100 cases (worded by the large model, never seen) | **84/100** with #231; 64/100 without it. Volunteered fact → card 14/15 (1/15 before #231), a kept fact changes → replacement card 14/15 (8/15), remember 19/20, don't save 9/10, recall 8/10 and 9/10, forget 10/10, the same fact again 1/10 | 2026-11-23, `main` and #231 | Valid |
| Real data end to end (PMData) | **82.4%**; on 111 shared questions 84.7% vs chatbot 62.2% | 2026-11-10, restated 11-17 | Changed since (#195 and later); historical |
| Team privacy attacks, team planted changes | 33/33, 6/6 | 2026-11-12 | **Retired feature** (supervisor chat, #213); the weekly report's k = 5 rule is unchanged |

### Check-in alerts

| Test | Result | Measured on | Valid now? |
|---|---|---|---|
| False alarms on calm synthetic people | under **0.5%** of 10,000 weekly windows (100 people) | #235 final commit `19725f9`, 2026-11-25 | Valid |
| Planted extreme week (sleep −3 h and HRV −30 ms for 7 days) | found in at least **95 of 100** | same | Valid |
| What must not raise one | one signal, one bad night, three bad days, missing or partial wear, old data, under 14 days of history: none | same | Valid |
| Privacy and roles | consent to roles; a replaced or demoted HR contact or supervisor loses access at once and gets no reminder; nameless notifications; leaving withdraws at once; one waiting alert per person and team | same, 42 tests, each review finding with a regression test | Valid |
| On real people | **not measured yet**: weekend testing on PMData and LifeSnaps | — | — |

### Conversations (follow-ups)

| Test | Result | Measured on | Valid now? |
|---|---|---|---|
| PR #195 final audit, 592 regression turns + 48 new wordings | fully correct **563/592** (from 504 before); new wordings **42/48** | `910da27`, 2026-11-22 | Superseded in part by the Nov 23 fixes, not re-run |
| Fitbit replay, 492 frozen public-data scenarios | openings **117/117**; complete three-turn conversations **45/117**; "which dates are missing" **0/43** | `31c3ca9`, 2026-11-22 (before #213 and the Nov 23 fixes) | Partly superseded (below). Its team-chat results describe the retired supervisor chat |
| Missing dates through the chat, 20 reserved weeks, fresh wordings | **14/20** by the frozen grader (16/20 counting dates written as ranges) | #217 branch, 2026-11-23 | Valid (merged) |
| Independent bank: 191 cases worded by the large model, read by the real reader | source after guidance **15/15**, after data **9/11** (main 0/26); source negatives 15/15; recall after "don't save" **13/25**, plain **6/15** (main 1/25, 1/15); coverage of one measure 30/30 and food edits 26/30 on main and with the fixes alike | integrated fixes and today's recall wording with calendar weeks, 2026-11-23 | Valid: the merged versions |
| Replay third turns, 219 readings, regression check | heart-rate weekend kept in **59/62** with calendar weeks (dropped in 20/62 on the previous main) | 2026-11-23 | Valid |

### Known limitations now

- **Check-in alerts are tuned on synthetic people only**, until the weekend's run on real people.
- **Fitbit's wear time counts awake hours**, so someone who wears the watch only at night never
  reaches the 10-hour "worn" bar, and the check-in rule cannot fire for them.
- **No emails to HR yet**: check-in notices are in the app only until the HR invitation PR.

- **"That earlier week"** after "and the week before?" is usually read as the opening week: right
  week in 2 of 66 on the small reader, about 60% on the large one; calendar weeks make the days
  right but not the week. The phrase is ambiguous; every precise answer states its dates.
  (`pr-195-followup-issues.md` item 13.)
- **"Those two figures"** after an answer with two results asks which one, by design.
- **Recall** of what was said in the chat is about half right on independent wordings (above).
- **Memory**: a fact said again in other words gets a replacement card rather than "already kept"
  (by design since #218), and 2 of 10 such cases replied "I didn't keep that" to a fact that is
  kept. Memory and coaching questions the reader does not place ("Did I tell you how I get to
  work?", "What time should I aim to go to bed?"), recall from another chat, weekends across a
  month and comparing with the month before still fail in the memory evaluation (8 of 52).
- **Saved-memory questions** such as "what is waiting for my approval?" are often read as entry
  status (6 of 10 on main and with the fixes alike).
- **Not re-measured:** a fresh multi-turn conversation set; a claim of better follow-ups
  overall needs one. PHIA and memory were re-run on 2026-11-23 (above).
- Open items from the #195 backlog: [pr-195-followup-issues.md](pr-195-followup-issues.md), each
  marked fixed, partly fixed or open.

## Where the history is

Living documents, kept current: this page, [status.md](status.md) (the working log),
[plan.md](plan.md), [architecture.md](architecture.md), [typed-requests.md](typed-requests.md),
[test-results.md](test-results.md), [evaluation.md](evaluation.md), [costs.md](costs.md) and
[experiments.md](experiments.md) (both append-only logs), and the feature pages ([teams.md](teams.md),
[agent-actions.md](agent-actions.md), [metrics.md](metrics.md), [workouts.md](workouts.md),
[deployment.md](deployment.md), [monitoring.md](monitoring.md), [api.md](api.md)).

Historical records, each marked at its top with its date and revision: the independent audits and
reviews of PR #195 (`independent-audit-*.md`, `audit-v3-*.md`, `pr-195-*.md`,
`a196c6d-root-causes-and-fix-plan.md`, `acceptance-structured-requests.md`), the reader runs
(`reader-replay-2026-11-19.md`, `reader-smoke-2026-11-19.md`), the Fitbit replay
(`fitbit-replay-results.md`, `evaluation-practice-scenarios.md`), dated plans and logs
(`roadmap.md`, `next-session.md`, `progress-2026-11-17.md`, `testing-plan.md`,
`evaluation-plan.md`), and `eval/results/`.
