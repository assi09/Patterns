"""Deterministic checks on every claim the agent makes, before anyone sees it.

A claim must cite evidence that exists and had enough data. What it asserts must hold in that
evidence: a change or an association must be significant and in the stated direction, every number
in the sentence must come from the cited statistics (allowing rounding and minutes/hours), every
date must fall inside the cited windows, every metric the sentence names must be covered by the
cited evidence, and the wording must not contradict the direction. Claims must not diagnose,
overstate causation, or reason about calorie balance from Fitbit's estimates.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.agent.present import label
from app.analysis.evidence import Evidence
from app.analysis.screen import benjamini_hochberg

ALPHA = 0.05

ClaimKind = Literal[
    "change", "association", "no_change", "data_quality", "day", "suggestion", "value", "guidance"
]
Direction = Literal["up", "down"]


class Claim(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    kind: ClaimKind
    evidence_ids: list[str] = Field(min_length=1)
    metric: str | None = None  # the metric the claim is about
    direction: Direction | None = None  # for change and association claims

    @field_validator("direction", mode="before")
    @classmethod
    def _no_direction(cls, value):
        """ "steady" or "none" is no direction: the verifier then says what is missing, instead of
        the whole submission failing to parse five times over one field (memory evaluation)."""
        return value if value in ("up", "down") else None


class Hypothesis(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    status: Literal["supported", "refuted", "inconclusive"]
    evidence_ids: list[str] = Field(default_factory=list)


class Submission(BaseModel):
    """What the agent hands in at the end of a run."""

    summary: str = Field(max_length=700)
    claims: list[Claim] = Field(max_length=5)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=12)


@dataclass(frozen=True)
class Rejection:
    claim: Claim
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Verdict:
    accepted: tuple[Claim, ...]
    rejected: tuple[Rejection, ...]


MEDICAL = re.compile(
    r"\b(diagnos\w*|disease|disorder|syndrome|apnea|insomnia|arrhythmia|a-?fib|atrial|infection|"
    r"depress\w*|prescri\w*|medication|dosage|treatment)\b",
    re.IGNORECASE,
)
# Advice anyone could read anywhere. An answer must speak to this person, or say nothing.
# How the answer was made, or what it cannot do, in place of the advice that was asked for.
ABOUT_ITSELF = re.compile(
    r"\bI (?:can'?t|cannot|can not) (?:give|offer|provide)\b|evidence[- ]based|tested habits?\b|"
    r"\b(?:with|in) this run\b|\bthe test run\b|\bthis many (?:checks|tests)\b|"
    r"\bthe person (?:asked|wants|said|has)\b|^\s*Asked when\b",
    re.IGNORECASE,
)
UNMETERED = ("memory", "food_log", "knowledge")  # about the person or the world, not one metric
YOUR_DATA = re.compile(
    r"\byour (?:sleep|steps?|heart|hrv|recovery|bedtime|strain|data|numbers?|efficiency|average)\b",
    re.IGNORECASE,
)
GENERIC_ADVICE = re.compile(
    r"\b(balanced diet|eat(?:ing)? (?:well|healthy|healthier)|stay(?:ing)? hydrated|drink(?:ing)? "
    r"(?:more|enough|plenty of) water|get(?:ting)? enough (?:sleep|rest)|sleep hygiene|"
    r"(?:deep|slow|calming) breath\w*|breathing exercises?|take (?:a|some) deep|"
    r"(?:aim for|get|getting|at least) (?:7|8|9|seven|eight|nine)(?:(?:-| to )\d)? hours|"
    r"listen to your body|(?:reduce|manage|managing|reducing) (?:your )?stress|"
    r"healthy (?:lifestyle|habits)|exercise regularly|regular exercise|stay active|"
    r"mindfulness|meditat\w*|good night'?s sleep)\b",
    re.IGNORECASE,
)
# A suggestion is an option the person may take up, never an order.
OPTION_WORDS = re.compile(
    r"\b(could|might|may|try|trying|consider|option|if you want|aim(?:ing)?|worth)\b", re.I
)
ORDER_WORDS = re.compile(r"\b(you should|you must|you need to|make sure (?:to|you))\b", re.I)
CAUSAL = re.compile(
    r"\b(caused|causes|causing|because of|due to|led to|leads to|results? in|proves?)\b",
    re.IGNORECASE,
)
ENERGY_BALANCE = re.compile(
    r"\b(calorie (?:deficit|surplus|balance)|caloric (?:deficit|surplus)|net calories|"
    r"energy (?:balance|deficit|surplus)|burn(?:ed|t)? more than you (?:eat|ate))\b",
    re.IGNORECASE,
)
DOWN_WORDS = re.compile(
    r"\b(drop\w*|fell|fall\w*|decreas\w*|declin\w*|lower\w*|reduc\w*|shorter|less|fewer|down)\b",
    re.IGNORECASE,
)
UP_WORDS = re.compile(
    r"\b(ris(?:e|en|ing)|rose|increas\w*|higher|grew|grow\w*|longer|more|climb\w*|up)\b",
    re.IGNORECASE,
)

ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
MONTH_DAY = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.? (\d{1,2})\b", re.I
)
DAY_MONTH = re.compile(
    r"\b(\d{1,2}) (" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b", re.I
)
BARE_HOUR = re.compile(r"\b(\d{1,2})\s*([ap])\.?m\b\.?", re.IGNORECASE)
CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?(?![\w:])", re.IGNORECASE)
DURATION = re.compile(
    r"(?<![\d.,])(\d+)\s*(?:h|hr|hrs|hours?)\b(?:\s*(?:and\s*)?(\d+)\s*(?:min|mins|minutes?)\b)?",
    re.IGNORECASE,
)
# Internal column names (sleep_minutes, hrv_ms...) must not reach the person.
COLUMN_NAME = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
# Evidence ids (12 hex characters) belong in `evidence_ids`; in the text they read as numbers.
EVIDENCE_ID = re.compile(r"\b(?=[a-f]*\d)[0-9a-f]{12}\b")
# How sentences name metrics, so a sentence cannot describe one no evidence covers. Only distinctive
# terms: generic words ("sleep", "activity") would match sentences about other metrics.
MENTIONS = {
    metric: re.compile(pattern, re.IGNORECASE)
    for metric, pattern in {
        "hrv_ms": r"\bHRV\b|heart rate variability",
        "resting_hr": r"resting heart rate|\bRHR\b",
        "respiratory_rate": r"breathing rate|respiratory rate",
        "skin_temp_variation_c": r"skin temperature",
        "readiness": r"\breadiness\b",
        "steps": r"\bsteps\b",
        "distance_km": r"\bdistance\b",
        "active_zone_minutes": r"active zone minutes|\bAZM\b",
        "cardio_load": r"cardio load",
        "calories": r"calories burned",
        "sedentary_minutes": r"\bsedentary\b",
        "lightly_active_minutes": r"light activity",
        "moderately_active_minutes": r"moderate activity",
        "very_active_minutes": r"vigorous activity",
        "wear_minutes": r"wear time",
        # "You slept less" is about time asleep as much as "time asleep" is.
        "sleep_minutes": r"time asleep|\bslept\b|sleep duration|hours of sleep",
        "time_in_bed": r"time in bed",
        "sleep_efficiency": r"sleep efficiency",
        "sleep_score": r"sleep score",
        "deep_sleep_minutes": r"deep sleep",
        "light_sleep_minutes": r"light sleep",
        "rem_sleep_minutes": r"\bREM\b",
        "awake_in_bed_minutes": r"time awake|awake in bed",
        "bedtime_hour": r"\bbedtimes?\b",
        "recovery_score": r"recovery score",
        "strain": r"\bstrain\b",
        "stress_score": r"\bstress\b",
    }.items()
}
NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")


TEST_TOOLS = ("compare_windows", "change_point", "trend", "correlate", "weekday_split")
CHANGE_TOOLS = ("compare_windows", "change_point", "trend")  # whether a measure moved
RUN_ADJUSTED = "p_value_run_adjusted"


def _base_p(evidence: Evidence) -> float | None:
    """The p-value as its tool or the screen reported it (corrected for the screen's metrics or a
    correlation's lags where they apply)."""
    stats = evidence.stats
    return stats.get("p_value_adjusted", stats.get("p_value"))


def _p(evidence: Evidence) -> float | None:
    """The p-value a decision rests on: corrected for the run's tests when the run set one."""
    return evidence.stats.get(RUN_ADJUSTED, _base_p(evidence))


def _significant(evidence: Evidence) -> bool:
    p = _p(evidence)
    return p is not None and p < ALPHA


def run_adjusted(tests: list[Evidence]) -> list[Evidence]:
    """The run's own tests with Benjamini-Hochberg adjusted p-values, judged together.

    An agent tests many things per run; without this, more than half of runs on a person where
    nothing changed reported something (eval/multiple_testing.py: 56%, and 6% with it, while
    planted changes were still found 92-98% of the time). Each copy keeps its id and its raw
    p-value, and records the adjusted value and how many tests it was adjusted for.
    """
    usable = [e for e in tests if e.tool in TEST_TOOLS and _base_p(e) is not None]
    if not usable:
        return list(tests)
    q = dict(
        zip((e.id for e in usable), benjamini_hochberg([_base_p(e) for e in usable]), strict=True)
    )
    return [
        e.model_copy(
            update={"stats": {**e.stats, RUN_ADJUSTED: round(q[e.id], 6), "tests_in_run": len(q)}}
        )
        if e.id in q
        else e
        for e in tests
    ]


def _sign(evidence: Evidence) -> float | None:
    """Which way the evidence points: positive is up, or a positive association."""
    for key in ("difference", "slope_per_day", "rho"):
        value = evidence.stats.get(key)
        if value is not None:
            return value
    return None


def _numbers_in(value) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int | float):
        return [float(value)]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers_in(v)]
    if isinstance(value, list | tuple):
        return [n for v in value for n in _numbers_in(v)]
    return []


