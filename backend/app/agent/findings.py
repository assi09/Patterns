"""An overview's findings, said by code from the overview's own tests, each cited.

The model's overview prose named more findings than it cited, and claimed "the rest looked steady"
beside clear changes (the v5 and v6 audits). Reading that prose back with word patterns only moved
the problem. An overview is a list of tested results, so code states it: the clear changes in rank
order, each with its figures and evidence, and how many tested measures showed no clear change.
Nothing here computes a statistic: the records are the overview's.
"""

from collections.abc import Sequence
from datetime import date

from app.agent.present import label
from app.agent.tools import evidence_payload
from app.agent.verifier import Claim
from app.agent.verifier import _significant as is_significant
from app.analysis.evidence import Evidence, Window

MAX_LISTED = 8


def _first_up(text: str) -> str:
    return text[:1].upper() + text[1:]


def finding_claim(record: Evidence) -> Claim:
    """The record's finding in a fixed sentence, citing it."""
    metric = record.metrics[0]
    shown = evidence_payload(record)["display"]
    name = _first_up(label(metric))
    if "difference" not in record.stats:
        return Claim(
            text=f"{name} averaged {shown.get('mean', '')}.",
            kind="value",
            evidence_ids=[record.id],
            metric=metric,
        )
    against = f"{shown.get('mean_recent', '')} against {shown.get('mean_baseline', '')}"
    if is_significant(record):
        way = "up" if (record.stats.get("difference") or 0) > 0 else "down"
        return Claim(
            text=f"{name} went {way}: {against}.",
            kind="change",
            evidence_ids=[record.id],
            metric=metric,
            direction=way,
        )
    return Claim(
        text=f"{name} showed no clear change: {against}.",
        kind="no_change",
        evidence_ids=[record.id],
        metric=metric,
    )


def code_claim(record: Evidence) -> Claim | None:
    """What one record establishes, in a fixed sentence citing it, and nothing more: the subject
    is its metric and the statement its own statistic. None for a record that is not a finding
    about the person's measures (a passage, a habit test, a coverage count), which code says
    elsewhere or not at all."""
    if not record.metrics or not record.sufficient:
        return None
    if "difference" in record.stats or (
        record.tool == "describe" and record.stats.get("mean") is not None
    ):
        return finding_claim(record)
    if record.tool == "trend" and record.stats.get("slope_per_day") is not None:
        name = _first_up(label(record.metrics[0]))
        if is_significant(record):
            way = "up" if record.stats["slope_per_day"] > 0 else "down"
            return Claim(
                text=f"{name} trended {'upward' if way == 'up' else 'downward'}.",
                kind="change",
                evidence_ids=[record.id],
                metric=record.metrics[0],
                direction=way,
            )
        return Claim(
            text=f"{name} showed no clear trend.",
            kind="no_change",
            evidence_ids=[record.id],
            metric=record.metrics[0],
        )
    if record.tool == "correlate" and record.stats.get("rho") is not None:
        rho = record.stats["rho"]
        names = " and ".join(label(m) for m in record.metrics)
        if is_significant(record):
            way = "together" if rho > 0 else "in opposite directions"
            return Claim(
                text=_first_up(f"{names} tended to move {way} (correlation {rho:g})."),
                kind="association",
                evidence_ids=[record.id],
                metric=record.metrics[-1],
                direction="up" if rho > 0 else "down",
            )
        return Claim(
            text=_first_up(f"{names} showed no clear link (correlation {rho:g})."),
            kind="no_change",
            evidence_ids=[record.id],
            metric=record.metrics[-1],
        )
    return None


def _when(window: Window, today: date) -> str:
    from app.agent.requested import _when as when

    return when(window, today)


def render_overview(records: Sequence[Evidence], today: date) -> tuple[str, list[Claim]]:
    """The overview as code says it, and its claims; ("", []) with nothing to say."""
    tested = [r for r in records if r.metrics and "difference" in r.stats and len(r.windows) == 2]
    # One measure is one finding however many records test it: an earlier run's record and its
    # version re-adjusted in this run made "39 measures" of 32 metrics (the a196 audit). The
    # latest record of each metric over each pair of periods speaks for it; the statistical
    # family that adjusted them is not changed here.
    latest = {(r.metrics[0], tuple(r.windows)): r for r in tested}
    tested = list(latest.values())
    described = [r for r in records if r.metrics and "difference" not in r.stats]
    if tested:
        focal, baseline = tested[0].windows[0], tested[0].windows[1]
        clear = sorted(
            (r for r in tested if is_significant(r)),
            key=lambda r: r.stats.get("overview_rank", 99),
        )
        steady = [r for r in tested if not is_significant(r)]
        head = f"{_first_up(_when(focal, today))}, compared with {_when(baseline, today)}"
        # Every clear change is named and cited: the first ones with their figures, the rest by
        # name and direction ("1 more measures also changed clearly" was shown uncited, v8).
        claims = [finding_claim(r) for r in clear]
        if claims:
            text = f"{head}, the clear changes were: " + " ".join(
                c.text for c in claims[:MAX_LISTED]
            )
            if overflow := claims[MAX_LISTED:]:
                named = ", ".join(f"{label(c.metric)} ({c.direction})" for c in overflow)
                text += f" Also changed clearly: {named}."
        else:
            text = f"{head}, nothing changed clearly."
        if steady:
            measures = "measure" if len(steady) == 1 else "measures"
            text += (
                f" The other {len(steady)} {measures} tested showed no clear change"
                if claims
                else f" None of the {len(steady)} {measures} tested showed a clear change"
            ) + "; that doesn't prove they stayed the same."
            claims.append(
                Claim(
                    text=f"{len(steady)} {measures} showed no clear change.",
                    kind="no_change",
                    evidence_ids=[r.id for r in steady],
                    metric=steady[0].metrics[0],
                )
            )
        return text, claims
    if described:
        window = described[0].windows[0]
        claims = [finding_claim(r) for r in described[:MAX_LISTED]]
        text = (
            f"{_first_up(_when(window, today))} is too short to compare with the days before, so "
            "here is what was recorded: " + " ".join(c.text for c in claims)
        )
        return text, claims
    return "", []
