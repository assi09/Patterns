# Smoke run of the clause reader (2026-11-19)

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
