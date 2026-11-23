# Smoke run of the clause reader (2026-11-19)

> **Historical record** (added to the repository on 2026-11-19), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

The first time the real request reader sees the clause schema. Approved with a hard $0.03 cap
from the $2 allowance. Written **before** the run; results are added below it afterwards.

## Turns

20 turns, listed with their expected meaning in [`eval/reader_smoke_expected.json`](../eval/reader_smoke_expected.json):
15 earlier failures or partials of the v4 audit (a pure workout draft, a paused workout, a count
with a save-status question, a status question alone, two metrics with different ranges, two
ranges anchored to an earlier day, five complete days before today, forget beside "don't save",
recall of this chat, a polite remember, "no higher than", "the first result only", an
explanation, a habit suggestion), 3 turns that passed, and 2 standalone controls written for this
run ("yesterday", "the last 7 days"), which regressed in the previous redesign. Each audit turn has
its original context (earlier turns, saved request state, waiting card); the controls have none.

## What counts as clean

A turn is **clean** when the final request has the expected kind and every expected clause:

- each data clause with its metric, operation, both dates and any comparison and threshold;
- a log with its entry kind, day and duration;
- a status question as status, never a confirmation;
- a memory request with its action (and, for recall, its scope);
- an investigation with its focus;

and nothing more: no extra data clause, and no log, correction or confirmation where only a read
was asked. First attempts and retries are counted separately: clean on the first attempt, clean
after one retry, or not clean.

**The run is clean** when the schema is accepted on every call and every turn is clean (after at
most one retry). **Stop before the full audit** if the schema is rejected, or any turn swaps a
period between clauses, drops a clause, or turns a read into a write; that failure is inspected
first.

## Results (added after the run)

**The schema was accepted on every call.** 17 of 20 turns were clean on the first attempt: both
standalone controls, the pure and paused workout drafts, the count beside a save-status question,
the status question alone, two metrics with their own ranges, five complete days, forget beside
"don't save", the polite remember, "no higher than", "the first result only", the explanation, the
habit suggestion and the three passing turns. Every clean clause copied its words exactly.

Three were not, and two met a stop rule:

| Turn | What the reader did | Stop rule | Fix |
|---|---|---|---|
| `calendar_rollover-02/t3` | "That date and the three dates before it" as the same day only: one day answered silently | swapped period | A check for "that date and the N days before/after it": N+1 days ending (or starting) on that date. **Rechecked live: sent back once, then Dec 29 – Jan 1.** |
| `privacy_memory-01/t2` | "What have I told you about riding?" read as remembering the *previous* message, its words copied into `said` | read turned into a write | A clause whose words are not from the current message (under 60% of its words) is sent back; every clean clause had copied its words exactly. Checked offline only: the cap was reached. |
| `calendar_rollover-01/t3` | The same phrase as the same day plus a three-day shift, two periods for one mean, which code turned into a question to the person | none (asked, not answered wrongly) | Two periods for one average are now the reading's error and sent back, not asked. Checked offline only. |

The three real readings are in `backend/tests/test_clauses.py` as regression tests, each followed by
the correct reading. Cost: $0.0299 of the $0.03 cap.

## Live re-check of the two offline fixes (approved, $0.007 cap; spent $0.0062)

Pass conditions were set before running: the memory question must end as recall of this chat with
no remember, replace or forget operation; the date question must end as one four-day window ending
on the referenced date, with first attempt and retry recorded.

| Turn | First attempt | Final | Verdict |
|---|---|---|---|
| `privacy_memory-01/t2` | recall **and** a remember copied from the previous message; sent back by the own-words check | recall, this chat only; no remember, replace or forget | **pass**, after one retry |
| `calendar_rollover-01/t3` | the same day as before; sent back by the around-an-earlier-date check | one window, Feb 26 – Feb 29, 2028 | **pass**, after one retry |

The reader still makes both first mistakes; code catches them before anything is answered or kept.
