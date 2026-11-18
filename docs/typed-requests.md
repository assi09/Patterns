# Structured requests and validation (2026-11-18)

The independent follow-up audit is development material, not a held-out score. Its principal
failure was interpretation: correct tools were often called for the wrong dates or operation,
and correct evidence could still produce an unavailable or contradictory final answer.

Scope authorized by Karim on 2026-11-18, now implemented locally:

- Interpret requests into validated fields, including multiple metrics and operations, explicit
  comparisons, relative dates and references to earlier requests. Calculate calendar offsets in
  code. Ask when a reference has more than one possible subject.
- Preserve data scope and guidance topics independently in the existing private answer trace.
  Do not infer a request's dates from numbers in an assistant's prose.
- Answer supported descriptive requests directly from deterministic evidence. Check complex
  answers against both their request and evidence, including after the repair allowance is used.
- Require relationship and change claims to cite the appropriate statistical tests. Causality
  wording must distinguish an observed association, an inconclusive test and missing data.
- Correct pending drafts rather than leaving stale values on their cards; preserve future dates.
  Read confirmed food logs and keep check-in ratings distinct from derived recovery scores.
- Respect requests not to propose memory and distinguish access limits from medical refusals.

Validation: offline tests for new wording, unrelated intervening turns, ambiguity, calendar
boundaries, missing metrics, comparisons, drafts, food and memory; then the full backend suite.
Any paid validation is separately capped and logged. Future generalization results must come
from new conversations specified before their run, with the final prose reviewed as well as the
tool arguments and evidence. Do not report the old audit as a fresh held-out evaluation.

## Implementation

`backend/app/agent/requests.py` reads the question, registered metric names/units/capabilities,
the user's local date, server draft presence and prior validated request state. It does not get
health rows or computed health values. Constrained function output is parsed into typed fields.
Code resolves relative dates, calendar boundaries and references; checks metric identity,
aggregation capability, threshold units, comparison operators and compatible windows; and asks
when an antecedent is ambiguous. A contradictory aggregation or draft interpretation gets at
most one repair, within a two-call, $0.015 reader budget. An unresolved request never silently
becomes an all-history query.

Data scope and guidance subjects are saved separately inside the existing private `AnswerTrace`
JSON. The API loads traces only through owned messages in the selected conversation. This works
after a new agent instance and requires no database migration or public API/mobile type change.

`requested.py` executes supported precise requests through deterministic analysis and renders
the answer from those same evidence records. Multiple operations remain separate. Descriptive
observations/counts can be reported with sparse data, explicitly as recorded observations;
inferential comparisons retain their minimum sample requirements and share the run's multiple
testing correction. Missing values stay missing; an absent metric is never replaced by another.
Wear limitations accompany recorded activity. Broad investigations and coaching retain the
existing expert loop; its final answer check now runs even after the repair allowance is spent,
and rejected claims cannot survive in the fallback summary. Negative relationship/change claims
must cite the corresponding test.

Confirmed food is read separately from the wearable series, over the requested dates and meal
type, with names and recorded nutrient totals. The former 45-day loading cutoff is removed; wearable start dates do not bound food readback.
Unknown nutrient values do not become zero, and consumed energy is distinct from energy burned.
This is readback of logged entries, not a complete estimate of what the person ate.

For corrections, the model gets the actual owned pending card. The tools enforce a newly stated
duration/day and retain the card's previously validated facts, so changing its date does not
require restating its duration. Only a successfully prepared replacement cancels the prior draft. Multiple waiting
cards require clarification. Tomorrow cannot be moved to today to pass validation. Textual
confirmation still only points to the card: a tap is required for Google execution.

Guidance uses a concrete subject in the retrieval query. When a retrieved exercise title matches
the named variant, other variants are excluded, including short qualifiers such as RKC. The
writer may not borrow instructions from another variant; failed grounding cannot fall back to
the first exercise passage. Sources remain inspectable. Memory opt-outs suppress the listener,
including opt-outs understood by the reader without a fixed English phrase.