LEVEL_KEYS = (
    "target",
    "total",
    "per_week",
    "mean",
    "median",
    "min",
    "max",
    "mean_recent",
    "mean_baseline",
    "mean_before",
    "mean_after",
    "mean_weekend",
    "mean_weekday",
    "value",
    "usual_median",
    "usual_low",
    "usual_high",
    "split_at",
    "best_bedtime",
    "worst_bedtime",
)

# Statistics expressed in the metric's own unit, which may be quoted in a related unit.
VALUE_KEYS = (
    "total",
    "per_week",
    "mean",
    "median",
    "sd",
    "min",
    "max",
    "difference",
    "mean_recent",
    "mean_baseline",
    "mean_before",
    "mean_after",
    "mean_weekend",
    "mean_weekday",
    "slope_per_day",
    "slope_low",
    "slope_high",
    "change_over_window",
    # Team reports (app/analysis/team.py)
    "median_change",
    "change_q1",
    "change_q3",
    "median_deviation_by_weekday",
)


def _conversions(metric: str) -> tuple[float, ...]:
    """Factors from a metric's unit to the units a sentence may use for it."""
    if metric.endswith("_minutes") or metric == "time_in_bed":
        return (1, 1 / 60)  # minutes, hours
    if metric.endswith("_hour"):
        return (1, 60)  # hours, minutes
    return (1,)


