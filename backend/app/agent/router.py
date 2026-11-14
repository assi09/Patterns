"""Routing a question to the expert that owns its topic.

A classifier answers the topic, the experts needed and the request intent. Topic routing has two
parts. Its **topic**: one probability per label (an expert, `general` or `out_of_scope`) that picks
the lead and checks the scope. And, independently
for each expert, whether answering **needs** that expert's data: a cross-domain question ("did my
late nights hurt my recovery?") needs two. A single topic distribution cannot say that, because its
spare probability is uncertainty, not a second topic. Code, not the classifier, decides what to do
(`decide`): refuse, answer from the conversation itself, hand the question to the general agent, or
give it to the lead expert, which may consult the other experts the question needs.

Jev (TypeSafe's typed decision model) is the classifier in the app. If it fails or times out, a
keyword rule over metric names routes instead, so a question is never lost to the router. An LLM
router exists for the evaluation, to compare accuracy, latency and cost. Every router receives the
question text only, never the person's data or memory: the current question and up to three earlier
ones from the conversation, so a follow-up ("and last week?") can be read in light of what it refers
to, even several questions back.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

import httpx2

from app.agent.experts import EXPERTS
from app.agent.intent import (
    INTENT_CRITERIA,
    INTENT_INSTRUCTIONS,
    Intent,
    decide_intent,
    intent_probabilities,
    keyword_intent,
)
from app.agent.jev import JevClient, JevError, clean
from app.agent.llm import LLM, Budget, LLMError
from app.agent.strategy_types import (
    QUESTION_CRITERIA,
    QUESTION_INSTRUCTIONS,
    QUESTION_TYPES,
    is_small_talk,
)
from app.agent.verifier import MEDICAL

GENERAL = "general"
CONVERSATION = "conversation"
OUT_OF_SCOPE = "out_of_scope"
EXPERT_LABELS = tuple(EXPERTS)
LABELS = (*EXPERT_LABELS, GENERAL, CONVERSATION, OUT_OF_SCOPE)

# What each label means, for the classifiers. Experts are described by the metrics they own.
CRITERIA = {
    "sleep": "time asleep, time in bed, bedtime, sleep efficiency, sleep stages (deep, light, "
    "REM), time awake at night, sleep score; general questions on sleep, naps, jet lag, shift "
    "work or feeling tired in the day",
    "recovery": "recovery, heart rate variability (HRV), resting heart rate, breathing rate, "
    "skin temperature, readiness, the app's recovery score, the app's stress score (physical "
    "signs of stress in the data, such as heart rate while still)",
    "activity": "logging workouts; how to do an exercise or stretch, how much exercise adults "
    "should do; steps, distance, exercise and training, Active Zone Minutes, "
    "active and sedentary time, calories burned, cardio load, strain (the day's load from time "
    "in heart-rate zones)",
    "nutrition": "logging food and drink, or analysing food and drink logged: calories eaten, "
    "protein, carbohydrates, fat, nutrients, "
    "meals; what is in a food or dish; how much of a nutrient adults generally need",
    GENERAL: "the person's own Fitbit data overall, or several areas with no main one, or a "
    "reminder about no particular area",
    # Without it, "what did I just say?" takes the earlier questions' topic and reaches an expert
    # that looks only at data.
    CONVERSATION: "this chat itself, not the data: what the person or the assistant said "
    "earlier in it, a recap of it, or what an earlier answer meant; what the app knows or "
    "remembers about the person; or a passing remark about something unrelated to health, food, "
    "exercise or sleep (their dog, their job). Never how they are doing, anything they ate or "
    "did, or what they should do next: those belong to the topic being discussed",
    # Coaching on everyday habits ("how can I sleep better?") is in scope since 2026-10-28.
    OUT_OF_SCOPE: "medical matters (a diagnosis, symptoms, an illness or condition, treatment, "
    "medication, supplements, diets, or whether to see a doctor), or anything unrelated to their "
    "own Fitbit data, improving their everyday habits, logging food, drink or workouts, what is "
    "in a food or dish, what a tracker metric means, how to do an exercise, general questions on "
    "sleep, training, recovery or eating, reminders, what they told the app about themselves, or "
    "this conversation",
}
INSTRUCTIONS = (
    "A person asks about their own Fitbit data, how to improve their everyday habits, to log "
    "food, drink or workouts, what is in a food, what a tracker metric means, how to do an "
    "exercise, general questions on sleep, training or eating, or for a reminder, "
    "possibly following up on earlier questions. Which topic is the current question about? "
    "Earlier questions, newest first, only show what it may refer to."
)


def needs_instructions(expert: str) -> str:
    return (
        f"A person asks a question about their own Fitbit data, possibly following up on their "
        f"earlier questions. Does answering the current question need their {expert} data "
        f"({CRITERIA[expert]})?"
    )


MAX_EARLIER = 3  # earlier questions the router sees, newest first

# Thresholds on the probabilities. Tuned by the router evaluation, not fitted to anyone's data.
REFUSE_AT = 0.5  # out of scope at least this likely: refuse
RECALL_AT = 0.5  # about the conversation itself at least this likely: answered from it
LEAD_AT = 0.4  # the most likely expert must reach this, or the general agent answers
CONSULT_AT = 0.5  # other experts whose data the question needs this likely are consulted


class RouterError(RuntimeError):
    """A classifier could not label the question; the message is safe to show and to log."""


@dataclass(frozen=True)
class Classification:
    probabilities: dict[str, float]  # the topic: every label, summing to 1
    needs: dict[str, float]  # per expert, the probability that answering needs its data
    source: str  # jev, keyword, llm
    latency_s: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None  # why an earlier router in the chain failed

    intent_probabilities: dict[str, float] = field(default_factory=dict)
    # The kind of answer the question needs (strategy.py); empty when no router gave one.
    question_types: dict[str, float] = field(default_factory=dict)

    @property
    def intent(self) -> Intent:
        return decide_intent(self.intent_probabilities)

    @property
    def question_type(self) -> str | None:
        if not self.question_types:
            return None
        return max(self.question_types, key=self.question_types.get)

    @property
    def top(self) -> str:
        return max(LABELS, key=lambda label: self.probabilities[label])


class Router(Protocol):
    def classify(self, question: str, earlier: Sequence[str] = ()) -> Classification: ...


def state(question: str, earlier: Sequence[str] = ()) -> dict:
    """What a router is given: the cleaned question and the latest earlier ones, newest first."""
    recent = [clean(q) for q in earlier[:MAX_EARLIER] if clean(q)]
    return {"question": clean(question), "earlier_questions": recent}


def normalized(raw: dict) -> dict[str, float]:
    """Probabilities over every label, summing to 1. Raises `RouterError` on unusable values."""
    if not isinstance(raw, dict):
        raise RouterError("The router returned no probabilities.")
    values = {label: _probability(raw.get(label, 0.0), label) for label in LABELS}
    total = sum(values.values())
    if total <= 0:
        raise RouterError("The router returned no probabilities.")
    return {label: value / total for label, value in values.items()}


def _probability(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
        raise RouterError(f"The router returned an invalid probability for {name}.")
    return float(value)


def needs_from(raw) -> dict[str, float]:
    """One independent probability per expert. Raises `RouterError` on unusable values."""
    if not isinstance(raw, dict) or set(raw) != set(EXPERT_LABELS):
        raise RouterError("The router did not say which experts' data the question needs.")
    return {expert: _probability(raw[expert], f"needs {expert}") for expert in EXPERT_LABELS}


class JevRouter:
    """Routes with Jev: no retries, since a slow or failing call falls back to the keyword rule."""

    def __init__(self, api_key: str, http: httpx2.Client | None = None, **options):
        try:
            self.client = JevClient(api_key, http, **options)
        except JevError as exc:
            raise RouterError(str(exc)) from exc
        self.model = self.client.model

    @classmethod
    def from_settings(cls, settings) -> "JevRouter":
        key = settings.typesafe_api_key
        return cls(
            key.get_secret_value() if key else "",
            model=settings.typesafe_model,
            base_url=settings.typesafe_base_url,
        )

    def payload(self, question: str, earlier: Sequence[str] = ()) -> dict:
        given = state(question, earlier)
        return {
            # A bare question when there is nothing earlier, as Jev reads plain text best.
            "state": given if given["earlier_questions"] else given["question"],
            "model": self.model,
            # One call: topic, request intent, and per expert whether its data is needed.
            "questions": {
                "topic": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA},
                "intent": {
                    "type": "choice",
                    "instructions": INTENT_INSTRUCTIONS,
                    "criteria": INTENT_CRITERIA,
                },
                "question_type": {
                    "type": "choice",
                    "instructions": QUESTION_INSTRUCTIONS,
                    "criteria": QUESTION_CRITERIA,
                },
                **{
                    f"needs_{expert}": {"type": "noul", "instructions": needs_instructions(expert)}
                    for expert in EXPERT_LABELS
                },
            },
        }

    def classify(self, question: str, earlier: Sequence[str] = ()) -> Classification:
        try:
            body, latency, cost = self.client.call(self.payload(question, earlier))
        except JevError as exc:
            raise RouterError(str(exc)) from exc
        try:
            answers = body["answers"]
            topic = answers["topic"]
            needs = {e: answers[f"needs_{e}"] for e in EXPERT_LABELS}
        except (ValueError, KeyError, TypeError) as exc:
            raise RouterError("Jev's answer was not in the expected format.") from exc
        if not isinstance(topic, dict) or topic.get("type") != "choice":
            raise RouterError("Jev's answer was not in the expected format.")
        if not all(isinstance(a, dict) and a.get("type") == "noul" for a in needs.values()):
            raise RouterError("Jev's answer was not in the expected format.")
        probabilities = normalized(topic.get("probabilities"))
        needed = needs_from({e: a.get("noul") for e, a in needs.items()})
        try:
            intent = answers["intent"]
            if not isinstance(intent, dict) or intent.get("type") != "choice":
                raise ValueError("The router returned an invalid request intent.")
            intents = intent_probabilities(intent.get("probabilities"))
        except (KeyError, ValueError, TypeError) as exc:
            raise RouterError("Jev did not return a valid request intent.") from exc
        return Classification(
            probabilities,
            needed,
            source="jev",
            latency_s=latency,
            cost_usd=cost,
            intent_probabilities=intents,
            question_types=_question_types(answers.get("question_type")),
        )


def _question_types(answer) -> dict[str, float]:
    """The question type's probabilities, or none: a missing or malformed answer is not fatal."""
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return {}
    raw = answer.get("probabilities")
    if not isinstance(raw, dict):
        return {}
    values = {
        t: float(raw[t])
        for t in QUESTION_TYPES
        if isinstance(raw.get(t), int | float) and not isinstance(raw.get(t), bool)
    }
    return values if values and sum(values.values()) > 0 else {}


