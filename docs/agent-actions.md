# Agent-assisted logging: tools and intent

Core capability, agreed 2026-10-24; the first local slice is implemented. Build locally first. Food photos remain part of the
intended demo, with editable estimates and provenance. Workout and food logging come first;
hydration is feasible and retained as a later small extension, not a prerequisite. Choose tools
for problems people actually bring to the agent, then evaluate task completion.

## Who decides

Use a hybrid: **Jev classifies; experts prepare; deterministic code authorizes and executes**.
The router keeps topic and request intent separate, in the same Jev call. Nutrition-related input
must not automatically become a food record. The Activity and Nutrition experts select relevant
read tools, ask for missing details and propose a structured draft. The app shows the exact
payload for review. Only an authenticated confirmation of that version can authorize a write.
Neither a classifier label, a tool argument nor a conversational "yes" is execution permission.

| Message (synthetic example) | Intended behavior |
|---|---|
| "How much protein did I eat yesterday?" | Read/compute and answer with evidence; no draft or write. |
| "Log lunch: chicken and rice." | Prepare a draft; ask for time/serving and unresolved food details. |
| "I had chicken and rice." | Clarify whether the person wants to log it or ask about it. |
| "Log lunch and compare my protein with yesterday." | Draft the log and answer the read question separately; unconfirmed food is excluded from the historical total. |
| "Here is a photo of lunch." | Clarify the request; do not infer consent to log. |
| "Undo the last meal." | Resolve the owned entry, show the requested deletion, obtain confirmation, then execute. |
| "Yes" after earlier logging questions | Resolve against a server-held draft; never inherit approval from chat history. |

Intent choices: `read`, `log`, `mixed`, `manage` (edit/cancel/undo), `clarify`. Low confidence means
clarify. The initial 0.7 threshold is provisional, not a measured guarantee. Scope refusal still
wins over any intent or expert selection. When Jev fails, a deliberately narrow keyword rule can
recognise explicit requests; ambiguous statements and follow-ups remain unclear. This is not a
security boundary. Proposal eligibility also needs the current message, owned draft state and
server-side validation, not just the inferred intent.

**Implemented locally:** intent gating; supplied-value food/workout proposal tools; persistent owned
and versioned drafts; confirmation/cancellation/undo APIs; immutable audit snapshots; duplicate
entry identities; durable execution claims; Google create/delete payloads and checked operations;
optional write consent; chat review cards; Data's saved entries; and matching mock behavior.
Logging can work without historical metric data. A pending clarification belongs to the user and
next reply for at most 24 hours; read-only topic changes stop it. General chat confirmations never
execute anything. The first phase handles one entry at a time; photos and inferred values are
not accepted by these proposal tools. The first workout types are running, walking, biking and
aerobic workout; unsupported activities must not be substituted with another type.

Entries must be plausible before anyone can confirm them, checked the same way in the app and the
API: one food entry at most 5,000 kcal and 500 g of each macronutrient; one workout at most 24 hours
and 300 km, at most 25 km/h running, 10 km/h walking or 80 km/h biking over the active time; nothing
dated more than 15 minutes in the future. A draft saved under looser rules is refused at
confirmation before any write. Distance goes to Google in whole millimetres. The review card shows
entries in plain words ("Lunch · Chicken salad", "Sat 24 Oct, 13:00 · 550 kcal · P 40 g") and edits
them with type chips, a date, a time and a duration, in the entry's own time zone.