def _allowed_numbers(cited: list[Evidence]) -> list[float]:
    """Every number a sentence may quote from the cited evidence, in the units people use."""
    allowed: list[float] = []
    for evidence in cited:
        factors = {f for metric in evidence.metrics for f in _conversions(metric)}
        for key, value in evidence.stats.items():
            numbers = [abs(n) for n in _numbers_in(value)]
            if key in VALUE_KEYS:
                allowed += [n * f for n in numbers for f in factors]
            elif key == "fraction_present":
                allowed += [n * 100 for n in numbers] + numbers  # shares as percentages
            else:
                allowed += numbers
        if evidence.tool == "knowledge":  # a passage's own numbers, as its text gives them
            text = str(evidence.stats.get("text", ""))
            allowed += [n for n, _ in _quoted_numbers(text)] + _quoted_durations(text)
        allowed.append(float(evidence.n))
        for window in evidence.windows:
            allowed += [float(window.days), window.days / 7]
    return allowed


def _quoted_numbers(text: str) -> list[tuple[float, int]]:
    """Numbers in a sentence with their decimal places, ignoring dates, times and durations."""
    text = EVIDENCE_ID.sub(" ", text)
    text = ISO_DATE.sub(" ", text)
    text = MONTH_DAY.sub(" ", text)
    text = DAY_MONTH.sub(" ", text)
    text = CLOCK.sub(" ", text)
    text = DURATION.sub(" ", text)
    found = []
    for match in NUMBER.finditer(text):
        raw = match.group().replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        found.append((abs(float(raw)), decimals))
    return found


def _matches(number: float, decimals: int, allowed: list[float]) -> bool:
    for value in allowed:
        tolerance = max(0.5 * 10**-decimals, 0.025 * abs(value))
        if abs(number - value) <= tolerance + 1e-9:
            return True
    return False


def _quoted_durations(text: str) -> list[float]:
    """Durations written as hours and minutes ("7 h 12 min", "2 hours"), in minutes."""
    return [int(h) * 60 + int(m or 0) for h, m in DURATION.findall(text)]


# Words that name one statistic, and the evidence keys that hold it. A number after one of them, in
# the same clause, must be that statistic: "your average was 9,800" when 9,800 is the highest day
# passed, because the check only asked whether the number was somewhere in the evidence (0 of 163
# such swaps caught on real people's claims, 2026-11-16).
STATISTIC_WORDS = (
    (
        re.compile(r"\b(?:usual|normal|typical) range\b|\busual(?:ly)?\b", re.I),
        "the usual range",
        lambda key: key.startswith("usual"),
    ),
    (
        re.compile(r"\baverag\w*|\bmean\b", re.I),
        "the average",
        lambda key: "mean" in key or key == "per_week",
    ),
    (
        re.compile(r"\b(?:highest|maximum|max|peak\w*)\b", re.I),
        "the highest",
        lambda key: key in ("max", "highest", "maximum"),
    ),
    (
        re.compile(r"\b(?:lowest|minimum|fewest)\b", re.I),
        "the lowest",
        lambda key: key in ("min", "lowest", "minimum"),
    ),
    (
        re.compile(r"\b(?:total\w*|in all|altogether)\b", re.I),
        "the total",
        lambda key: key in ("total", "per_week"),
    ),
    (re.compile(r"\b(?:median|middle)\b", re.I), "the median", lambda key: "median" in key),
)
# Where a word's reach ends: a sentence or clause, but not the point of "7.5" or comma of "9,800".
CLAUSE_END = re.compile(r"[.;!?](?!\d)|,(?!\d{3})|\b(?:but|while|whereas|although)\b", re.I)
OTHER_LEVELS = ("highest", "lowest", "maximum", "minimum")


def _blank(pattern: re.Pattern, text: str) -> str:
    return pattern.sub(lambda m: " " * len(m.group()), text)


def _figures(text: str) -> list[tuple[int, float, int]]:
    """Each number and duration in a sentence with its position and decimals; dates, clock times
    and evidence ids left out. Durations are in minutes."""
    for pattern in (EVIDENCE_ID, ISO_DATE, MONTH_DAY, DAY_MONTH, CLOCK):
        text = _blank(pattern, text)
    found = [
        (m.start(), int(m.group(1)) * 60 + int(m.group(2) or 0), 0) for m in DURATION.finditer(text)
    ]
    text = _blank(DURATION, text)
    for m in NUMBER.finditer(text):
        raw = m.group().replace(",", "")
        found.append((m.start(), abs(float(raw)), len(raw.split(".")[1]) if "." in raw else 0))
    return sorted(found)


