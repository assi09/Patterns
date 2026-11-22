"""Every workout type Google accepts, and what Fitbit records for each kind.

The kinds follow what Fitbit put in the summaries of 119 workouts it recorded for the owner:
every workout has calories, average heart rate, time in heart-rate zones and Active Zone Minutes;
walks also have steps, distance and pace; soccer, tennis, volleyball and "sport" have steps and
distance; the elliptical has steps; weightlifting, strength, cardio and general workouts have
neither. Types the owner has not done are placed by the same rule (on foot, a court or field
sport, step-based, swimming, or neither); docs/agent-actions.md lists which were verified.
"""

import re
from enum import StrEnum


class Kind(StrEnum):
    ON_FOOT = "on_foot"  # steps, distance and pace
    FIELD = "field"  # steps and distance: running about, with no meaningful pace
    STEPS = "steps"  # steps, but distance from stride means nothing on a machine or a dance floor
    SWIM = "swim"  # pool lengths, when the tracker counted them
    OTHER = "other"  # heart rate only: gym, yoga, cycling, rowing, combat sports and the rest


ON_FOOT = {
    "WALKING", "RUNNING", "HIKING", "TRAIL_RUN", "TREADMILL", "TREADMILL_WALK", "INCLINE_RUN",
    "INCLINE_WALK", "POWER_WALKING", "NORDIC_WALKING", "STROLLER_WALK", "WALK_WITH_WEIGHTS",
    "RUCKING", "BACKPACKING", "ORIENTEERING", "SNOWSHOEING",
}  # fmt: skip
FIELD = {
    "SOCCER", "TENNIS", "VOLLEYBALL", "VOLLEYBALL_BEACH", "SPORT", "BASKETBALL", "BADMINTON",
    "SQUASH", "PADEL", "PICKELBALL", "RACQUETBALL", "RACKET_SPORTS", "TABLE_TENNIS", "HANDBALL",
    "RUGBY", "FOOTBALL_AMERICAN", "FOOTBALL_AUSTRALIAN", "FIELD_HOCKEY", "LACROSSE", "CRICKET",
    "BASEBALL", "SOFTBALL", "ULTIMATE_FRISBEE", "FRISBEE_PLAYING_GENERAL", "GOLF",
    "TRACK_AND_FIELD", "CHEERLEADING",
}  # fmt: skip
STEPS = {
    "ELLIPTICAL", "STAIRCLIMBER", "STEP_TRAINING", "JUMPING_ROPE", "DANCING", "BALLET",
    "BALLROOM_DANCE", "BREAKDANCING", "HIP_HOP", "JAZZ_DANCE", "MODERN_DANCE", "TANGO", "ZUMBA",
    "BARRE_CLASS",
}  # fmt: skip
SWIM = {"SWIMMING", "SWIMMING_POOL", "SWIMMING_OPEN_WATER"}