# Keyword rules for the question type, tried in order; the first that matches wins.
QUESTION_WORDS = (
    (
        "world",
        re.compile(
            r"\b(?:how many calories (?:are |is )?in|calories in|nutrition (?:of|in)|"
            r"what(?:'s| is) in (?:a|an|the)|what does .+ mean|"
            r"what (?:is|are) (?:hrv|active zone minutes))",
            re.I,
        ),
    ),
    (
        "coaching",
        re.compile(
            r"\b(how (?:can|do|could|should) i (?:improve|sleep better|recover|get better|boost|"
            r"increase|raise|lower|reduce|train)|tips?\b|advice|what should i (?:do|change)|"
            r"help me (?:sleep|recover|improve))",
            re.I,
        ),
    ),
    ("why", re.compile(r"\b(why|what(?:'s| is) (?:causing|behind)|explain)\b", re.I)),
    ("day", re.compile(r"\b(today|tonight|last night|this morning|yesterday)\b", re.I)),
    (
        "pattern",
        re.compile(
            r"\b(weekends?|weekdays?|correlat\w*|relat\w*|go(?:es)? with|affect\w*|"
            r"on days (?:i|when))\b",
            re.I,
        ),
    ),
    (
        "change",
        re.compile(
            r"\b(chang\w*|lately|recently|trend\w*|getting (?:worse|better)|"
            r"since|dropp?\w*|rising|went (?:up|down))\b",
            re.I,
        ),
    ),
    (
        "lookup",
        re.compile(
            r"\b(what(?:'s| is| was) my|how (?:much|many|long)|average|best|worst|"
            r"normal|usual)\b",
            re.I,
        ),
    ),
)