def _level_values(cited: list[Evidence], wanted) -> list[float]:
    values: list[float] = []
    for evidence in cited:
        factors = {f for metric in evidence.metrics for f in _conversions(metric)}
        for key, value in evidence.stats.items():
            if wanted(key):
                values += [abs(n) * f for n in _numbers_in(value) for f in factors]
    return values


def _scopes(text: str) -> list[tuple[int, int, str, Callable[[str], bool]]]:
    """Each statistic word's reach: from the word to the next one or the end of its clause."""
    words = sorted(
        (m.start(), m.end(), said, wanted)
        for pattern, said, wanted in STATISTIC_WORDS
        for m in pattern.finditer(text)
    )
    scopes = []
    for i, (_, end, said, wanted) in enumerate(words):
        stop = words[i + 1][0] if i + 1 < len(words) else len(text)
        if boundary := CLAUSE_END.search(text, end):
            stop = min(stop, boundary.start())
        scopes.append((end, stop, said, wanted))
    return scopes


def wrong_statistic(text: str, cited: list[Evidence], day: bool = False) -> list[str]:
    """Numbers quoted as one statistic that are another: the average given the highest day's value.
    Only a number that is a different level in the evidence is rejected; a change's size, a count
    of days or a window's length after "average" is left to the other checks. In a claim about one
    day, a number no statistic word governs must be the day's own value."""
    levels = set(LEVEL_KEYS) | set(OTHER_LEVELS)
    scopes, figures = _scopes(text), _figures(text)
    if day:
        free = [(0, len(text), "the day's value", lambda key: key == "value")]
        governed = [f for f in figures if any(start <= f[0] < stop for start, stop, *_ in scopes)]
        figures_free = [f for f in figures if f not in governed]
    problems = []
    for start, stop, said, wanted in scopes + (free if day else []):
        right = _level_values(cited, wanted)
        if not right:
            continue  # nothing cited holds that statistic: the other checks decide
        other = _level_values(cited, lambda key, wanted=wanted: key in levels and not wanted(key))
        pool = figures_free if said == "the day's value" else figures
        for at, number, decimals in pool:
            if not start <= at < stop or _matches(number, decimals, right):
                continue
            if _matches(number, decimals, other):
                problems.append(f"quotes another statistic as {said}: {number:g}")
                break
    return problems


def _quoted_clock_times(text: str) -> list[float]:
    """Times of day ("23:30", "11:30 pm"), as hours relative to midnight (23:30 -> -0.5)."""
    times = []
    for h, meridiem in BARE_HOUR.findall(text):  # "7am", "10 pm"
        hours = int(h) % 12 + (12 if meridiem.lower() == "p" else 0)
        times.append(hours - 24 if hours >= 12 else hours)
    for h, m, meridiem in CLOCK.findall(text):
        hours = (
            int(h) % 12 + (12 if meridiem.lower().startswith("p") else 0) if meridiem else int(h)
        )
        value = hours + int(m) / 60
        times.append(value - 24 if value >= 12 else value)
    return times


def _clock_levels(cited: list[Evidence]) -> list[float]:
    """The times of day the cited evidence holds: levels of metrics measured as a clock time."""
    return [
        value
        for evidence in cited
        if any(metric.endswith("_hour") for metric in evidence.metrics)
        for key, value in evidence.stats.items()
        if key in LEVEL_KEYS and isinstance(value, int | float)
    ]


def _unsupported_dates(text: str, years: set[int], cited: list[Evidence]) -> list[date]:
    """Dates in the text that the evidence does not cover. "Jan 22" names no year, so it stands if
    any year the evidence touches fits: across New Year it can only be one of them."""
    bad = [
        day
        for y, m, d in ISO_DATE.findall(text)
        if not _date_supported(day := date(int(y), int(m), int(d)), cited)
    ]
    pairs = [(MONTHS[m.lower()], int(d)) for m, d in MONTH_DAY.findall(text)]
    pairs += [(MONTHS[m.lower()], int(d)) for d, m in DAY_MONTH.findall(text)]
    for month, day in pairs:
        possible = []
        for year in years:
            try:
                possible.append(date(year, month, day))
            except ValueError:
                continue
        if not any(_date_supported(d, cited) for d in possible):
            bad.extend(possible)
    return bad


def _date_supported(day: date, cited: list[Evidence]) -> bool:
    for evidence in cited:
        if evidence.stats.get("change_date") == day.isoformat():
            return True
        if any(w.start <= day <= w.end for w in evidence.windows):
            return True
    return False


