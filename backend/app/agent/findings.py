"""Every finding a broad answer states about the person's data, tied to the evidence behind it.

An overview names more metrics than the five claims a submission holds: "time asleep, light sleep,
deep sleep, REM sleep, HRV and recovery score all dropped" was shown with evidence for some of them
only (the v5 audit). Code reads which metrics each clause of the summary names and what it says of
them (went up, went down, held steady), checks that against the overview's own tests or the
answer's verified claims, cites the supporting record for each one, and leaves out a sentence it
cannot support. Nothing here computes a statistic: the records are the overview's.
"""

import re
from collections.abc import Sequence

from app.agent.agent import AgentResult
from app.agent.present import ALIASES, METRICS, label
from app.agent.tools import evidence_payload
from app.agent.verifier import Claim
from app.agent.verifier import _significant as is_significant
from app.analysis.evidence import Evidence

# Other names the answers use for a metric; the catalog labels are read as well.
EXTRA_NAMES = {"calories": "calories"}


def _names() -> list[tuple[str, str]]:
    names = {}
    for metric, info in METRICS.items():
        text = info.label.lower()
        names[text] = metric
        names[re.sub(r"\s*\(.*?\)", "", text).strip()] = metric
    names |= {alias: metric for metric, aliases in ALIASES.items() for alias in aliases}
    names |= EXTRA_NAMES
    return sorted(names.items(), key=lambda item: -len(item[0]))


NAMES = _names()


def named(text: str) -> list[str]:
    """The metrics a piece of text names, longest names first, each once."""
    lowered = text.lower().replace("heart-rate", "heart rate")
    found, taken = [], []
    for name, metric in NAMES:
        for match in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", lowered):
            span = match.span()
            if any(a < span[1] and span[0] < b for a, b in taken):
                continue
            taken.append(span)
            if metric not in found:
                found.append(metric)
    return found