def keyword_question_type(question: str) -> dict[str, float]:
    if is_small_talk(question):
        return {"chat": 1.0}
    found = next((name for name, pattern in QUESTION_WORDS if pattern.search(question)), None)
    return {found: 1.0} if found else {}


def _words(*patterns: str) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(patterns) + r")", re.IGNORECASE)


# Patterns match at the start of a word, so "train" also matches "training".
KEYWORDS = {
    "sleep": _words(
        r"sleep",
        r"slept",
        r"bed",
        r"nap",
        r"rem\b",
        r"deep sleep",
        r"awake",
        r"wak(e|ing) up",
        r"night",
    ),
    "recovery": _words(
        r"recover",
        r"hrv",
        r"heart rate variability",
        r"resting heart",
        r"rhr\b",
        r"readiness",
        r"breathing",
        r"respirat",
        r"skin temp",
        r"temperature",
        r"stress",
    ),
    "activity": _words(
        r"step",
        r"walk",
        r"run",
        r"exercis",
        r"workout",
        r"train",
        r"active",
        r"activity",
        r"distance",
        r"zone minutes",
        r"azm\b",
        r"strain",
        r"heart[- ]rate zone",
        r"sedentary",
        r"cardio",
        r"burn",
    ),
    "nutrition": _words(
        r"eat",
        r"ate\b",
        r"food",
        r"diet",
        r"protein",
        r"carb",
        r"fat\b",
        r"meal",
        r"breakfast",
        r"lunch",
        r"dinner",
        r"snack",
        r"drink",
        r"nutri",
        r"sugar",
        r"fib(er|re)",
        r"calories (eaten|in)\b",
        r"intake",
    ),
}
# Questions about the chat itself, not about any metric.
CONVERSATION_WORDS = re.compile(
    r"\b(?:what|which) (?:did|do|was|were) (?:i|you)\b.{0,20}?\b(?:say|said|ask|asked|write|"
    r"wrote|mean|meant|tell|told|saying|asking)"
    r"|\b(?:previous|earlier|last|first|above) (?:\w+ )?(?:messages?|questions?|answers?|"
    r"repl(?:y|ies))\b"
    r"|\b(?:summari[sz]e|recap)\b.{0,20}\b(?:chat|conversation)\b"
    r"|\bwhat (?:have )?we (?:talked|discussed|said)\b",
    re.IGNORECASE,
)
# Not "sick" or "ill": "did my HRV drop when I was sick?" is a question about the data. Not
# "supplement" either: "did my protein-supplement days go with better recovery?" is one too.
OFF_TOPIC = _words(
    r"doctor",
    r"symptom",
    r"cure",
    r"medicine",
    r"melatonin",
    r"pills?\b",
    r"drugs?\b",
)


