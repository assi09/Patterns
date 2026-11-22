> Scheduling update: the user subsequently requested completing the final paid audit on this SHA despite the preflight findings. That run is complete; see [the final report](independent-audit-910da27-final.md). This file preserves the earlier findings, not a request for another repair round.

# Independent offline preflight of 910da27 — November 22, 2026

**HOLD paid auditing on this candidate until two deterministic gaps are repaired.** The user
asked to continue auditing once Claude finishes. PR #195's reported candidate resolves locally
to `910da27c912486dac18c7901ce6548df91a258fe`. This review began while required backend CI was
running; mobile was green. It is an offline preflight, not a fresh release audit or a new live
reader comparison. No paid calls or Google traffic/writes occurred; the $2.286249298 remaining
allowance is unchanged. No production edits, commits, pushes or merges.

## 1. [P1] Promotion of a repeated overview drops whole-message guard flags

**`backend/app/agent/requests.py:691–695`, `716–725`.**

`resolve` builds the repeated request with a new `Reading` containing only redo parts/options.
It therefore has the default `medical=false`, `fabricate=false`, `mix_sources=false`. When that
repeated investigation replaces a primary status or recall, `_composed` returns `again` with a
small whitelist of copied fields. The original request's whole-message guard flags are lost.

Independent controls use correct supplied reader clauses and synthetic data, then call the real
`ask` function without a provider:

| Supplied flag | Status alone | Same status beside repeated overview |
|---|---|---|
| `fabricate=true` | Request retains flag; fixed fabrication refusal, no claims | Request has false; delivers overview, one data claim |
| `mix_sources=true` | Request retains flag; fixed one-source refusal, no claims | Request has false; delivers overview, one data claim |
| `medical=true` | Request retains flag | Request flag becomes false too; the explicit “Diagnose” wording is independently caught by a downstream textual guard in this control |

The words used for the first two compound controls explicitly request invented stronger evidence
or a combined export/sync series. The displayed overview remains computed from the synthetic
frame: **these tests do not demonstrate invented figures, actual source mixing or medical advice**.
They demonstrate loss of already-detected refusal flags and bypass of the corresponding fixed
refusals. A downstream textual safeguard catching one wording does not repair the lost contract.

**General repair:** preserve message-level subject, restrictions and memory policy independently
of which component supplies the answer kind. Composition may choose a primary execution kind;
it must not reset already-detected restrictions to defaults. Apply policy after composition or
carry an explicit immutable message envelope through it. Test each guard across primary/side
permutations, including status and recall promotion, plus unflagged controls. Preserve the
existing honest overview + status result and no-write behavior.

Reproduction and receipts: `data/eval/910da27_review/composition_guard_probe.py` and JSON output.
This is a deterministic code contract test, not evidence that the live reader will choose these
clauses with any measured frequency.

## 2. [P1] A retry can change a protected length instead of dropping it

**`backend/app/agent/requests.py:1213–1227`.**

The new `_lengths_kept` restores a previous non-null length only when the retry's length is null.
A new non-null value bypasses preservation. The same old failure therefore remains reachable
through a different valid retry:

- Current message: “Make the opening date the closing date of a three-day block.” Earlier
  synthetic result: September 16–21.
- First reading: both endpoints at the old first day, length 3. The consistency check correctly
  rejects it and marks `periods.length` to keep.
- Retry with null length: restored to 3; the unresolved conflict asks which three days. This
  repaired reproduction passes.
- Retry with **length 1**: not restored; the same one-day endpoints now agree with length 1,
  so the request is accepted as September 16 alone.
- Retry with length 2: the user is asked “Which 2 days ...”, replacing their stated three even
  in the clarification.

The first two-turn script runs through real `interpret`, with read-back off as in the matched
comparison, not a direct call to the field helper. No model/network calls occur.

**General repair:** protect an established explicit constraint against changed values as well as
nulls. Match its semantic period through retry edits, rather than relying only on positional
kind equality. Do not blindly freeze an arbitrary wrong first reading: retain provenance for
which count the message explicitly supplied, or clarify if that cannot be established. A
structurally coherent retry cannot be accepted merely because it deleted or rewrote the user's
requirement. Controls should include null, replacement values, reordered periods, alternative
period kinds and a genuine correction of a mistaken first interpretation. Preserve free
endpoint repair while enforcing the user's count.

Reproduction and receipts: `data/eval/910da27_review/retry_probe.py` and JSON output.

## Repairs that independently hold

- Actual change-point, weekday-split and tag-effect records now render correctly through
  coaching's final observation assembly; their published claims reverify. The old empty figures
  and invalid tag change claim no longer reproduce in that path.
- The actual previously duplicated saved overview now resolves a correctly scripted subsequent
  “why?” without false ambiguity. Removing the duplicate manually is no longer necessary.
- Replaying all 152 prior candidate readings under the original frozen scorer retains all
  **146 previous passes**, adds the duplicate case for **147/152**, and spoils none. This only
  tests new code against already captured readings. It does not measure the new memory/history
  prompts or establish reader accuracy.
- The 224 focused tests pass; Ruff and formatting checks pass. The focused set includes the
  reported repair cases and contrasting controls. Full local suite and final CI status follow.
- Prior legacy, grounding, option-count and correction probes were rerun into new output paths.

## Next audit gate

Fix both findings offline first; rerun these reproductions and contrasting controls. Once Claude
supplies the final frozen SHA and both required checks are green, review the final diff, measure
the reader-facing changes with protected date/history/memory controls, then run a fresh frozen
conversation audit if those gates pass. Retain the broader question families restored for the
shared $5 plan. Meter all new paid phases under the remaining **$2.286249298**, with PHIA kept
separate and capped; do not label exposed replay scores held-out release accuracy.