def check_claim(claim: Claim, evidence: dict[str, Evidence]) -> list[str]:
    """Why the claim cannot be shown; empty when it passes."""
    missing = [i for i in claim.evidence_ids if i not in evidence]
    if missing:
        return [f"cites evidence that does not exist: {', '.join(missing)}"]
    cited = [evidence[i] for i in claim.evidence_ids]
    reasons = []

    if insufficient := [e.id for e in cited if not e.sufficient]:
        reasons.append(f"cites evidence with too little data: {', '.join(insufficient)}")
    about = (
        [e for e in cited if claim.metric in e.metrics or e.tool in UNMETERED]
        if claim.metric
        else cited
    )
    if claim.metric and not about:
        reasons.append(f"none of the cited evidence is about {claim.metric}")

    if claim.kind in ("change", "association"):
        tools = (
            ("correlate",)
            if claim.kind == "association"
            else (
                "compare_windows",
                "change_point",
                "trend",
                "weekday_split",
            )
        )
        support = [e for e in about if e.tool in tools and _significant(e)]
        if not support:
            tested = next((e.stats["tests_in_run"] for e in about if "tests_in_run" in e.stats), 0)
            within = f" after correcting for the {tested} tests in this run" if tested else ""
            reason = f"no cited {claim.kind} evidence is significant at {ALPHA}{within}"
            # Lost only to the correction, on the weaker test: say how to confirm it.
            if any(
                e.tool == "change_point" and (p := _base_p(e)) is not None and p < ALPHA
                for e in about
            ):
                reason += (
                    "; to confirm the change, compare the windows before and after its "
                    "change_date with compare_windows, a stronger test, and cite that"
                )
            reasons.append(reason)
        elif claim.direction is None:
            reasons.append("a change or association claim must state its direction")
        else:
            signs = {(_sign(e) or 0) > 0 for e in support}
            if signs != {claim.direction == "up"}:
                reasons.append(f"the evidence does not point {claim.direction}")
    if claim.kind == "no_change":
        relationship = bool(
            re.search(r"\b(?:link|association|relationship|correlat\w*)\b", claim.text, re.I)
        ) or any(e.tool == "correlate" for e in about)
        tools = (
            ("correlate",)
            if relationship
            else ("compare_windows", "change_point", "trend", "weekday_split", "tag_effect")
        )
        tested = [e for e in about if e.tool in tools]
        if not tested:
            reasons.append("a no-pattern claim must cite a test of that relationship or change")
        if any(_significant(e) for e in tested):
            reasons.append("claims no change, but the cited evidence shows a significant one")
    if claim.kind == "suggestion":
        # An everyday habit to try, grounded in this person's own data: some cited evidence about
        # it must show a real pattern about the habit (a significant association or weekday
        # split, or a lever habit_options supports). That a measure changed tests no habit: "keep
        # activity spread across the week" stood on higher average steps (the b730 audit).
        grounded = [
            e
            for e in about
            if (_significant(e) and e.tool not in CHANGE_TOOLS)
            or (e.tool == "habit_options" and e.stats.get("supported"))
            or (e.tool == "personal_options" and e.stats.get("options"))
            or e.tool == "memory"  # what they told the app, in words
            or (e.tool == "food_log" and e.stats.get("meals_logged"))
        ]
        if not grounded:
            reasons.append(
                "a suggestion must cite evidence specific to this person about the habit (a "
                "significant association, a supported habit option, or something "
                "personal_options found); a "
                "measure that changed is not a tested habit. Without one, say nothing specific "
                "stands out yet and ask what is going on"
            )
        if not OPTION_WORDS.search(claim.text):
            reasons.append("word a suggestion as an option the person may try (could, might, try)")
        if ORDER_WORDS.search(claim.text):
            reasons.append("do not order the person: offer the habit as an option instead")
    if claim.kind == "guidance":
        # What a public source says in general; never a statement about this person's data.
        if not cited or not all(e.tool == "knowledge" for e in cited):
            reasons.append("a guidance claim must cite only the passages it comes from")
        if YOUR_DATA.search(claim.text):
            reasons.append("guidance is what a source says in general, not about their data")
    if claim.kind == "value" and not [e for e in about if e.tool != "coverage"]:
        reasons.append("a value claim must cite the evidence that holds the value")
    if claim.kind == "data_quality" and not any(e.tool == "coverage" for e in cited):
        reasons.append("a data-quality claim must cite coverage evidence")
    if claim.kind == "day":
        # Where one day sits against the usual range: up for above, down for below, none within.
        days = [e for e in about if e.tool == "compare_day"]
        expected = {"above": "up", "below": "down", "within": None}
        if not days:
            reasons.append("a day claim must cite compare_day evidence about its metric")
        elif any("position" not in e.stats for e in days):
            reasons.append("too few earlier days for a usual range; state only the day's value")
        elif {expected.get(e.stats.get("position")) for e in days} != {claim.direction}:
            position = days[0].stats.get("position")
            reasons.append(
                f"the day is {position} the usual range"
                + ("" if position == "within" else ", so the claim's direction must say so")
            )

    if claim.direction and claim.kind in ("change", "day"):
        up, down = bool(UP_WORDS.search(claim.text)), bool(DOWN_WORDS.search(claim.text))
        if (
            claim.direction == "up"
            and down
            and not up
            or claim.direction == "down"
            and up
            and not down
        ):
            reasons.append("the wording contradicts the stated direction")

    return reasons + text_problems(claim.text, cited, general=claim.kind == "guidance")


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEKDAY_DATE = re.compile(
    r"\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*,? (?:the )?("
    + "|".join(sorted(MONTHS, key=len, reverse=True))
    + r")\.? (\d{1,2})\b",
    re.IGNORECASE,
)


