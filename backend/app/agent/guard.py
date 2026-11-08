"""A check by meaning that nothing shown to the person is medical.

Patterns coaches everyday habits (sleep timing, wind-down, training load and rest, movement),
grounded in the person's own data, since 2026-10-28; it never diagnoses, names a condition, or
advises treatment, medication, supplements, diets or seeing a doctor. The router only judges the
question: an in-scope question ("why is my HRV low?") can still get an answer that names a
condition ("this looks like overtraining") or recommends a supplement. The verifier's word
check misses anything phrased in other words, so before an answer is shown, every sentence that
passed the deterministic checks is put to Jev in one call, with one yes/no per sentence. A flagged
sentence is rejected like any other verifier failure: sent back once, then dropped.

If Jev cannot be reached, the word check alone applies, and the trace records that the guard did
not run. The guard never sees data: only the sentences that would be shown.
"""

from dataclasses import dataclass
from typing import Protocol

from app.agent.jev import JevClient, JevError, clean

FLAG_AT = 0.5
MAX_TEXTS = 8  # a summary and at most five claims, with room to spare

INSTRUCTIONS = (
    "Below is a list of sentences an app shows a person about their own Fitbit data. The app "
    "describes patterns and may suggest everyday habits (bedtime and sleep schedule, winding "
    "down, screens or caffeine timing before bed, naps, training load, rest days, walking and "
    "movement breaks, reminders) but is not medical. Is sentence {i} medical: does it diagnose, "
    "name or hint at an illness or condition, read the data as a warning sign about health, or "
    "advise treatment, medication, supplements, a diet, or seeing a doctor? Describing the data "
    "and suggesting an everyday habit are not medical, and neither is passing on what a public "
    "guideline says about everyday eating, exercise or sleep."
)
REASON = (
    "is medical (a diagnosis, a condition, or treatment, medication, supplements, a diet or a "
    "doctor); describe the data, and suggest only everyday habits grounded in it"
)


class GuardError(RuntimeError):
    """The guard could not judge the sentences; the message is safe to show and to log."""


@dataclass(frozen=True)
class Judgement:
    flagged: tuple[bool, ...]  # one per sentence, in order
    probabilities: tuple[float, ...]
    latency_s: float = 0.0
    cost_usd: float = 0.0


class Guard(Protocol):
    def judge(self, texts: list[str]) -> Judgement: ...


class JevGuard:
    def __init__(self, jev: JevClient):
        self._jev = jev

    @staticmethod
    def payload(texts: list[str], model: str = "jev-latest") -> dict:
        sentences = [clean(t) for t in texts]
        return {
            "state": {"sentences": {str(i): t for i, t in enumerate(sentences)}},
            "model": model,
            "questions": {
                f"advice_{i}": {"type": "noul", "instructions": INSTRUCTIONS.format(i=i)}
                for i in range(len(sentences))
            },
        }

    def judge(self, texts: list[str]) -> Judgement:
        if not texts:
            return Judgement((), ())
        if len(texts) > MAX_TEXTS:
            raise GuardError(f"At most {MAX_TEXTS} sentences can be checked at once.")
        try:
            body, latency, cost = self._jev.call(self.payload(texts, self._jev.model))
        except JevError as exc:
            raise GuardError(str(exc)) from exc
        try:
            answers = body["answers"]
            probabilities = tuple(float(answers[f"advice_{i}"]["noul"]) for i in range(len(texts)))
        except (KeyError, TypeError, ValueError) as exc:
            raise GuardError("Jev's answer was not in the expected format.") from exc
        if not all(0 <= p <= 1 for p in probabilities):
            raise GuardError("Jev returned an invalid probability.")
        flagged = tuple(p >= FLAG_AT for p in probabilities)
        return Judgement(flagged, probabilities, latency, cost)
