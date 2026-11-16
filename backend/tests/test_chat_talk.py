"""Messages that ask nothing of the data get a reply, not a data run; what the person says in a chat
shapes the answers that follow; day answers state their figures; wear talk without a gap goes."""

from datetime import date

import pytest

from app.agent.agent import Claim, without_coverage_talk
from app.agent.ask import ask, told_here
from app.agent.context import ChatState, Turn
from app.agent.conversation import CHAT_FALLBACKS, chat_kind
from app.agent.intent import Intent
from app.agent.llm import ScriptedLLM
from app.agent.router import EXPERT_LABELS, LABELS, Classification, KeywordRouter
from app.agent.strategy import figures_check
from app.agent.strategy_types import is_small_talk, is_statement, offer_in
from app.analysis.day import with_scores
from app.synthetic import generate

START = date(2026, 7, 1)


@pytest.fixture(scope="module")
def frame():
    return with_scores(generate(START, 60, seed=4).frame)


class Router:
    def __init__(self, question_type, *, action_topic="sleep", intent=Intent.READ):
        self.seen: list[str] = []
        self.result = Classification(
            dict.fromkeys(LABELS, 0.0) | {action_topic: 0.9},
            dict.fromkeys(EXPERT_LABELS, 0.0),
            source="test",
            intent_probabilities={str(i): float(i == intent) for i in Intent},
            question_types={question_type: 1.0} if question_type else {},
        )

    def classify(self, question, earlier=()):
        self.seen.append(question)
        return self.result


@pytest.mark.parametrize(
    "message",
    [
        "Hi",
        "hey there!",
        "thanks",
        "ok cool",
        "that's wrong",
        "thats not what i asked",
        "what can you do?",
        "im a student i had a few projects thats why i didnt have time to sleep much",
    ],
)
def test_small_talk_and_statements_are_chat(message):
    assert is_small_talk(message)
    assert KeywordRouter().classify(message).question_type == "chat"


@pytest.mark.parametrize(
    "message",
    [
        "how did i sleep today",
        "CAN u give me advice on how to sleep better",
        "I want to sleep better, any tips",
        "why is my sleep worse lately?",
        "and yesterday",
        "show me my steps",
        "Hello! How did I sleep?",
        "thanks, what was my resting HR yesterday?",
    ],
)
def test_questions_and_requests_are_not_chat(message):
    assert not is_small_talk(message)


def test_a_fact_inside_a_question_is_no_statement():
    assert is_statement("I'm a student and I had projects")
    assert not is_statement("I'm a student, how much should I sleep?")
    assert not is_statement("Can you remind me I have exams")


def test_hi_gets_a_reply_without_any_data_run(frame):
    llm = ScriptedLLM([ScriptedLLM.say("Hey! Want to see how last night went?")])
    reply = ask(llm, Router("why"), frame, "Hi")  # code is sure, whatever the router says
    assert reply.result.stop_reason == "chatted"
    assert reply.result.summary == "Hey! Want to see how last night went?"
    assert not llm.requests[0].get("tools")  # one call, no tools
    assert reply.result.claims == []


def test_a_statement_is_connected_to_the_chat_not_tested(frame):
    history = [Turn("how did i sleep today", "You slept 5 h 40 min on Nov 14, under your usual.")]
    words = "Projects, that fits the short night on Nov 14. Want ideas that fit around them?"
    llm = ScriptedLLM([ScriptedLLM.say(words)])
    message = "im a student i had a few projects thats why i didnt have time to sleep much"
    reply = ask(llm, Router("chat"), frame, message, history=history)
    assert reply.result.summary == words
    task = llm.requests[0]["messages"][1]["content"]
    assert "5 h 40 min" in task and "latest message" in task


def test_hi_routed_to_the_conversation_is_still_a_chat(frame):
    # The router may call "Hi" a remark about the chat: the recall reply then answered "There are
    # no earlier messages in this chat yet." (the first real run, 2026-11-14).
    llm = ScriptedLLM([ScriptedLLM.say("Hey! How can I help today?")])
    reply = ask(llm, Router("chat", action_topic="conversation"), frame, "Hi")
    assert reply.result.stop_reason == "chatted"


def test_a_chat_reply_with_a_new_number_falls_back(frame):
    llm = ScriptedLLM([ScriptedLLM.say("Hi! You slept 7 h 30 min last night.")])
    reply = ask(llm, Router("chat"), frame, "Hi")
    assert reply.result.stop_reason == "chat_fallback"
    assert reply.result.summary == CHAT_FALLBACKS["greeting"]


def test_a_question_the_router_calls_chat_still_gets_its_data(frame):
    # "?" in a message that code does not know as small talk: the data run answers it.
    llm = ScriptedLLM([ScriptedLLM.say("ignored")])
    reply = ask(llm, Router("chat"), frame, "how is my sleep doing?")
    assert reply.result.stop_reason != "chatted"


@pytest.mark.parametrize(
    "message, kind",
    [
        ("Hello", "greeting"),
        ("thanks!", "thanks"),
        ("that's wrong", "reaction"),
        ("what can you do?", "capabilities"),
        ("I'm a student with deadlines", "statement"),
    ],
)
def test_each_kind_has_its_fallback(message, kind):
    assert chat_kind(message) == kind