Real Google writes remain off by default. Fake-provider end-to-end tests and UI click-throughs
pass; two real synthetic model runs prepared drafts without Google writes, with the final run
submitting in two calls. On 2026-10-25 one real food entry was created from the app, read back
from Google and deleted by undo (see [experiments.md](experiments.md#first-real-google-write-and-answers-that-read-like-one-reply-2026-10-25));
one real workout (no distance) was created and undone the same way after PR #57. Reconciliation of pending operations or process crashes
remains a prerequisite to leaving writes on. A refresh reads the saved status;
it does not currently poll Google operations. Food lookup and gram-based serving arithmetic are implemented in `app/outside.py`. PR #195 reads confirmed meal entries. External nutrition-history mapping and deduplication, photo input and hydration are separate work.

**What the tracker recorded is added to a workout** (built after the first real workout write).
When a workout draft is created or saved again, the server reads Google's roll-ups for exactly
that interval, the metrics Fitbit records for that kind of workout (below). It also lists exercises
already recorded over the same time. The result is stored in the draft as `measured`; whatever the
model or the app puts in that field is replaced. Decided with the user:
- **The person's values win**; the tracker fills in the rest (today only distance can conflict).
- **An overlapping exercise is a warning on the card**, not a refusal: logging it would add a
  second workout, but the tracker may have the wrong type.
- **No tracker data** (no heart rate in the interval: not worn, or not synced yet) logs only the
  given values; the card says so and offers "Refresh from Fitbit", which saves the same draft
  again and reads the tracker again. Without heart rate no calories are sent, because Google's
  total calories exist even then, estimated from resting burn.
- Total calories, not active ones: on 8 of the owner's recorded exercises the roll-up over the
  exercise's own interval matched Fitbit's summary exactly for steps, distance and heart rate and
  within 2% for calories, while active calories were 30-50% lower.
- Only the summary is written; no minute-level data, since the tracker already wrote it and a
  summary does not change the daily totals.

**Every workout type, with the metrics Fitbit records for its kind** (PR #59): drafts accept all
181 of Google's exercise types, and each kind of workout gets what Fitbit puts on it. The types,
kinds, field mappings, API details and how each was checked are in [workouts.md](workouts.md).

## Tools to build around user tasks

The table includes implemented proposal/review capabilities and the planned read/estimation
extensions. `propose_food_log` and `propose_workout_log` exist; execution is outside model tools.

| User problem | Tool/capability | Why and boundary |
|---|---|---|
| Understand existing intake | Nutrition history, coverage, compare/trend tools | Finish API nutrition mapping and deduplication; missing data is not zero. |
| Find the food they ate | `find_food`, `get_food`, available serving units | Google food records first; keep candidate IDs, source and serving basis. Confirm ambiguous matches. |
| Adjust a known serving | `scale_nutrients` | Pure unit/serving arithmetic over fetched or user-supplied values; never model arithmetic. Do not convert cups/pieces to grams without a food-specific conversion. |
| Record a meal with known numbers | `propose_food_log` | Preserve supplied energy/macros and missing values. A missing macro is not zero; calorie estimates do not independently verify user input. |
| Record a workout | `propose_workout_log`, existing-session lookup | Resolve time, type and duration; inspect overlap with device sessions before creating another entry. |
| Understand a workout window | built into workout drafts (`app/actions/measure.py`) | Google's roll-ups over the exact interval (steps, distance, total calories, average heart rate) plus overlapping exercises; no heart rate means no tracker data. |
| Record an entry from a photo | `estimate_food`, then food lookup and a draft | Extract candidate foods/portion assumptions; ask about hidden ingredients, amount or preparation when needed. Show uncertainty and allow editing. No invented precision. |
| Fix a draft | `get_draft`, `revise_draft`, `cancel_draft` | Owned server state; revision invalidates prior confirmation. Cancellation before execution makes no remote write. |
| Apply or undo a reviewed action | Confirmed executor, provider reconciliation, delete | Server-controlled operations, absent from the model's unrestricted toolbox. Durable status, IDs and audit; retry only when outcome is known. |
| Record water | `propose_hydration_log` | Later extension using the same approval path, with explicit volume units. |

Start with Google food lookup because the app already connects to Google and its nutrition guide
prefers identified foods. Prototype actual lookup and serving coverage before promising that its
catalogue will find every local dish. USDA FoodData Central is a candidate fallback with food
search and detail endpoints, a separate API key and public-domain data. It does not remove the
need to disambiguate recipes or portions. Do not add another provider until catalogue coverage
shows it is useful. Persist provider IDs and provenance rather than copying a model's recalled
nutrient values. No browsing or arbitrary URL-fetch tool is needed in the agent's runtime.

## Provider findings and corrections to the initial discussion

Research checked 2026-10-24 using primary documentation, without reading personal records:

- Google supports creating workout sessions, nutrition logs and hydration logs with their
  respective write scopes. Request only the capability the person enables; do not expand every
  existing read-only connection automatically. Testing-mode console configuration remains a
  separate manual setup task, not something this research proves for the deployed OAuth client.
- Food and food measurement units are read-only catalogue resources. Identified-food logs refer
  to a food ID and serving; custom/anonymous-food logs supply the nutrient values.
- **Anonymous-food logs are not editable after creation**, according to Google's nutrition guide.
  All drafts can be edited before confirmation. Post-write correction may require a separately
  confirmed replacement/deletion flow; do not promise arbitrary in-place editing or silently
  delete and recreate an entry.
- Create returns an **Operation**, not necessarily a finished DataPoint. Track the returned
  operation and actual completion/error before declaring success or persisting a provider ID as
  confirmed. Batch delete also returns an Operation. A successful HTTP status alone is insufficient.
- The documented create method does not expose a request-id parameter. Do not assume provider
  idempotency. Persist a local execution claim, reconcile ambiguous outcomes and prevent blind
  retry; exactly-once effects during network failure are not established by this documentation.
- Workouts have an interval, exercise type, active duration and optional summary metrics. Raw
  telemetry uses separate data types. Do not write fabricated sensor measurements, mark a manual
  log as sensor-measured, or add a workout summary to daily totals a second time.
- The nutrition examples use kcal for energy and grams for nutrient quantities, including
  sodium. Unit conversion is deterministic and tested; do not send milligrams as grams.

Sources: [Google nutrition/hydration guide](https://developers.google.com/health/data-types/nutrition),
[workout guide](https://developers.google.com/health/data-types/workouts),
[create method](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/create),
[batch delete](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/batchDelete),
[USDA API guide](https://fdc.nal.usda.gov/api-guide/).

## Implementation and evaluation sequence

1. **Built:** intent routing and a task-based tool plan. Scripted tests cover independent topic
   and intent, read-only questions, ambiguous meal/photo statements, mixed requests, explicit
   cancellation/undo, malformed classifier outputs, fallback and medical refusal.
2. **Built with fake-provider validation:** durable owned drafts, versioning, confirmation,
   cancellation, execution claims and audit, with
   migration and additive backend/mobile contract. Fake provider exercises concurrency, restart
   and ambiguous outcomes before any model can propose a remote action.
3. **Built:** workout and supplied-value food proposals and clarification in chat, with review cards and
   local fake-provider execution. Logging must work even when an expert has no historical data.
4. **Partly built:** capability consent and a gated create/undo writer; actual Google validation,
   operation reconciliation, intraday summary evidence,
   nutrition sync and duplicate reconciliation. Real account writes need explicit approval of
   the exact test record and cleanup.
5. Photo input and estimates via the same drafts: consent, validation, retention/deletion, no
   photos in logs, no estimated values represented as measured statistical Evidence. One or two
   paid synthetic-image checks only when model behavior needs verification, logged in costs.
6. Held-out task evaluation: completion/clarification, read-only false-action proposals, ownership
   and unauthorized execution, duplicates, numerical/unit correctness, undo/recovery, cost and
   latency. Compare hybrid routing with expert-only intent decisions before claiming Jev wins.
   Include negation, multiple requests, stale drafts, changed topics and injection in food names.

No approval text is trusted from a photo, food name, imported entry, prior chat message or model.
Proposed actions are not memory facts; their storage, lifecycle and retention need their own rules.
