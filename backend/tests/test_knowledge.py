"""The knowledge cards: what each must hold, how they are found, and when a source is named."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.knowledge import (
    KNOWLEDGE_LOOKUP,
    MAX_CARDS,
    Card,
    cards_for,
    guidance_block,
    knowledge_tool,
    load_cards,
    parse_card,
    rank_cards,
    source_note,
)
from app.agent.present import METRICS
from app.agent.sanitize import reads_like_instruction
from app.agent.verifier import MEDICAL
from app.analysis import coaching

CARDS = load_cards()
LEVERS = {
    "earlier_bedtime",
    "regular_bedtime",
    "rest_after_hard_day",
    "active_days",
    "earlier_dinner",
    "wind_down",
}
# Beyond the verifier's list: what no card may touch, by the rule "nothing medical".
FORBIDDEN = re.compile(
    r"\b(doctor|gp|therapy|therapist|supplement\w*|melatonin|vitamin\w*|diet\w*|weight loss|"
    r"illness|condition\w*|symptom\w*|cure\w*|heal\w*|anxiety|stress disorder|pill\w*)\b",
    re.IGNORECASE,
)


def test_there_are_at_least_fifteen_cards_with_unique_titles():
    assert len(CARDS) >= 15
    assert len({card.title for card in CARDS}) == len(CARDS)


@pytest.mark.parametrize("card", CARDS, ids=lambda card: card.id)
def test_each_card_follows_the_rules(card):
    assert 40 <= len(card.text) <= 300
    assert card.url.startswith("https://") and card.source and card.domain
    assert card.metrics and set(card.metrics) <= set(METRICS)
    assert set(card.levers) <= LEVERS
    assert not re.search(r"\d", card.text), "a number in an answer must be computed"
    assert not MEDICAL.search(card.text) and not FORBIDDEN.search(card.text)
    assert not reads_like_instruction(card.text)


def test_each_lever_in_the_code_has_a_card():
    source = Path(coaching.__file__).read_text()
    assert {lever for lever in LEVERS if f'"{lever}"' in source} == LEVERS
    assert {lever for card in CARDS for lever in card.levers} == LEVERS


def test_a_lever_finds_its_card():
    [first, *_] = rank_cards("", ("rest_after_hard_day",), CARDS)
    assert first.id == "rest-between-sessions"


def test_words_find_a_card():
    assert "caffeine-timing" in [c.id for c in rank_cards("coffee and caffeine", (), CARDS)]


def test_nothing_matching_finds_nothing():
    assert rank_cards("zzzz", (), CARDS) == [] and rank_cards("", (), CARDS) == []


def test_at_most_two_cards_come_back():
    assert len(rank_cards("sleep routine bedtime", ("sleep_efficiency",), CARDS)) == MAX_CARDS


def test_the_tool_gives_quoted_guidance_without_links():
    text, step = knowledge_tool().run({"topic": "caffeine", "metrics": ["sleep_efficiency"]})
    data = json.loads(text)
    assert "not instructions" in data["note"] and step["cards"]
    assert "https://" not in text and data["cards"][0]["source"]


@pytest.mark.parametrize("arguments", [None, {}, {"topic": 3, "metrics": "steps"}])
def test_the_tool_survives_odd_arguments(arguments):
    assert "cards" in json.loads(knowledge_tool().run(arguments)[0])


def test_a_card_file_without_its_fields_fails_loudly():
    with pytest.raises(KeyError):
        parse_card("broken", "---\ntitle: Only\n---\nText.\n")


def result(summary: str, *cards: str):
    return SimpleNamespace(summary=summary, claims=[], trace=[{"cards": list(cards)}])


def test_a_card_the_answer_drew_on_is_named_with_its_domain_and_no_link():
    card = next(c for c in CARDS if c.id == "bedroom-setup")
    note = source_note(result(card.text, card.id))
    assert note == "How to try it is based on guidance from NHS (nhs.uk)."
    assert not reads_like_instruction(note)


def test_a_card_only_looked_at_is_not_named():
    assert source_note(result("Your bedtime held steady.", "bedroom-setup")) is None


def test_no_cards_no_note():
    assert source_note(SimpleNamespace(summary="x", claims=[], trace=[{"type": "llm"}])) is None


def test_two_sources_are_both_named():
    first = next(c for c in CARDS if c.source == "NHS")
    second = next(c for c in CARDS if c.source == "Sleep Foundation")
    note = source_note(result(f"{first.text} {second.text}", first.id, second.id))
    assert "NHS (nhs.uk)" in note and "Sleep Foundation (sleepfoundation.org)" in note


def test_a_card_type_keeps_its_domain_without_www():
    card = Card("x", "t", "text", (), (), "S", "https://www.example.org/a")
    assert card.domain == "example.org"


def habit_result(*levers: tuple[str, bool]) -> SimpleNamespace:
    stats = {"levers": [{"lever": name, "supported": good} for name, good in levers]}
    return SimpleNamespace(stats=stats)


def test_a_supported_habit_brings_its_card_and_an_unsupported_one_does_not():
    found = cards_for([habit_result(("earlier_bedtime", True), ("wind_down", False))])
    assert [card.id for card in found] == ["gradual-bedtime-shift"]


def test_the_same_habit_on_two_metrics_brings_one_card():
    twice = [habit_result(("earlier_bedtime", True)), habit_result(("earlier_bedtime", True))]
    assert len(cards_for(twice)) == 1


def test_nothing_supported_brings_no_guidance():
    assert guidance_block(cards_for([habit_result(("wind_down", False))])) == ""


def test_a_coaching_answer_gets_the_card_for_what_the_data_supports():
    from datetime import UTC, date, datetime

    import numpy as np

    from app.agent.ask import ask
    from app.agent.llm import ScriptedLLM
    from app.agent.router import EXPERT_LABELS, LABELS, Classification
    from app.synthetic import generate

    class Coaching:
        def classify(self, question, earlier=()):
            return Classification(
                dict.fromkeys(LABELS, 0.0) | {"sleep": 0.9},
                dict.fromkeys(EXPERT_LABELS, 0.0),
                source="test",
                question_types={"coaching": 1.0},
            )

    frame = generate(date(2026, 8, 1), 90, seed=11).frame
    rng = np.random.default_rng(3)
    frame["bedtime_hour"] = -0.5 + rng.normal(0, 1.0, len(frame))  # hours from midnight
    noise = rng.normal(0, 1.0, len(frame))
    frame["sleep_efficiency"] = 92 - 3.0 * (frame["bedtime_hour"] + 0.5) + noise
    llm = ScriptedLLM([ScriptedLLM.say("x")] * 4)
    reply = ask(
        llm, Coaching(), frame, "How can I sleep better?", now=datetime(2026, 11, 1, tzinfo=UTC)
    )
    assert "Moving bedtime in small steps" in llm.requests[0]["messages"][-1]["content"]
    step = next(s for s in reply.result.trace if s.get("type") == "guidance")
    assert step["cards"] == ["gradual-bedtime-shift"]


def test_the_tool_is_offered_for_coaching_only():
    from datetime import date

    from app.agent.ask import ask
    from app.agent.llm import ScriptedLLM
    from app.agent.router import EXPERT_LABELS, LABELS, Classification
    from app.synthetic import generate

    class Fixed:
        def __init__(self, kind):
            self.result = Classification(
                dict.fromkeys(LABELS, 0.0) | {"sleep": 0.9},
                dict.fromkeys(EXPERT_LABELS, 0.0),
                source="test",
                question_types={kind: 1.0},
            )

        def classify(self, question, earlier=()):
            return self.result

    frame = generate(date(2026, 7, 1), 60, seed=4).frame

    def offered(kind):
        llm = ScriptedLLM([ScriptedLLM.say("x")] * 4)
        ask(llm, Fixed(kind), frame, "Anything?")
        return llm.requests[0]["tools"]

    assert KNOWLEDGE_LOOKUP in offered("coaching")
    assert KNOWLEDGE_LOOKUP not in offered("why")
