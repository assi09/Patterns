# Archived handoff from November 11

This records the pilot proposal at commit `fa845eb`. For current work use the [open issues](status.md#open-issues)
and [plan](plan.md). Stored traces, thumbs, the aggregate pilot report and owner-operated account deletion
shipped after this handoff. The November 17 [pilot record](progress-2026-11-17.md) supersedes the proposed dates and caps below.

## Agreed with Karim on 2026-11-11

**The pilot.** Karim emails 10-12 testers on 2026-11-12; not all may join.
- Lasts **10 days**, budget **$40** (Karim and Jad share it).
- At least 5 people in **one team** who sync; 8 or more makes alerts likelier.
- Daily caps for it would be `FA_CHAT_DAILY_CAP_PER_USER_USD=0.25` and
  `FA_CHAT_DAILY_CAP_TOTAL_USD=3.50` on the Railway `api` service. **Still 0.30 and 3.00: do not
  change them until Karim says so** (it restarts the API).
- Testers need a Fitbit or Pixel Watch, must be added as Google test users (Testing mode, 7-day
  sign-ins), and are asked to do the morning check-in every day.
- The invitation says: their Fitbit data and questions are stored and analysed to measure the app;
  results are reported only as totals, never by name or with their values; the team may read
  answers to check them (optional sentence); everything is deleted on request at the end.
- Karim also sets a budget limit in the OpenAI dashboard and checks with Jad on the Failure Matrix,
  threat model and red team.

**Their data is used, only aggregates leave the database.** Analysis runs on their real data;
only totals and rates go to `eval/results/` and the report. People are "person 1, 2, ...".
Postgres on Railway has **no public port** (checked): run the report script inside the `api`
service, which already has the database. Never copy their health data to a laptop or into git.

## Build, in this order, before testers join

1. **Stored traces per answer.** Today `ChatMessage` has `run_id` and `cost_usd`, but the trace it
   points to lives in memory and is lost on restart. Store per answer: latency (total and per
   step), stop reason (answered, answered in part, budget, failed checks, refused), number of
   model and tool calls, tool errors, repair rounds, verifier rejections. Migration, tests, and the
   team agent's answers too (`TeamChatMessage`). This is also the AgentOps deliverable (15%).
2. **Thumbs up or down on answers** in the Ask screen (and the team chat): stored per message,
   API, `types.ts`, mock, `http.ts`, hooks, light and dark checked.
3. **Pilot report script** (`eval/pilot_report.py` or similar) that prints only aggregates:
   - accuracy of the agent's claims against the independent oracle (`eval/oracle.py`) on each
     person's own data;
   - questions per person per day, question types (from the router), success rate, refusals,
     latency, cost;
   - thumbs-up rate; alerts marked useful; reminders and memory cards kept;
   - recovery score against morning check-ins (a first look; about 10 per person);
   - team: alerts raised, proposals approved or declined.
   Tested on a made-up database first.
4. **Then the "why" fix** (issue 33): code tests every likely cause before and after the change,
   and scores may not be explained by their own inputs in `compare_windows`. Retest on the same 33
   why questions plus no-cause controls, about $1, with the rule in plan.md set before the run.

Account deletion was outstanding at the time of this proposal. The owner CLI now handles deletion requests.

## Still open with Karim

- The team consent wording: "stress" or "physical stress signs" (issue 34). Changing it means
  asking members again.
- After the above: team agent evaluation (scripted, privacy attacks, alerts on PMData), the team
  screens on the real backend, blind grading (Karim and Jad), then report, poster and demo
  (presentations on 2026-12-05).
- If time runs short, drop in this order: the agent-written weekly team report, phone push, the
  router held-out test. Personal experiments stay on hold.
