# What the request reader actually read on the v4 audit's misses (2026-11-19)

The v4 audit kept only each turn's final request, so a failure could not be put down to the reader
misreading, to code rejecting a good reading, or to a later stage. `eval/reader_replay.py` replayed
only the reader on the 47 failed and partial turns and 11 passing controls, with the context each
turn had (cost $0.0675; [costs.md](costs.md)). Each reading, any retry and its reason were kept.
The expected meaning comes from the frozen conversations and answer key, never from the readings.
These are new readings on the same code: they can reproduce a failure, not recover the original.

## Controls

All 11 passing controls were read correctly on the first attempt: no check sent a good reading back.

## Where the 47 misses come from (about; a few turns have two causes)

| Cause | Turns | Examples |
|---|---:|---|
| **The reading's form**: one flat `Reading` with every domain's fields, all required by the strict schema | ~15 | Placeholder data parts on logging and memory messages (every cold workout draft then asked "which earlier measurement?"); "5 complete days" and "that date and the three before it" written as a one-day `relative` period with `days` set, which that kind ignores; written ranges put on a `calendar` period, which ignores start and end; "remove my goal" read as both forget and `deny`, and deny wins; "repeat the count and say if it's saved" can only be one kind, so the count is lost; no kind for a read-only status question |
| **Code bugs** | 3 (+4 above) | "No higher than 7100" sent back because the comparison check matched "higher than"; polite "Would you remember…?" stopped by the API's `worth_listening`; chat-only recall filtered by the durable-memory test; logging parts resolved as data (the 4 workout drafts above) |
| **Misreadings a prompt can address** | 3 | "What could explain the strongest finding" read as what_changed; a habit suggestion read as guidance; "the first result only" repeating the second |
| **After the reading** (answer writing, retrieval, recall content) | ~10 | Coaching that only recaps; guidance replies failing the wording check; recall content |
| **Cascades** from an earlier failed turn | ~12 | Corrections, "go ahead" and status after a draft that never existed; follow-ups on a failed first question |
| **Read correctly this time** | 5 | The reader is not fully stable; their original cause cannot be recovered |

## What this changes in the plan

The clause design is confirmed as the main fix: per-clause kinds with only their own fields (so a
logging clause cannot carry a data part), a period type per meaning (fixed interval, calendar
period, shift, N days ending on a day with or without it), memory consent separate from the
action, and a read-only status clause. The three code bugs are fixed with it. About a quarter of
the misses are cascades that should clear once the first turn works; they are re-tested, not
fixed separately.
