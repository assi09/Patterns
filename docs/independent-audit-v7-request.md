# Independent audit request: PR #195 after the redesign

> **Historical record** (added to the repository on 2026-11-20), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

**Frozen target: the commit that adds this file.** Verify with
`git log -1 --format=%H -- docs/independent-audit-v7-request.md`; it must equal the PR head and
`git status` must be clean. Nothing is pushed to the PR until the audit is reported. Keep the PR
unmerged.

## What changed since the v6 audit (`9684d77`)

Details are in [typed-requests.md](typed-requests.md#explicit-anchors-instead-of-word-checks-2026-11-20).

- The pattern checks in `backend/app/agent/checks.py` are gone. The reader states what a relative
  period hangs on (`relative_to`: an earlier result or this clause's first period), the source
  (`source`: food log or tracker), whether guidance refers back (`refers_back`), and whether a
  request is medical (`medical`). Code does the date arithmetic.
- Overviews are said by code from their own tests, every clear change named and cited.
- Guidance: the small model's variant pick chooses the exercise passages; only passages the writer
  reports using are cited.
- Memory: the listener runs only when the message tells something about the person.
- The gpt-5.4-nano read-back (`backend/app/agent/readback.py`) is **off**
  (`read_back_enabled = False`); it rejected correct readings in a live slice. Audit it as off.

Claude's own live checks (v7: 226 turns, v8: 94 turns) are development material, graded by the
author, and must not be reused: write new conversations.

## Protocol

- **Fresh paired wording.** Every scenario in two natural wordings, each in its own conversation,
  frozen with its profiles and answer key before the first call. Include minimal pairs that need
  different answers (a shifted range and the next block; food eaten and calories burned).
- **Grade what was delivered and what was stored**: the reply text, its dates, metric, operation
  and source, the evidence the API returns for it after the chat is reopened, and card, action and
  memory state in the database after the turn. A right number for the wrong days fails.
- **Harness clock.** If the frozen-clock harness is reused, advance the clock per call (Claude's
  v8 harness ticks one millisecond per call): with equal timestamps, history in chats of three or
  more turns has no order, and v6/v7 three-turn results may include failures from that.

## Report separately, each with numerator and denominator, partials and failures

1. Investigations (what changed, why, coaching), on changed and flat profiles.
2. Mixed requests (a read beside a log, a status, a memory request; two reads in one message).
3. Food log versus tracker, both directions, including switching back.
4. Memory: remember, recall, forget with cancel and confirm, "don't save", and no candidate from
   a pure question (checked in the store, not only the reply).
5. Workout logging and corrections: duration, day, a paused workout, status.
6. PHIA B1 regression gate, as before, against the stored comparator.

Also report direct metric lookups and adjacent-period follow-ups (openings and follow-ups counted
separately), both-wordings consistency, unnecessary clarifications, and the zero-tolerance gates
in [acceptance-structured-requests.md](acceptance-structured-requests.md).

## Budget

About **$0.96** of the $4 remains ([costs.md](costs.md)). Price the frozen deck, with retries and
the PHIA gate, before the first call, and stop before the cap.

## Known weak spots, not to be designed around

Investigations were 6/12 fully correct in v8 (one read as a comparison of eight measures, one
explanation that was only the fixed limit line). "Just breakfast." was once read as a possible log.
One caffeine answer came from the web instead of the vetted passage.