class KeywordRouter:
    """Metric words decide the topic; medical words mean out of scope. Free and instant.

    A question with no metric words takes its topic from the latest earlier question that has some,
    unless it asks about the conversation itself.
    """

    def classify(self, question: str, earlier: Sequence[str] = ()) -> Classification:
        given = state(question, earlier)
        text = given["question"]
        intents = keyword_intent(text)
        probabilities = dict.fromkeys(LABELS, 0.0)
        hits = self._hits(text)
        for previous in given["earlier_questions"]:
            if any(hits.values()):
                break
            hits = self._hits(previous)
        needs = {label: 1.0 if count else 0.0 for label, count in hits.items()}
        kinds = keyword_question_type(text)
        if MEDICAL.search(text) or OFF_TOPIC.search(text):
            probabilities[OUT_OF_SCOPE] = 1.0
            return Classification(
                probabilities, needs, source="keyword", intent_probabilities=intents
            )
        total = sum(hits.values())
        if CONVERSATION_WORDS.search(text):
            probabilities[CONVERSATION] = 1.0
            needs = dict.fromkeys(needs, 0.0)
        elif not total:
            probabilities[GENERAL] = 1.0
        else:
            probabilities |= {label: count / total for label, count in hits.items()}
        return Classification(
            probabilities,
            needs,
            source="keyword",
            intent_probabilities=intents,
            question_types=kinds,
        )

    @staticmethod
    def _hits(text: str) -> dict[str, int]:
        return {label: len(pattern.findall(text)) for label, pattern in KEYWORDS.items()}


ROUTE_TOOL = "route"
LLM_ROUTER_PROMPT = (
    INSTRUCTIONS
    + " With the route tool, give the probability of each topic (they should sum to 1), and "
    "separately for each of sleep, recovery, activity and nutrition the probability that "
    "answering needs that data (each from 0 to 1).\n"
    + "\n".join(f"- {label}: {meaning}" for label, meaning in CRITERIA.items())
    + "\nAlso give a separate probability for each request intent. "
    + INTENT_INSTRUCTIONS
    + "\n"
    + "\n".join(f"- {label}: {meaning}" for label, meaning in INTENT_CRITERIA.items())
    + "\nAnd a probability for each question type. "
    + QUESTION_INSTRUCTIONS
    + "\n"
    + "\n".join(f"- {label}: {meaning}" for label, meaning in QUESTION_CRITERIA.items())
)