def wrong_weekdays(text: str, years: set[int]) -> list[str]:
    """ "Fri Nov 14" when Nov 14 was a Saturday: the model names weekdays from memory, and got
    them wrong in the first conversation run (2026-11-14). Right in any year the evidence spans."""
    found = []
    for name, month, day in WEEKDAY_DATE.findall(text):
        candidates = []
        for year in years or {date.today().year}:
            try:
                candidates.append(date(year, MONTHS[month.lower()], int(day)))
            except ValueError:
                continue
        if candidates and not any(
            WEEKDAYS[d.weekday()].startswith(name.lower()) for d in candidates
        ):
            found.append(f"{name} {month} {day}")
    return found


def text_problems(
    text: str, cited: list[Evidence], said: str = "", general: bool = False
) -> list[str]:
    """What is wrong with a sentence shown to the person, given the evidence it rests on. `said` is
    the person's own message: repeating their "8 am" or "20 minutes" is not inventing a number."""
    reasons = []
    allowed = _allowed_numbers(cited)
    allowed = [*allowed, *(n for n, _ in _quoted_numbers(said)), *_quoted_durations(said)]
    unsupported = [n for n, d in _quoted_numbers(text) if not _matches(n, d, allowed)]
    if unsupported:
        reasons.append(
            "quotes numbers not found in the cited evidence: "
            + ", ".join(f"{n:g}" for n in unsupported)
        )
    durations = [m for m in _quoted_durations(text) if not _matches(m, 0, allowed)]
    if durations:
        reasons.append(
            "quotes durations not found in the cited evidence: "
            + ", ".join(f"{m:g} min" for m in durations)
        )
    levels = [*_clock_levels(cited), *_quoted_clock_times(said)]
    times = [t for t in _quoted_clock_times(text) if not any(abs(t - v) <= 0.1 for v in levels)]
    if times:
        reasons.append("quotes times of day not found in the cited evidence")
    years = {w.start.year for e in cited for w in e.windows} | {
        w.end.year for e in cited for w in e.windows
    }
    if bad := _unsupported_dates(text, years, cited):
        reasons.append("mentions dates outside the cited evidence: " + ", ".join(map(str, bad)))
    day = any(e.tool == "compare_day" for e in cited) and len(cited) == 1
    if not general and (swapped := wrong_statistic(text, cited, day)):
        reasons += swapped
    if wrong := wrong_weekdays(text, years):
        reasons.append("names the wrong day of the week: " + ", ".join(wrong))
    if EVIDENCE_ID.search(text):
        reasons.append("writes evidence ids in the text; list them only in evidence_ids")
    if ABOUT_ITSELF.search(text):
        reasons.append("talks about itself; give the advice its evidence supports, plainly")
    if GENERIC_ADVICE.search(text) and not general:  # a how-to from a named source is general
        reasons.append(
            "gives advice anyone could read anywhere; say something specific to this person's "
            "own numbers and life, or leave it out"
        )
    covered = {metric for evidence in cited for metric in evidence.metrics}
    # A passage or what they said speaks of steps or sleep in words, with no metric to cover it.
    if any(evidence.tool in UNMETERED for evidence in cited):
        covered |= set(MENTIONS)
    if uncovered := [
        m for m, pattern in MENTIONS.items() if m not in covered and pattern.search(text)
    ]:
        names = ", ".join(label(m) for m in uncovered)
        reasons.append(
            f"mentions {names}, which none of the cited evidence covers; describe only what the "
            "evidence shows"
        )
    if columns := COLUMN_NAME.findall(text):
        reasons.append(
            "uses internal metric names (" + ", ".join(sorted(set(columns))) + "); use the "
            "names people use, as given in the task"
        )

    if MEDICAL.search(text):
        reasons.append("uses medical language; describe patterns, do not diagnose")
    if CAUSAL.search(text):
        reasons.append("states causation; the tools show change and association, not cause")
    if ENERGY_BALANCE.search(text):
        reasons.append("reasons about calorie balance, which Fitbit's estimates cannot support")
    return reasons


# A clause that only says nothing clearly changed does not claim a change.
NEGATED = re.compile(
    r"\b(no clear|not clearly|did not|didn't|does not|doesn't|do not|don't|no significant|"
    r"not significant|unchanged|steady|stable|similar|the same|no real)\b",
    re.IGNORECASE,
)
SHIFT_WORDS = re.compile(r"\b(later|earlier|shift\w*)\b", re.IGNORECASE)
CLAUSES = re.compile(r"[.;!?]|,|\b(?:while|but|whereas|although)\b", re.IGNORECASE)
SENTENCES = re.compile(r"(?<=[.!?])\s+")
HEDGED = re.compile(
    r"\b(could (?:just )?be (?:normal |natural |day-to-day )?(?:variation|chance|noise)|"
    r"within (?:the )?normal (?:range|variation)|may be (?:chance|noise)|"
    r"not (?:a )?clear(?:ly)?|too small to (?:say|be sure))\b",
    re.IGNORECASE,
)


IN_RANGE = re.compile(r"\b(?:within|in|inside)\b[^.]*\b(?:usual|normal|typical)\b", re.IGNORECASE)