UP = re.compile(
    r"\b(?:rose|risen|went up|up|increased?|increasing|higher|climbed|more|longer|gained|jumped)\b",
    re.IGNORECASE,
)
DOWN = re.compile(
    r"\b(?:dropped|drop|fell|fallen|went down|down|decreased?|decreasing|lower|declined|dipped|dip|"
    r"less|fewer|shorter|slipped)\b",
    re.IGNORECASE,
)
STEADY = re.compile(
    r"\b(?:steady|held|unchanged|stable|flat|similar|the same|no clear|not clearly|didn'?t "
    r"(?:clearly )?(?:change|move|shift)|did not (?:clearly )?(?:change|move|shift)|"
    r"nothing else (?:\w+ )?changed)\b",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+")
CLAUSE = re.compile(r"[;:]|,\s*(?:while|whereas|but)\b|\b(?:while|whereas|but)\b", re.IGNORECASE)


def verdict(clause: str) -> str | None:
    """What a clause says of the metrics it names: "steady" wins over a direction word inside it
    ("did not clearly go up"); with both directions, nothing can be checked but presence."""
    if STEADY.search(clause):
        return "steady"
    up, down = bool(UP.search(clause)), bool(DOWN.search(clause))
    return "up" if up and not down else "down" if down and not up else None


def _agrees(record: Evidence, said: str | None) -> bool:
    if said is None:
        return True
    if "difference" not in record.stats:
        return False  # a description says nothing about a change
    if said == "steady":
        return not is_significant(record)
    rose = (record.stats.get("difference") or 0) > 0
    return is_significant(record) and rose == (said == "up")


def _claim_agrees(claim: Claim, said: str | None) -> bool:
    if said is None:
        return True
    if said == "steady":
        return claim.kind == "no_change"
    return claim.kind == "change" and claim.direction == said


def finding_claim(record: Evidence) -> Claim:
    """The record's finding in a fixed sentence, citing it."""
    metric = record.metrics[0]
    shown = evidence_payload(record)["display"]
    name = label(metric)
    if "difference" not in record.stats:
        mean = shown.get("mean", "")
        return Claim(
            text=f"{name[:1].upper() + name[1:]} averaged {mean}.",
            kind="value",
            evidence_ids=[record.id],
            metric=metric,
        )
    against = f"{shown.get('mean_recent', '')} against {shown.get('mean_baseline', '')} before"
    if is_significant(record):
        way = "up" if (record.stats.get("difference") or 0) > 0 else "down"
        return Claim(
            text=f"{name[:1].upper() + name[1:]} went {way}: {against}.",
            kind="change",
            evidence_ids=[record.id],
            metric=metric,
            direction=way,
        )
    return Claim(
        text=f"{name[:1].upper() + name[1:]} showed no clear change: {against}.",
        kind="no_change",
        evidence_ids=[record.id],
        metric=metric,
    )


MAX_LISTED = 6


def overview_summary(records: Sequence[Evidence]) -> tuple[str, list[Evidence]]:
    """When no sentence of the answer can be supported: the overview's own findings, by code."""
    tested = [r for r in records if r.metrics and "difference" in r.stats]
    clear = sorted(
        (r for r in tested if is_significant(r)), key=lambda r: r.stats.get("overview_rank", 99)
    )[:MAX_LISTED]
    if clear:
        steady = [r for r in tested if not is_significant(r)]
        text = "The clear changes: " + "; ".join(finding_claim(r).text[:-1] for r in clear) + "."
        if steady:
            text += " The other measures showed no clear change."
        return text, clear
    if tested:
        return "Nothing changed clearly over those days.", []
    return "", []


# "The rest looked steady", "everything else held": a claim about every tested metric the answer
# did not name. It was never checked, and was false twice (the v6 audit).
BLANKET = re.compile(
    r"\b(?:the rest|everything else|all (?:the )?other\w*|other (?:measures|metrics|numbers|"
    r"markers|areas)|the remaining\w*|remaining (?:measures|metrics)|nothing else)\b",
    re.IGNORECASE,
)
PIECE = re.compile(r"\s*;\s*")


def cite_findings(result: AgentResult, records: Sequence[Evidence]) -> None:
    """Each metric the summary names gets a claim citing what supports what is said of it; a
    blanket "the rest held steady" is checked against every tested metric it covers. A piece of
    a sentence saying something no record or verified claim supports is left out; the clear
    changes a dropped blanket claim hid are listed with their evidence."""
    if not result.summary or not records:
        return
    by_metric = {r.metrics[0]: r for r in records if r.metrics}
    claims = {c.metric: c for c in result.claims if c.metric}
    mentioned = set(named(result.summary))
    sentences, needed, dropped, blanket_dropped = [], [], 0, False
    for sentence in SENTENCE.split(result.summary.strip()):
        pieces = []
        for piece in PIECE.split(sentence.rstrip(".!? ")):
            ok, cited = _supported(piece, by_metric, claims, mentioned)
            if ok:
                pieces.append(piece)
                needed += cited
            else:
                dropped += 1
                blanket_dropped |= bool(BLANKET.search(piece))
        if pieces:
            end = sentence.rstrip()[-1] if sentence.rstrip()[-1:] in ".!?" else "."
            sentences.append("; ".join(pieces) + end)
    if blanket_dropped:
        hidden = [
            r
            for metric, r in by_metric.items()
            if metric not in mentioned and "difference" in r.stats and is_significant(r)
        ]
        if hidden:
            hidden.sort(key=lambda r: r.stats.get("overview_rank", 99))
            listed = hidden[:MAX_LISTED]
            sentences.append(
                "Also clearly changed: "
                + "; ".join(finding_claim(r).text[:-1] for r in listed)
                + "."
            )
            needed += listed
    if dropped and not sentences:
        text, listed = overview_summary(records)
        if not text:
            return
        sentences, needed = [text], listed
    result.summary = " ".join(sentences)
    have = {i for c in result.claims for i in c.evidence_ids}
    for record in {r.id: r for r in needed}.values():
        result.evidence.setdefault(record.id, record)
        if record.id not in have:
            result.claims.append(finding_claim(record))
            have.add(record.id)
    result.trace.append(
        {"type": "findings_cited", "dropped_pieces": dropped, "cited": len({r.id for r in needed})}
    )


def _supported(piece, by_metric, claims, mentioned) -> tuple[bool, list[Evidence]]:
    cited: list[Evidence] = []
    for clause in CLAUSE.split(piece):
        said = verdict(clause)
        if BLANKET.search(clause) and said is not None:
            # The rest: every tested metric the answer names nowhere, except those named here.
            here = set(named(clause))
            covered = [r for m, r in by_metric.items() if m not in mentioned or m in here]
            if not all(_agrees(r, said) for r in covered if "difference" in r.stats):
                return False, []
        for metric in named(clause):
            record, claim = by_metric.get(metric), claims.get(metric)
            if claim is not None and _claim_agrees(claim, said):
                continue
            if record is not None and _agrees(record, said):
                cited.append(record)
                continue
            return False, []
    return True, cited
