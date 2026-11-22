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


def code_claim(record: Evidence) -> Claim | None:
    """What one record establishes, in a fixed sentence citing it, and nothing more: the subject
    is its metric, the statement its own statistic, worded for what that statistic means. A
    change point compares the days either side of a split, a weekday split two groups of days,
    a tag effect tagged against untagged days; read as a window comparison, each came out as
    "Steps went up: against ." (the review of e1c1eec). The claim kind is one the record
    supports. None for a record with too little data, a figure missing, or no finding about the
    person's measures (a passage, a habit test, a coverage count)."""
    if not record.metrics or not record.sufficient:
        return None
    say = SAYERS.get(record.tool)
    if say is None:
        return None
    shown = evidence_payload(record)["display"]
    try:
        return say(record, shown, is_significant(record))
    except _Missing:
        return None


class _Missing(Exception):
    """A figure the sentence needs is not in the record."""


def _shown(shown: dict, *keys: str) -> list[str]:
    values = [shown.get(k) for k in keys]
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise _Missing
    return values


def _claim(record, text, kind, direction=None, metric=None) -> Claim:
    return Claim(
        text=_first_up(text),
        kind=kind,
        evidence_ids=[record.id],
        metric=metric or record.metrics[0],
        direction=direction,
    )


def _up(record) -> str:
    return "up" if (record.stats.get("difference") or 0) > 0 else "down"


def _windows(record, shown, significant) -> Claim:
    recent, baseline = _shown(shown, "mean_recent", "mean_baseline")
    name = label(record.metrics[0])
    if significant:
        way = _up(record)
        return _claim(record, f"{name} went {way}: {recent} against {baseline}.", "change", way)
    return _claim(
        record, f"{name} showed no clear change: {recent} against {baseline}.", "no_change"
    )


def _change_point(record, shown, significant) -> Claim:
    before, after, when = _shown(shown, "mean_before", "mean_after", "change_date")
    name = label(record.metrics[0])
    if significant:
        way = _up(record)
        return _claim(
            record,
            f"{name} went {way} around {when}: {after} after against {before} before.",
            "change",
            way,
        )
    return _claim(
        record,
        f"{name} showed no clear shift: {after} after {when} against {before} before.",
        "no_change",
    )


def _weekdays(record, shown, significant) -> Claim:
    weekend, weekday = _shown(shown, "mean_weekend", "mean_weekday")
    name = label(record.metrics[0])
    if significant:
        way = _up(record)
        more = "higher" if way == "up" else "lower"
        return _claim(
            record,
            f"{name}: {more} on weekend days than on weekdays, {weekend} against {weekday}.",
            "change",
            way,
        )
    return _claim(
        record,
        f"{name} showed no clear weekday-weekend difference: {weekend} on weekend days against "
        f"{weekday} on weekdays.",
        "no_change",
    )


def _tagged(record, shown, significant) -> Claim:
    tagged, untagged = _shown(shown, "with_tag", "without_tag")
    name = label(record.metrics[-1])
    if significant:
        # Two groups of days, not a change over time: a value claim, as the verifier allows.
        return _claim(record, f"{name}: {tagged}, against {untagged}.", "value")
    return _claim(
        record, f"{name} showed no clear difference: {tagged}, against {untagged}.", "no_change"
    )


def _trend(record, shown, significant) -> Claim:
    if record.stats.get("slope_per_day") is None:
        raise _Missing
    name = label(record.metrics[0])
    if significant:
        way = "up" if record.stats["slope_per_day"] > 0 else "down"
        word = "upward" if way == "up" else "downward"
        return _claim(record, f"{name} trended {word}.", "change", way)
    return _claim(record, f"{name} showed no clear trend.", "no_change")


def _correlate(record, shown, significant) -> Claim:
    rho = record.stats.get("rho")
    if rho is None or len(record.metrics) != 2:
        raise _Missing
    names = " and ".join(label(m) for m in record.metrics)
    if significant:
        way = "together" if rho > 0 else "in opposite directions"
        return _claim(
            record,
            f"{names} tended to move {way} (correlation {rho:g}).",
            "association",
            "up" if rho > 0 else "down",
            record.metrics[-1],
        )
    return _claim(
        record,
        f"{names} showed no clear link (correlation {rho:g}).",
        "no_change",
        metric=record.metrics[-1],
    )


def _described(record, shown, significant) -> Claim:
    (mean,) = _shown(shown, "mean")
    return _claim(record, f"{label(record.metrics[0])} averaged {mean}.", "value")


SAYERS = {
    "compare_windows": _windows,
    "change_point": _change_point,
    "weekday_split": _weekdays,
    "tag_effect": _tagged,
    "trend": _trend,
    "correlate": _correlate,
    "describe": _described,
}


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
        claims = [c for r in clear if (c := code_claim(r)) is not None]
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
        claims = [c for r in described if (c := code_claim(r)) is not None][:MAX_LISTED]
        if not claims:
            return "", []
        text = (
            f"{_first_up(_when(window, today))} is too short to compare with the days before, so "
            "here is what was recorded: " + " ".join(c.text for c in claims)
        )
        return text, claims
    return "", []