# Google's Exercise.ExerciseType values, except EXERCISE_TYPE_UNSPECIFIED (PICKELBALL is
# Google's spelling).
TYPES = (
    "AEROBIC_WORKOUT", "ARCHERY", "ASSAULT_BIKE", "BACKPACKING", "BADMINTON", "BALLET",
    "BALLROOM_DANCE", "BARRE_CLASS", "BASEBALL", "BASKETBALL", "BIKING", "BILLIARDS", "BODY_WEIGHT",
    "BOOTCAMP", "BOWLING", "BOXING", "BREAKDANCING", "CALISTHENICS", "CANOEING", "CARDIO_SCULPT",
    "CARDIO_WORKOUT", "CARPENTRY", "CHEERLEADING", "CIRCUIT_TRAINING", "CLEANING", "CLIMBING",
    "CORE_TRAINING", "CRICKET", "CROQUET", "CROSS_COUNTRY_SKI", "CROSS_TRAINING", "CROSSFIT",
    "CURLING", "DANCING", "DIVING", "ELECTRIC_BIKE", "ELECTRIC_SCOOTER", "ELLIPTICAL",
    "EQUESTRIAN_SPORTS", "EXERCISE_CLASS", "FENCING", "FIELD_HOCKEY", "FISHING", "FITNESS_GAMING",
    "FOILING", "FOOTBALL_AMERICAN", "FOOTBALL_AUSTRALIAN", "FREE_WEIGHTS",
    "FRISBEE_PLAYING_GENERAL", "FUNCTIONAL_STRENGTH_TRAINING", "GARDENING", "GOLF", "GYMNASTICS",
    "HANDBALL", "HAND_CYCLING", "HIIT", "HIKING", "HIP_HOP", "HOCKEY", "HOEING",
    "HOUSEHOLD_CHORES", "HUNTING", "ICE_SKATING", "INCLINE_RUN", "INCLINE_WALK",
    "INDOOR_CLIMBING", "INTERVAL_WORKOUT", "JAZZ_DANCE", "JIU_JITSU", "JUMPING_ROPE", "KARATE",
    "KAYAKING", "KICKBOXING", "KITESURFING", "LACROSSE", "MARTIAL_ARTS", "MEDITATE",
    "MODERN_DANCE", "MOTOCROSS", "MOTORCYCLE", "MOUNTAIN_BIKE", "MOWING_LAWN", "MUAY_THAI",
    "MULTISPORT", "MUSICAL_PERFORMANCE", "NORDIC_WALKING", "ORIENTEERING", "OTHER",
    "OUTDOOR_BIKE", "OUTDOOR_WORKOUT", "PADDLEBOARDING", "PADEL", "PAINTING", "PARAGLIDING",
    "PARKOUR", "PICKELBALL", "PILATES", "POLO", "POWERLIFTING", "POWER_WALKING", "RACKET_SPORTS",
    "RACQUETBALL", "RESISTANCE_BANDS", "ROCK_CLIMBING", "ROLLERBLADING", "ROLLER_SKATING",
    "ROWING", "ROWING_MACHINE", "RUCKING", "RUGBY", "RUNNING", "SAILING", "SCOOTERING",
    "SCUBA_DIVING", "SHOOTING", "SHOVELING", "SKATEBOARDING", "SKATING", "SKIING", "SKYDIVING",
    "SNORKELING", "SNOWBOARDING", "SNOWMOBILING", "SNOWSHOEING", "SNOW_SPORT", "SOCCER",
    "SOFTBALL", "SPEED_SKATING", "SPINNING", "SPORT", "SQUASH", "STAIRCLIMBER", "STATIONARY_BIKE",
    "STEP_TRAINING", "STRENGTH_TRAINING", "STRETCHING", "STROLLER_WALK", "SURFING", "SWIMMING",
    "SWIMMING_OPEN_WATER", "SWIMMING_POOL", "SYNCHRONIZED_SWIMMING", "TABATA_WORKOUT",
    "TABLE_TENNIS", "TAEKWONDO", "TAI_CHI", "TANGO", "TENNIS", "TRACK_AND_FIELD", "TRAIL_RUN",
    "TRAMPOLINE", "TREADMILL", "TREADMILL_WALK", "TRX", "ULTIMATE_FRISBEE", "UNICYCLING",
    "VOLLEYBALL", "VOLLEYBALL_BEACH", "WAKEBOARDING", "WALKING", "WALK_WITH_WEIGHTS",
    "WATER_AEROBICS", "WATER_JOGGING", "WATER_POLO", "WATER_SKIING", "WATER_SPORT",
    "WATER_VOLLEYBALL", "WEEDING", "WEIGHTLIFTING", "WEIGHT_MACHINES", "WEIGHTS", "WHEELCHAIR",
    "WINDSURFING", "WORKOUT", "WRESTLING", "YOGA", "YOGA_BIKRAM", "YOGA_HATHA", "YOGA_POWER",
    "YOGA_VINYASA", "ZUMBA",
)  # fmt: skip