## What the live development checks showed

All data in these checks is made up. No Google writes or paid web searches were enabled. Each
plan was written to a new output directory before its first call. Previous results were kept;
new variants were not relabelled as successful reruns. Every captured answer was directly read,
and RAG replies compared with their retrieved passages. No paid model judge was used.

| Stage | Checks | What happened | Reported API cost |
|---|---:|---|---:|
| Initial smoke | 15 (10 answers, 5 reader-only checks) | 14 passed; other-person access was clarified instead of limited; fixed | $0.011193492 |
| First fresh synthetic set | 83 | 72 automated passes; direct review also found a squat cue borrowed from a weighted variant, so one of those passes was partial | $0.061797732 |
| Fresh set after constrained decoding/variant selection | 78 | 75 passed; all 34 initial metric lookups and all 34 date-shift follow-ups passed; multipart, guidance attributes and food intent exposed three further cases | $0.081097904 |
| Four new probes plus replay of those 78 | 82 | All 4 new probes passed; 76/78 regression turns passed. Remaining failures: equality interpreted as a window comparison, and food carrying an extra wearable metric despite correct readback prose | $0.094112192 |
| Final contract regressions | 4 | All passed: strict, inclusive and equal counts, then confirmed breakfast readback with the right food name and consumed energy | $0.006452634 |

Total for this implementation's paid checks: **$0.254653954** across 262 turns/checks. Including
the two earlier independent audits (about $0.4588 and $1.330020434), the requested work remains
at about **$2.04 of the $3 ceiling**. Costs are reported token usage, not an invoice.

The repairs address general contracts rather than enumerating more follow-up wordings:
constrained output shape; additive versus non-additive metrics; a threshold count versus a
two-window change test; actual draft state versus historical food readback; concrete guidance
subjects versus answer-format attributes; and exercise variant identity.

Raw plans, replies, evidence, summaries and the synthetic frame stay in ignored directories
`data/eval/typed_requests_*_2026-11-18/`. Later runs additionally retain the script, implementation
hashes and provider completions for diagnosis. Run a new check explicitly with
`PYTHONPATH=backend .venv/bin/python eval/typed_request_check.py --split <split> --out <new-dir>`.
The script refuses an existing directory; `contract-regression` is a replay, not held out.
All cases currently in that script have now been inspected and are development material. The
historical split names do not make a later rerun a new held-out evaluation.

## Limits and next evidence

Final local verification: `cd backend && ../.venv/bin/ruff check . &&
../.venv/bin/ruff format --check . && ../.venv/bin/pytest -q` — **1,920 passed**.
There are 95 additional tests relative to the 1,825-test starting revision. Focused checks also
exercise an actual replacement card and cancellation of its predecessor, confirmation remaining
a draft, per-account/per-conversation state loading after a new agent instance, reader-service
failure, malformed output, bounded repair, missing data and unsafe fallback rejection. Existing
fixtures that claimed stability from `describe` alone were corrected rather than weakening the
new evidence-type rule. No mobile or public API contract changed.

These are implementation checks by the implementer, not an external blind evaluation. Most
questions are deliberately precise, on a synthetic table; they test metric/period identity and
retrieval, not the plausibility of a person's physiology. The 78-turn score belongs to the
version tested before the later contract repairs. **Do not turn the successful four-turn final
regression into an overall agent accuracy claim.** No final fresh end-to-end score on real
histories has been collected for this architecture.

The old 369-turn independent audit is now development/regression material and was not replayed
in this implementation check. Broad why/coaching questions, complex filters, long conversations,
guidance completeness and arbitrary wording still need a new independent conversation audit.
The existing PHIA results describe their recorded earlier revisions; they are not new results
for this request path. Live Google writes remain outside these checks. Local implementation is
ready for review; deployment and an external final evaluation are separate steps.
