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
    if claim.kind == "no_change" and any(_significant(e) for e in about if e.tool != "coverage"):
        reasons.append("claims no change, but the cited evidence shows a significant one")
    if claim.kind == "suggestion":
        # An everyday habit to try, grounded in this person's own data: some cited evidence about
        # it must show a real pattern (a significant test, or a lever habit_options supports).
        grounded = [
            e
            for e in about
            if _significant(e)
            or (e.tool == "habit_options" and e.stats.get("supported"))
            or (e.tool == "personal_options" and e.stats.get("options"))
            or e.tool == "memory"  # what they told the app, in words
            or (e.tool == "food_log" and e.stats.get("meals_logged"))
        ]
        if not grounded:
            reasons.append(
                "a suggestion must cite evidence specific to this person (a significant test, a "
                "supported habit option, or something personal_options found); without one, say "
                "nothing specific stands out yet and ask what is going on"
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