# Names Fitbit uses, or plain words where "RUNNING" -> "Running" would read oddly.
# The app has the same list (mobile/src/lib/actionLog.ts).
NAMES = {
    "RUNNING": "Run", "WALKING": "Walk", "BIKING": "Bike", "HIKING": "Hike",
    "AEROBIC_WORKOUT": "Aerobic workout", "PICKELBALL": "Pickleball", "HIIT": "HIIT", "TRX": "TRX",
    "FOOTBALL_AMERICAN": "American football", "FOOTBALL_AUSTRALIAN": "Australian football",
    "FRISBEE_PLAYING_GENERAL": "Frisbee", "VOLLEYBALL_BEACH": "Beach volleyball",
    "SWIMMING_POOL": "Pool swim", "SWIMMING_OPEN_WATER": "Open water swim",
    "YOGA_BIKRAM": "Bikram yoga", "YOGA_HATHA": "Hatha yoga", "YOGA_POWER": "Power yoga",
    "YOGA_VINYASA": "Vinyasa yoga", "WALK_WITH_WEIGHTS": "Walk with weights",
    "MEDITATE": "Meditation", "OTHER": "Other workout",
}  # fmt: skip

# Fastest plausible average over the active time, in km/h; a faster distance is a typo.
_RUN = {"RUNNING", "TRAIL_RUN", "TREADMILL", "INCLINE_RUN", "ORIENTEERING", "TRACK_AND_FIELD"}
_WHEELS = {
    "BIKING", "MOUNTAIN_BIKE", "OUTDOOR_BIKE", "STATIONARY_BIKE", "SPINNING", "ELECTRIC_BIKE",
    "HAND_CYCLING", "ASSAULT_BIKE", "UNICYCLING", "WHEELCHAIR",
}  # fmt: skip
_PADDLE = {"ROWING", "ROWING_MACHINE", "KAYAKING", "CANOEING", "PADDLEBOARDING"}
_SKATE = {"ROLLERBLADING", "ROLLER_SKATING", "ICE_SKATING", "SKATING", "SPEED_SKATING"}


def kind(exercise_type: str) -> Kind:
    for kind_, types in (
        (Kind.ON_FOOT, ON_FOOT),
        (Kind.FIELD, FIELD),
        (Kind.STEPS, STEPS),
        (Kind.SWIM, SWIM),
    ):
        if exercise_type in types:
            return kind_
    return Kind.OTHER


def name(exercise_type: str) -> str:
    if exercise_type in NAMES:
        return NAMES[exercise_type]
    words = exercise_type.lower().replace("_", " ")
    return words[0].upper() + words[1:]


def in_sentence(exercise_type: str) -> str:
    """The name inside a sentence: lower case, but an acronym stays one ("ready to log: HIIT",
    not "hiit")."""
    words = name(exercise_type).split()
    return " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in words)


def max_speed_kmh(exercise_type: str) -> float | None:
    if exercise_type in _RUN:
        return 25
    if exercise_type in ON_FOOT:
        return 10
    if exercise_type in _WHEELS:
        return 80
    if exercise_type in SWIM:
        return 10
    if exercise_type in _PADDLE:
        return 25
    if exercise_type in _SKATE:
        return 60
    return None


# Names too general to say which workout it was ("a sport", "my workout").
_TOO_GENERAL = {"OTHER", "WORKOUT", "SPORT"}
# Every way a type is named here: its own words ("strength training", "hiit") and the name the
# app shows ("Run", "Pool swim"). Longest first, so "rowing machine" is not read as "rowing".
_PHRASES = sorted(
    {
        (phrase, exercise_type)
        for exercise_type in TYPES
        if exercise_type not in _TOO_GENERAL
        for phrase in (exercise_type.lower().replace("_", " "), name(exercise_type).lower())
    },
    key=lambda item: -len(item[0]),
)
_PHRASE = {phrase: re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE) for phrase, _ in _PHRASES}


def named_type(text: str) -> str | None:
    """The one workout type the person's words name, or None if they name none or several.

    The model chose "strength training" for "a HIIT workout", "a boxing session" and "a squash
    game", which Google has types for (the held-out logging run of 2026-11-22): the person's own
    word is the type. "After squash I walked home" names two, and is left to the model."""
    taken: list[tuple[int, int]] = []
    found = set()
    for phrase, exercise_type in _PHRASES:
        for match in _PHRASE[phrase].finditer(text):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            taken.append(match.span())
            found.add(exercise_type)
    return found.pop() if len(found) == 1 else None