# "Biggest", "main" or "changed the most" ranks one change above the rest, which only a test of
# every metric can show (the overview a broad question gets).
SUPERLATIVE = re.compile(
    r"\b(biggest|largest|greatest|mainly|primarily|top change|"
    r"(?:main|primary|single biggest) (?:change|shift|thing|story|driver|difference|reason)|"
    r"(?:changed|moved|shifted|stood out|stands out) (?:the )?most|"
    r"most (?:notable|noticeable|significant|striking))\b",
    re.IGNORECASE,
)
# Saying the person feels or does something because of a metric claims a cause; the data shows
# what moved together, never why ("you're tired mainly because you've been sleeping less").
ATTRIBUTED = re.compile(
    r"\bbecause (?:you|your|of your)\b|\b(?:that|this|which)(?:'s| is| explains) why you\b",
    re.IGNORECASE,
)


def ranked_problems(summary: str, evidence: list[Evidence]) -> list[str]:
    """A superlative about a metric the overview did not rank first. Only answers that got the
    overview are checked: elsewhere nothing compared every metric, so nothing can rank them."""
    ranked = {
        e.metrics[0]: e.stats["overview_rank"] for e in evidence if "overview_rank" in e.stats
    }
    possible = [e for e in evidence if e.stats.get("overview_possible")]
    if not ranked and not possible:
        return []
    top = next((m for m, rank in ranked.items() if rank == 1), None)
    if top is None and possible:
        possible.sort(key=lambda e: abs(e.stats.get("cliffs_delta") or 0), reverse=True)
        top_possible = possible[0].metrics[0]
    else:
        top_possible = None
    for sentence in SENTENCES.split(summary):
        if not SUPERLATIVE.search(sentence):
            continue
        named = [m for m, pattern in MENTIONS.items() if pattern.search(sentence)]
        for metric in named:
            if metric == top:
                continue
            if metric == top_possible and HEDGED.search(sentence):
                continue
            if top:
                return [
                    f"calls {label(metric)} the biggest or main change, but the overview ranks "
                    f"{label(top)} first; rank the changes as the overview does"
                ]
            return [
                f"calls {label(metric)} the biggest or main change, but nothing changed clearly; "
                "say so, and name the largest move only with a hedge"
            ]
    return []


def attributed(summary: str) -> list[str]:
    """Wording that gives a metric as the reason for how the person is or feels."""
    if ATTRIBUTED.search(summary):
        return [
            "gives a metric as the reason for how they feel or what they do ('because you...'); "
            "the data shows what changed alongside it, so say it could be contributing"
        ]
    return []


# "Held steady" or "no clear change": what a summary says when nothing changed.
STEADY = re.compile(
    r"\b(no clear (?:change|difference|shift)|not clearly (?:changed?|different)|held steady|"
    r"stayed (?:steady|stable|flat|about the same)|steady|stable|unchanged|no (?:real )?change|"
    r"did(?:n't| not) (?:clearly )?change|about the same|flat)\b",
    re.IGNORECASE,
)
CHANGE_TESTS = ("compare_windows", "change_point", "trend")


# The comparison a counting question states outright; an unclear one ("over 10k") is left to the
# model.
ASKED_COMPARISON = (
    (
        "above",
        re.compile(
            r"\bstrictly (?:above|over|more than|greater than)\b|"
            r"\b(?:not|without) (?:counting|including) (?:equal|the same|ties)|"
            r"\bexcluding (?:equal|ties)|\bmore than\b|\bgreater than\b",
            re.I,
        ),
    ),
    (
        "at_least",
        re.compile(
            r"\bat least\b|\bor more\b|\bor above\b|\bor higher\b|"
            r"\bno (?:less|fewer) than\b|\bincluding (?:equal|ties|the same)",
            re.I,
        ),
    ),
    (
        "below",
        re.compile(
            r"\bstrictly (?:below|under|less than)\b|\bless than\b|"
            r"\bfewer than\b",
            re.I,
        ),
    ),
    (
        "at_most",
        re.compile(
            r"\bat most\b|\bor less\b|\bor fewer\b|\bor below\b|"
            r"\bno (?:more|greater) than\b",
            re.I,
        ),
    ),
    ("exactly", re.compile(r"\bexactly (?:\d|equal)", re.I)),
)
NO_DAY_EQUAL = re.compile(r"\bno (?:day|night)s? (?:had |was |were )?(?:exactly|equal)", re.I)


def asked_comparison(question: str) -> str | None:
    """The comparison a question states outright, when it states exactly one."""
    said = {name for name, pattern in ASKED_COMPARISON if pattern.search(question)}
    if "above" in said and "at_least" in said:  # "more than or including": not outright
        return None
    return said.pop() if len(said) == 1 else None


def comparison_problems(question: str, summary: str, evidence: list[Evidence]) -> list[str]:
    """A count made with another comparison than the question's, or "no day equalled it" when
    the count shows one did."""
    problems = []
    counts = [e for e in evidence if e.tool == "goal_progress"]
    wanted = asked_comparison(question)
    if wanted and counts and all(e.stats.get("direction") != wanted for e in counts):
        used = counts[-1].stats.get("direction")
        problems.append(
            f"the question asks for days {wanted.replace('_', ' ')} the value, but the count used "
            f"{str(used).replace('_', ' ')}; count again with direction {wanted}"
        )
    if NO_DAY_EQUAL.search(summary) and any(e.stats.get("days_equal") for e in counts):
        problems.append("says no day equalled the value, but the count shows one did")
    return problems


