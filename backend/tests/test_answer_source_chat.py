""" "Where does that figure come from?" through the chat: answered from the stored last answer.

The unit tests of `app.agent.provenance` build history turns by hand; this goes through /chat,
so the history is the stored messages, as in the app.
"""

from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_clauses import data, dates, said

from app.agent.llm import ScriptedLLM


def post(client, headers, agent, words, reading, conversation=None):
    agent.llm.request_turns = [ScriptedLLM.call("read_request", **reading)]
    body = {"text": words} | ({"conversationId": conversation} if conversation else {})
    response = client.post("/chat", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()[-1]


def test_a_source_question_after_a_data_answer_names_its_records_and_days(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    words = "Total steps from 2026-08-03 to 2026-08-09?"
    first = post(
        client,
        headers,
        agent,
        words,
        said(data(words, ["steps"], "sum", dates("2026-08-03", "2026-08-09"))),
    )
    assert first["evidenceIds"]
    asked = "Where does that figure come from?"
    reply = post(
        client,
        headers,
        agent,
        asked,
        said({"type": "source", "said": asked}),
        first["conversationId"],
    )
    assert (
        "your own records" in reply["text"]
        and "Aug 3" in reply["text"]
        and "Aug 9" in reply["text"]
    )
    assert "keep" not in reply["text"].casefold()  # never an answer about saved memory
    assert not reply["evidenceIds"]  # nothing new is read for it


def test_a_source_question_with_nothing_before_it_says_so(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    asked = "Where did that come from?"
    reply = post(client, headers, agent, asked, said({"type": "source", "said": asked}))
    assert "no earlier answer" in reply["text"]
