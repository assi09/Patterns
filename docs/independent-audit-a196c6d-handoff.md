# Independent live audit of PR 195 at a196c6d

November 21, 2026. **Hold the merge.** The evidence-version fix worked across successive live investigations. The agent also answered all 24 direct metric questions and all eight exercise-guidance turns correctly. Nine date follow-ups silently returned other dates, and neither wording of a date-only correction to a paused workout produced the requested card.

## Results

| Area | Full | Partial | Fail | Both wordings fully correct |
|---|---:|---:|---:|---:|
| metric openings | 24/24 | 0 | 0 | 12/12 |
| adjacent follow-ups | 15/24 | 0 | 9 | 4/12 |
| guidance | 8/8 | 0 | 0 | 4/4 |
| food | 7/8 | 0 | 1 | 3/4 |
| investigations | 6/16 | 6 | 4 | 1/8 |
| workout | 4/6 | 0 | 2 | 2/3 |
| All conversations | 64/86 | 6 | 16 | 26/43 |

All 86 HTTP turns completed. Strict full-pass rate was 74.4%; both natural wordings passed for 60.5% of paired turns. Two clear requests elicited unnecessary clarification. Grades include what the app actually said, cited dates and source, and database state. A candid refusal to make a requested correction earns a failure for execution but is distinguished from a false claim of success. Asking for three options could earn full credit with fewer if the answer explained the limitation and preserved the scope. General guidance was allowed when properly sourced and labelled.

## What changed in practice

**Evidence after reopening.** In a separate API session with the in-memory evidence cache empty, I reopened all 86 messages under their original owners and fetched all 316 citation occurrences. The text, ID lists and every evidence payload matched the originating turn, including windows, n, sufficiency, adjusted p-value and test count. For a versioned ID I compared the returned content to the actual source record cited by that turn, including when the source itself was an older version. All 21 versioned citation occurrences matched. Fourteen used an adjustment across 39 tests where the original used 32, five used 37 instead of 32, and the other two used three and five. The original payloads stayed accessible. This directly exercises the mismatch on b730fda.

**Follow-up dates.** There were 12 metrics, two phrasings and four calendar operations. Starting a four-day block immediately *after* the old interval passed 6/6. Ending a four-day block immediately *before* it passed 3/6. Keeping the endpoint and narrowing to its final three days passed 3/6. Starting a four-day block on the old interval's second day passed 3/6. Examples:

- Both phrasings for the forward-adjacent block now worked across their three metrics. In contrast, “Back up to the day just before that stretch began. Give the four-day average ending there” failed on all three. The equivalent “Use four days up to, and including, the date immediately before the first date you used” passed all three.
- For resting heart rate, “Move one day on from the first date; that day is day one of my new four-day average” resolved as a shift of the entire five-day interval. The trace selected `relative/previous`. For one preceding-block failure the trace selected `rolling/today`. The new representation can express the intended intervals. The normal reader still selects competing operations or the wrong anchor.
- Preserve a changed length even if the anchor implies a shift. Check whether a proposed result satisfies the requested length, reference edge and direction. Full-adjusted arithmetic tests alone cannot catch a valid calculation on the wrong window.

**Investigations and coaching.** The clear-change overview named and cited changes, and the flat overview distinguished lack of a clear change from proof of stability. An honest “none of the habits tested” was supported on the requested interval in two single-option coaching turns. Other answers lost context or overstated what the underlying habit record tested:

- On both flat-profile explanation turns the answer counted 39 test records as “39 measures.” They represented 32 distinct metrics over the same two periods. Deduplicate by metric and comparison scope for a claim about the number of measures. Preserve the actual test count separately for statistical adjustment.
- The reverse-order comparison explicitly labelled both periods, so it received partial credit on the changed profile. Its follow-up described steps going down and sleep going up without dates, reversing the chronological change. Keep a consistent earlier/later orientation when summarizing direction.
- A three-ideas follow-up silently expanded October 10–30 to September 2–October 31. Other turns gave one option without accounting for the requested remainder. No turn demonstrated a successful top-up with three distinctly labelled and sourced options. One request about how to format the current answer also created two unsolicited memory candidates. Neither was approved.
- One answer recommended a wind-down routine because sleep efficiency was better on days without a stress tag. The citation was real, but the data tested the tag, not the routine. The mapping originates in `backend/app/analysis/coaching.py`. An observational stress split can justify describing or monitoring the association; a separately sourced general wind-down suggestion should not be presented as something tested on the person's days.

**Food, workouts and guidance.** Both food chains returned the right breakfast for October 17 and then the distinct confirmed breakfast for October 16. Both excluded the pending entry. One tracker-switch request still asked which measurement was meant even though the immediately preceding turn established energy. Both paused-workout creations stored 38 active and 50 elapsed minutes correctly. On moving the workout by one day, one wording silently turned the 12-minute pause into active time; the other acknowledged that it could not update the draft. Both status answers reflected the store. For a date-only correction, validate that all untargeted fields match the prior card, including elapsed and active durations separately. All eight bodyweight bridge and standard push-up turns used the relevant plain-variant passage and retained it on follow-up.

## Method, cost and limits

GitHub PR head and clean execution checkout both matched `a196c6d58631651ee195df94ec3cafa476520cb1`. The required backend and mobile checks were green. The questions, grading criteria, source frames, answer key and runner were frozen before the first paid call (bundle `a32d92950be8aac642a21792a25d664a0c01efe69e8a7464b2ff0e02bfbd04d4`). The audit used 36 synthetic chats, independently executed paired wording, a ticking test clock, real reader and verifier calls, isolated SQLite state, and disabled Google writes. The previous B1 gate was outside this focused run; its 24/24 belongs to b730fda. The deck is weighted toward earlier failure families, so its overall percentage is not a population estimate or a measured before/after improvement.

Independent recomputation agreed on all 4,444 checked numerical evidence fields. Wrong-window answers still failed. No paid retries of the deck or product changes were made. Actual cost was **$0.286983744**, below the $0.59 cap. Approximately **$0.3133** remains of $4. Full per-turn questions, answers, source-row expectations, citations, state and reasons are local under `data/eval/a196_review/reviewed_turns.md`. Raw inputs and results remain in git-ignored directories; `reopen.json` and `versions.json` retain the persistence checks.