def contradicted(summary: str, evidence: list[Evidence]) -> list[str]:
    """What a summary says about a metric that the run's own tests contradict.

    The audit (2026-11-18) saw "time asleep showed no clear change" over a clear drop, the
    verifier having rejected that very claim, and an answer opening "sleep increased" over a clear
    decrease. Judged per metric and only where the run's tests of it agree: a metric whose tests
    disagree (steady this week, changed over three months) may be described either way, since the
    summary could mean either test."""
    by_metric: dict[str, list[Evidence]] = {}
    for e in evidence:
        if e.tool in CHANGE_TESTS and _p(e) is not None:
            for metric in e.metrics[:1]:
                by_metric.setdefault(metric, []).append(e)
    clear = {
        metric: signs
        for metric, tests in by_metric.items()
        if all(_significant(t) for t in tests)
        and (signs := {(_sign(t) or 0) > 0 for t in tests if _sign(t)})
        and len(signs) == 1
    }
    flagged: dict[str, str] = {}
    for sentence in SENTENCES.split(summary):
        if HEDGED.search(sentence) and not STEADY.search(sentence):
            continue
        for clause in CLAUSES.split(sentence):
            if not clause or OPTION_WORDS.search(clause):
                continue
            up, down = UP_WORDS.search(clause), DOWN_WORDS.search(clause)
            for metric, pattern in MENTIONS.items():
                if metric not in clear or metric in flagged or not pattern.search(clause):
                    continue
                went_up = next(iter(clear[metric]))
                if STEADY.search(clause) and not (up or down):
                    flagged[metric] = "called steady"
                elif NEGATED.search(clause) or bool(up) == bool(down):
                    continue
                elif bool(up) != went_up:
                    flagged[metric] = "said to have gone up" if up else "said to have gone down"
    if not flagged:
        return []
    said = ", ".join(f"{label(m)} ({why})" for m, why in flagged.items())
    return [
        f"contradicts this run's own tests: {said}, where every test of it shows a clear change "
        "(the other way, or at all); say what the tests show"
    ]


def overstated(summary: str, evidence: list[Evidence]) -> list[str]:
    """Metrics a summary describes as changing that no significant test in the run supports.

    Claims are checked against their kind; the summary has none, so each clause that names a
    metric with a direction word ("lower", "dropped", "later") needs a significant test of that
    metric among the run's evidence. Clauses saying nothing clearly changed are skipped. A
    sentence that hedges ("could be normal variation") may give a direction for a metric the run
    tested, significant or not: that is the honest way to describe a borderline result."""
    supported = {
        metric for e in evidence if e.tool in TEST_TOOLS and _significant(e) for metric in e.metrics
    }
    # A habit the person's data supports ("being in bed by 23:30 went with higher efficiency")
    # names its metrics with direction words; habit_options is the test behind it.
    supported |= {
        metric
        for e in evidence
        if e.tool == "habit_options" and e.stats.get("supported")
        for metric in e.metrics
    }
    # "Higher than usual today" describes where a day sits, which compare_day shows.
    supported |= {
        metric
        for e in evidence
        if e.tool == "compare_day" and e.stats.get("position") in ("above", "below")
        for metric in e.metrics
    }
    # "Your weekend bedtimes run later" describes the person's routine, which code measured.
    supported |= {
        metric
        for e in evidence
        if e.tool == "personal_options" and e.stats.get("options")
        for metric in e.metrics
    }
    tested = {metric for e in evidence if e.tool in TEST_TOOLS for metric in e.metrics}
    # "In your usual range" says where a day sits, which compare_day shows.
    days = {
        metric
        for e in evidence
        if e.tool == "compare_day" and "position" in e.stats
        for metric in e.metrics
    }
    flagged: list[str] = []
    for sentence in SENTENCES.split(summary):
        allowed = tested if HEDGED.search(sentence) else supported
        for clause in CLAUSES.split(sentence):
            # "You could try getting more steps" suggests something; it reports no change.
            if not clause or NEGATED.search(clause) or OPTION_WORDS.search(clause):
                continue
            if not (
                UP_WORDS.search(clause) or DOWN_WORDS.search(clause) or SHIFT_WORDS.search(clause)
            ):
                continue
            here = allowed | days if IN_RANGE.search(clause) else allowed
            for metric, pattern in MENTIONS.items():
                if pattern.search(clause) and metric not in here and metric not in flagged:
                    flagged.append(metric)
    if not flagged:
        return []
    names = ", ".join(label(m) for m in flagged)
    return [
        f"describes a change in {names} that no significant evidence in this run shows; say "
        "there was no clear change, or leave it out"
    ]


def verify(
    claims: list[Claim],
    evidence: dict[str, Evidence],
    extra: Callable[[Claim], list[str]] | None = None,
) -> Verdict:
    """Checks every claim; `extra` adds the caller's own rules, such as an expert's ownership."""
    accepted, rejected = [], []
    for claim in claims:
        reasons = check_claim(claim, evidence)
        if extra:
            reasons += extra(claim)
        if reasons:
            rejected.append(Rejection(claim, tuple(reasons)))
        else:
            accepted.append(claim)
    return Verdict(tuple(accepted), tuple(rejected))