def _probabilities_schema(labels: tuple[str, ...]) -> dict:
    return {
        "type": "object",
        "properties": {label: {"type": "number", "minimum": 0, "maximum": 1} for label in labels},
        "required": list(labels),
    }


class LLMRouter:
    """The same labels from the language model, for comparison in the evaluation."""

    def __init__(self, llm: LLM):
        self._llm = llm

    def classify(self, question: str, earlier: Sequence[str] = ()) -> Classification:
        tool = {
            "type": "function",
            "function": {
                "name": ROUTE_TOOL,
                "description": "The probability of each topic.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": _probabilities_schema(LABELS),
                        "needs": _probabilities_schema(EXPERT_LABELS),
                        "intent": _probabilities_schema(tuple(Intent)),
                        "question_type": _probabilities_schema(QUESTION_TYPES),
                    },
                    "required": ["topic", "needs", "intent", "question_type"],
                },
            },
        }
        messages = [
            {"role": "system", "content": LLM_ROUTER_PROMPT},
            {"role": "user", "content": json.dumps(state(question, earlier))},
        ]
        budget = Budget(max_calls=1, max_tool_calls=1, max_cost_usd=0.002)
        try:
            completion = self._llm.complete(messages, tools=[tool], budget=budget)
        except LLMError as exc:
            raise RouterError(str(exc)) from exc
        call = next((c for c in completion.tool_calls if c.name == ROUTE_TOOL), None)
        if call is None or call.arguments is None:
            raise RouterError("The model did not route the question.")
        # Validate topic/needs first so a missing intent does not hide other malformed fields.
        topic = normalized(call.arguments.get("topic"))
        needs = needs_from(call.arguments.get("needs"))
        try:
            intents = intent_probabilities(call.arguments.get("intent"))
        except ValueError as exc:
            raise RouterError(str(exc)) from exc
        kinds = call.arguments.get("question_type")
        return Classification(
            topic,
            needs,
            source="llm",
            latency_s=completion.latency_s,
            cost_usd=completion.cost_usd,
            intent_probabilities=intents,
            question_types=_question_types({"type": "choice", "probabilities": kinds}),
        )


@dataclass(frozen=True)
class FallbackRouter:
    """Tries the primary router; when it fails, the fallback answers and the reason is kept."""

    primary: Router
    fallback: Router

    def classify(self, question: str, earlier: Sequence[str] = ()) -> Classification:
        try:
            return self.primary.classify(question, earlier)
        except RouterError as exc:
            return replace(self.fallback.classify(question, earlier), error=str(exc))


@dataclass(frozen=True)
class Route:
    action: Literal["expert", "general", "conversation", "refuse"]
    expert: str | None  # the lead, for `expert`
    consult: tuple[str, ...]  # the other experts the lead may consult
    routed: bool  # True when the router chose the expert, False when the person did
    classification: Classification


def decide(classification: Classification, choice: str = "auto") -> Route:
    """What to do with a question, from its label probabilities and the person's expert choice.

    The scope check runs on every question, so choosing an expert cannot get a medical question
    answered. Consults are the router's call: the other experts whose data the question needs.
    """
    if choice != "auto" and choice not in EXPERTS:
        raise ValueError(f"unknown expert {choice!r}")
    p = classification.probabilities
    if p[OUT_OF_SCOPE] >= REFUSE_AT:
        return Route("refuse", None, (), choice == "auto", classification)
    if p[CONVERSATION] >= RECALL_AT:
        # Whoever was picked, a question about the chat is answered from the chat.
        return Route("conversation", None, (), choice == "auto", classification)
    needs = classification.needs
    ranked = sorted(EXPERT_LABELS, key=lambda label: needs[label], reverse=True)
    if choice != "auto":
        lead, routed = choice, False
    else:
        top = max((*EXPERT_LABELS, GENERAL), key=lambda label: p[label])
        if top == GENERAL or p[top] < LEAD_AT:
            return Route("general", None, (), True, classification)
        lead, routed = top, True
    consult = tuple(e for e in ranked if e != lead and needs[e] >= CONSULT_AT)
    return Route("expert", lead, consult, routed, classification)
