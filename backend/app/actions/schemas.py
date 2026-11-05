"""Validated log payloads, with explicit units and timezone-aware times."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from pydantic.alias_generators import to_camel

from app.actions import exercises
from app.actions.exercises import Kind
from app.agent.sanitize import clean, reads_like_instruction

Number = Annotated[float, Field(ge=0, le=100000, strict=True)]

# What one entry can plausibly be. A value outside these is a typo or a misunderstanding, so it is
# refused before anyone can confirm it, not sent to Google and corrected later.
MAX_KCAL = 5000  # one food or meal
MAX_MACRO_G = 500  # protein, carbohydrate or fat in one entry
MAX_WORKOUT = timedelta(hours=24)
MAX_DISTANCE_KM = 300
FUTURE_GRACE = timedelta(minutes=15)  # clock drift between the phone and the server
ExerciseType = Literal[exercises.TYPES]  # every type Google accepts


def now() -> datetime:
    """The current time; tests replace it."""
    return datetime.now(UTC)


def not_future(moment: datetime) -> None:
    if moment > now() + FUTURE_GRACE:
        raise ValueError("A log cannot be in the future.")


class LogModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        allow_inf_nan=False,
    )


class FoodLog(LogModel):
    kind: Literal["food"] = "food"
    food_name: str = Field(min_length=1, max_length=160)
    consumed_at: AwareDatetime
    meal_type: Literal["BREAKFAST", "LUNCH", "DINNER", "SNACK"]
    energy_kcal: Number | None = None
    protein_g: Number | None = None
    carbohydrate_g: Number | None = None
    fat_g: Number | None = None
    # Set by code, never by the model: "estimated" when the values came from a food lookup, so the
    # draft card can say so before the person confirms it.
    provenance: Literal["user_entered", "estimated"] = "user_entered"
    estimate_source: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def valid_food(self) -> Self:
        name = clean(self.food_name, 160)
        if not name or reads_like_instruction(name):
            raise ValueError("Use a food name, without instructions.")
        self.food_name = name
        if all(
            v is None for v in (self.energy_kcal, self.protein_g, self.carbohydrate_g, self.fat_g)
        ):
            raise ValueError("Supply at least one energy or macronutrient value.")
        if self.energy_kcal is not None and self.energy_kcal > MAX_KCAL:
            raise ValueError(f"One entry can have at most {MAX_KCAL} kcal.")
        if any(
            v is not None and v > MAX_MACRO_G
            for v in (self.protein_g, self.carbohydrate_g, self.fat_g)
        ):
            raise ValueError(f"One entry can have at most {MAX_MACRO_G} g of each macronutrient.")
        not_future(self.consumed_at)
        return self

    def google_payload(self) -> dict:
        log = {
            "foodDisplayName": self.food_name,
            "interval": interval(self.consumed_at, self.consumed_at + timedelta(seconds=1)),
            "mealType": self.meal_type,
            "serving": {"amount": 1.0},
        }
        for field, value, unit in (
            ("energy", self.energy_kcal, "kcal"),
            ("totalCarbohydrate", self.carbohydrate_g, "grams"),
            ("totalFat", self.fat_g, "grams"),
        ):
            if value is not None:
                log[field] = {unit: value}
        if self.protein_g is not None:
            log["nutrients"] = [{"nutrient": "PROTEIN", "quantity": {"grams": self.protein_g}}]
        return {"nutritionLog": log}


class Overlap(LogModel):
    """An exercise already recorded over part of the workout, by the tracker or another app."""

    exercise_type: str = Field(pattern=r"^[A-Z_]{1,64}$")
    start_time: AwareDatetime
    end_time: AwareDatetime


class ZoneSeconds(LogModel):
    """Seconds in each of Fitbit's heart-rate zones."""

    light: Annotated[float, Field(ge=0)] = 0
    moderate: Annotated[float, Field(ge=0)] = 0
    vigorous: Annotated[float, Field(ge=0)] = 0
    peak: Annotated[float, Field(ge=0)] = 0


class Measured(LogModel):
    """What the tracker recorded during the workout. Only the server fills this in."""

    status: Literal["measured", "no_data", "unavailable"]
    steps: Annotated[int, Field(ge=0)] | None = None
    distance_km: Annotated[float, Field(ge=0)] | None = None
    calories_kcal: Annotated[float, Field(ge=0)] | None = None
    average_heart_rate: Annotated[int, Field(gt=0)] | None = None
    zone_seconds: ZoneSeconds | None = None
    active_zone_minutes: Annotated[int, Field(ge=0)] | None = None
    swim_lengths: Annotated[int, Field(ge=0)] | None = None
    overlaps: list[Overlap] = Field(default_factory=list, max_length=20)


