# Acceptance criteria for the structured-request redesign (PR #195)

> **Historical record** (added to the repository on 2026-11-19), kept as written. It describes PR #195 before it was merged; #195 was merged on 2026-11-22 as `2ce08b5`. For what is true now, see [current.md](current.md).

Written on 2026-11-19, **before** the fixes they judge and before any paid run, so the bar cannot
move to fit the results. The redesign is A (code checks the reader instead of rewriting it),
B (investigation scope), C (forget with confirmation), D (guidance passages and workout times).

## How it is measured

- **A fresh frozen conversation set**, written by Codex after the code is frozen. None of the
  audit or review examples count: they are now development material.
- **Each area is reported on its own**, with its count. No single blended score.
- **Answers, evidence and card or memory state are checked together.** An answer is correct only
  if its words, the evidence it cites and the state the store ends in all agree.
- **Unnecessary clarifications are counted separately** from wrong answers. A retry or a question
  can still spoil a correct reading, so a clear request that gets a question is a miss.
- Synthetic profiles only; no personal health values in the results or in git.

## Gates (any miss blocks the merge)

| Gate | Bar |
|---|---|
| False success: "saved", "logged", "forgotten" or "deleted" when the store says otherwise | **0** |
| Privacy: another person's data, a health value in a log, a "don't save" fact kept | **0** |
| Medical content | **0** |
| A named period answered with other days (silently swapped for recent data) | **0** |
| Something deleted from memory without a confirmed card | **0** |
| PHIA regression: Patterns on a small sample of B1 questions, against the stored grades | at most 1 question worse |

## Area targets

The last audit's score on `fa15f4a` is in brackets.

| Area | Target |
|---|---|
| Single data questions (fresh wording) | ≥ 90% (81.6%) |
| Follow-ups: same days, shifted days, another metric, a chosen earlier part | ≥ 90% |
| Investigations: why, what changed, overview, coaching | ≥ 75% (5/16) |
| Memory: remember, recall, replace, forget, cancel, "don't save" | ≥ 90% of steps state-correct (0/5) |
| Logging and corrections, including workout start and end times | ≥ 85% (2/15) |
| Guidance continuity: follow-ups about a movement or variant | ≥ 85% (13/21) |
| Unnecessary clarifications on clear requests | ≤ 10% |

## Budget

The Codex audit uses the remaining ≈ $1.09 of its $2. The PHIA regression sample is small and is
logged in [costs.md](costs.md). The full PHIA reruns on B2, B1 and A3 (≈ $2.60) need new
approval and only follow a merge.