def test_yes_takes_up_the_offer_the_last_answer_ended_on(frame):
    router = Router("coaching")
    history = [Turn("I had projects", "Makes sense. Want some ideas that fit around deadlines?")]
    ask(ScriptedLLM([]), router, frame, "yes please", history=history)
    assert router.seen[0] == "Give me some ideas that fit around deadlines."


def test_offer_in_finds_only_a_closing_question():
    assert offer_in("You slept 6 h. Want a reminder?") == "Want a reminder?"
    assert offer_in("Why? You slept 6 h. The rest was normal.") is None


def test_what_they_said_in_this_chat_reaches_the_advice(frame):
    history = [
        Turn("how did i sleep today", "You slept 5 h 40 min."),
        Turn("I'm a student with project deadlines this month", "That fits."),
    ]
    assert told_here(history) == ["I'm a student with project deadlines this month"]
    llm = ScriptedLLM([])  # the run stops at once; what matters is what it was given
    ask(
        llm,
        Router("coaching"),
        frame,
        "how can I sleep better?",
        history=history,
        chat=ChatState(),
    )
    task = llm.requests[0]["messages"][1]["content"]
    assert "student with project deadlines" in task


def test_a_day_answer_must_give_its_figures():
    day = Claim(text="Short night.", kind="day", evidence_ids=["e"], metric="sleep_minutes")
    assert figures_check([day], "You slept less than usual on Nov 14.")
    assert not figures_check([day], "You slept 5 h 40 min on Nov 14, under your usual 7 h.")
    assert not figures_check([], "Nothing to say.")


def test_wear_talk_without_a_gap_is_dropped():
    text = "Bedtime held. Low wear time does not stand out as an explanation for the short sleep."
    assert without_coverage_talk(text) == "Bedtime held."
    gap = "You slept 6 h. Three nights are missing, so the week is thin."
    assert without_coverage_talk(gap) == gap


def test_why_after_no_change_says_there_is_nothing_to_explain(frame):
    steady = Turn(
        "Is my resting heart rate going up lately?",
        "Not really, it held steady.",
        claims=({"kind": "no_change", "evidence_ids": ["e"], "metric": "resting_hr"},),
    )
    llm = ScriptedLLM([])
    ask(llm, Router("why"), frame, "why?", history=[steady])
    run = llm.requests[-1]  # after the follow-up rewrite
    assert "nothing to explain" in run["messages"][1]["content"]
    assert set(run["tools"]) >= {"describe", "compare_windows"}
    assert "correlate" not in run["tools"]


def test_why_after_a_real_change_still_looks_for_causes(frame):
    moved = Turn(
        "Is my resting heart rate going up lately?",
        "Yes, it rose.",
        claims=({"kind": "change", "evidence_ids": ["e"], "metric": "resting_hr"},),
    )
    llm = ScriptedLLM([])
    ask(llm, Router("why"), frame, "why?", history=[moved])
    assert "nothing to explain" not in llm.requests[-1]["messages"][1]["content"]


def test_a_wrong_weekday_is_caught():
    from app.agent.verifier import wrong_weekdays

    assert wrong_weekdays("On Fri Nov 14 your HRV dipped.", {2026}) == ["Fri Nov 14"]
    assert wrong_weekdays("On Saturday, Nov 14 and Friday Nov 13.", {2026}) == []


def test_a_detail_after_a_question_gets_no_period():
    from app.agent.followup import with_period

    assert with_period("At noon.", [Turn("How much protein did I eat yesterday?", "-")]) == (
        "At noon."
    )


def test_the_period_is_carried_by_code():
    from app.agent.followup import with_period

    month = [Turn("What's my average sleep this month?", "7 h 17 min.")]
    assert with_period("what was my best night?", month) == "what was my best night this month?"
    assert with_period("and my worst?", month) == "and my worst this month?"
    assert with_period("what was my best night last week?", month).endswith("last week?")
    assert with_period("I slept badly", month) == "I slept badly"


def test_a_second_refusal_in_a_row_is_worded_differently(frame):
    from app.agent.ask import MEDICAL_AGAIN, MEDICAL_REFUSAL

    first = Turn("Do I have sleep apnea?", MEDICAL_REFUSAL)
    router = Router(None, action_topic="out_of_scope")
    reply = ask(ScriptedLLM([]), router, frame, "should I take melatonin?", history=[first])
    assert reply.result.summary == MEDICAL_AGAIN


def test_a_watch_alarm_request_says_it_is_a_reminder_instead():
    from app.reminders.tools import NO_WATCH_ALARMS, reminder_reply

    text = reminder_reply("Tap Set on the card.", [("Wake up", "Every day at 07:00")], True)
    assert text.startswith(NO_WATCH_ALARMS) and "07:00" in text


def test_7am_in_their_message_is_a_time_they_gave():
    from app.agent.verifier import _quoted_clock_times

    assert _quoted_clock_times("an alarm for 7am") == [7]