class WorkoutLog(LogModel):
    kind: Literal["workout"] = "workout"
    exercise_type: ExerciseType
    start_time: AwareDatetime
    end_time: AwareDatetime
    active_seconds: Annotated[int, Field(gt=0, strict=True)]
    distance_km: Annotated[float, Field(ge=0, strict=True)] | None = None
    provenance: Literal["user_entered"] = "user_entered"
    measured: Measured | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        elapsed = (self.end_time - self.start_time).total_seconds()
        if elapsed <= 0 or self.active_seconds > elapsed:
            raise ValueError("Active time must fit within the workout interval.")
        if elapsed > MAX_WORKOUT.total_seconds():
            raise ValueError("One workout can last at most 24 hours.")
        not_future(self.end_time)
        if self.distance_km is not None:
            if self.distance_km > MAX_DISTANCE_KM:
                raise ValueError(f"One workout can cover at most {MAX_DISTANCE_KM} km.")
            limit = exercises.max_speed_kmh(self.exercise_type)
            if limit and self.distance_km / (self.active_seconds / 3600) > limit:
                raise ValueError("That distance is too far for the active time.")
        return self

    def google_payload(self) -> dict:
        # Google requires displayName and metricsSummary, even when there is no metric to give.
        exercise = {
            "exerciseType": self.exercise_type,
            "displayName": exercises.name(self.exercise_type),
            "interval": interval(self.start_time, self.end_time),
            "activeDuration": f"{self.active_seconds:g}s",
            "metricsSummary": self._summary(),
        }
        return {"exercise": exercise}

    def _summary(self) -> dict:
        # What the person said wins; the tracker's measurements fill in the rest, the same ones
        # Fitbit puts on a workout of this kind (the server measures only those). Nothing is
        # estimated, and no minute-level data is written: the tracker already wrote it, and a
        # summary does not change the daily totals, so nothing is counted twice.
        measured = self.measured if self.measured and self.measured.status == "measured" else None
        kind = exercises.kind(self.exercise_type)
        summary: dict = {}
        distance_km = self.distance_km
        if distance_km is None and measured and measured.distance_km:
            distance_km = measured.distance_km
        if distance_km is not None:
            # Whole millimetres: 5.1 km is 5_100_000, not 5_099_999.999999999.
            summary["distanceMillimeters"] = round(distance_km * 1_000_000)
            metres = distance_km * 1000
            if metres > 0 and kind == Kind.ON_FOOT:
                summary["averagePaceSecondsPerMeter"] = round(self.active_seconds / metres, 3)
            elif metres > 0 and kind != Kind.FIELD:  # bikes, boats, swims: speed, as Fitbit
                summary["averageSpeedMillimetersPerSecond"] = round(
                    metres * 1000 / self.active_seconds, 1
                )
        if measured:
            # 64-bit integers travel as strings, durations as "123s".
            if measured.steps:
                summary["steps"] = str(measured.steps)
            if measured.calories_kcal is not None:
                summary["caloriesKcal"] = measured.calories_kcal
            if measured.average_heart_rate:
                summary["averageHeartRateBeatsPerMinute"] = str(measured.average_heart_rate)
            if measured.zone_seconds:
                zones = measured.zone_seconds
                summary["heartRateZoneDurations"] = {
                    "lightTime": f"{zones.light:g}s",
                    "moderateTime": f"{zones.moderate:g}s",
                    "vigorousTime": f"{zones.vigorous:g}s",
                    "peakTime": f"{zones.peak:g}s",
                }
            if measured.active_zone_minutes:  # Fitbit leaves it out when there are none
                summary["activeZoneMinutes"] = str(measured.active_zone_minutes)
            if measured.swim_lengths:
                summary["totalSwimLengths"] = measured.swim_lengths
        return summary


def interval(start: datetime, end: datetime) -> dict:
    return {
        "startTime": start.isoformat(),
        "endTime": end.isoformat(),
        "startUtcOffset": f"{start.utcoffset().total_seconds():g}s",
        "endUtcOffset": f"{end.utcoffset().total_seconds():g}s",
    }


Log = Annotated[FoodLog | WorkoutLog, Field(discriminator="kind")]
LOG = TypeAdapter(Log)
DATA_TYPES = {"food": "nutrition-log", "workout": "exercise"}
WRITE_SCOPES = {
    "food": "https://www.googleapis.com/auth/googlehealth.nutrition.writeonly",
    "workout": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.writeonly",
}
