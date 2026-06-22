from langchain_core.messages import AIMessage, HumanMessage

from backend.mcp_server.agents.graph import _latest_user_question, _recent_history


def test_latest_user_question_returns_last_human():
    msgs = [HumanMessage(content="first"), AIMessage(content="reply"), HumanMessage(content="second")]
    assert _latest_user_question(msgs) == "second"


def test_latest_user_question_empty():
    assert _latest_user_question([]) == ""


def test_recent_history_excludes_current_question():
    msgs = [
        HumanMessage(content="How is Apple doing?"),
        AIMessage(content="Apple is up."),
        HumanMessage(content="And the price?"),
    ]
    history = _recent_history(msgs)
    assert "And the price?" not in history
    assert "User: How is Apple doing?" in history
    assert "Assistant: Apple is up." in history


def test_recent_history_empty_on_first_turn():
    msgs = [HumanMessage(content="How is Apple doing?")]
    assert _recent_history(msgs) == ""


def test_recent_history_respects_turn_limit():
    msgs = []
    for i in range(20):
        msgs.append(HumanMessage(content=f"q{i}"))
        msgs.append(AIMessage(content=f"a{i}"))
    msgs.append(HumanMessage(content="current"))
    history = _recent_history(msgs, max_turns=4)
    assert history.count("\n") == 3
    assert "current" not in history
