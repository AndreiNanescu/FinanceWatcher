"""Deterministic core of the agent graph: price summarization, markdown
stripping, history rendering, and Plan clamping inputs."""

import json

from backend.agents.graph import (
    Company,
    Plan,
    _latest_user_question,
    _recent_history,
    _strip_markdown,
    _summarize_prices,
)
from backend.config import config
from langchain_core.messages import AIMessage, HumanMessage

OHLCV = {
    "2026-07-01": {"Open": 99.0, "High": 105.0, "Low": 98.0, "Close": 100.0, "Volume": 1_000},
    "2026-07-02": {"Open": 101.0, "High": 112.0, "Low": 100.0, "Close": 104.0, "Volume": 3_000},
    "2026-07-03": {"Open": 105.0, "High": 111.0, "Low": 96.0, "Close": 110.0, "Volume": 2_000},
}


def test_summarize_prices_computes_change_and_range():
    s = _summarize_prices("Apple (AAPL)", 30, OHLCV)
    assert "closed at 110.00" in s
    assert "versus 100.00" in s
    assert "up 10.0%" in s
    assert "96.00 to 112.00" in s  # period low/high from Low/High columns
    assert "2,000" in s  # average volume, thousands-separated
    assert "3 trading days" in s
    assert "only price facts available" in s  # the anti-hallucination tail


def test_summarize_prices_accepts_json_string():
    assert "up 10.0%" in _summarize_prices("X", 7, json.dumps(OHLCV))


def test_summarize_prices_falls_back_on_garbage():
    assert _summarize_prices("X", 7, "not json").startswith("Price for X (last 7 days):")
    assert _summarize_prices("X", 7, {}).startswith("Price for X (last 7 days):")
    no_closes = {"2026-07-01": {"Open": 1.0}}
    assert _summarize_prices("X", 7, no_closes).startswith("Price for X (last 7 days):")


def test_summarize_prices_flat_and_down_direction():
    flat = {k: {**v, "Close": 100.0} for k, v in OHLCV.items()}
    assert "flat 0.0%" in _summarize_prices("X", 7, flat)
    down = dict(OHLCV)
    down["2026-07-03"] = {**OHLCV["2026-07-03"], "Close": 90.0}
    assert "down 10.0%" in _summarize_prices("X", 7, down)


def test_strip_markdown_removes_structures_keeps_prose():
    text = "## Heading\n**Bold** claim\n- bullet one\n* bullet two\n\n\n\nEnd __here__."
    out = _strip_markdown(text)
    assert "##" not in out and "**" not in out and "__" not in out
    assert "- bullet" not in out and "* bullet" not in out
    assert "Bold claim" in out and "bullet one" in out and "End here." in out
    assert "\n\n\n" not in out  # collapsed newlines


def test_strip_markdown_preserves_inline_asterisk_free_text():
    clean = "Apple rose 3% on strong earnings. No formatting here."
    assert _strip_markdown(clean) == clean


def test_latest_user_question_picks_last_human():
    msgs = [HumanMessage(content="first"), AIMessage(content="answer"), HumanMessage(content="second")]
    assert _latest_user_question(msgs) == "second"
    assert _latest_user_question([]) == ""


def test_recent_history_excludes_current_question_and_labels_roles():
    msgs = [
        HumanMessage(content="q1"),
        AIMessage(content="a1"),
        HumanMessage(content="q2"),  # current question — must be excluded
    ]
    rendered = _recent_history(msgs)
    assert "User: q1" in rendered
    assert "Assistant: a1" in rendered
    assert "q2" not in rendered


def test_recent_history_respects_max_turns():
    msgs = []
    for i in range(10):
        msgs.append(HumanMessage(content=f"q{i}"))
        msgs.append(AIMessage(content=f"a{i}"))
    msgs.append(HumanMessage(content="current"))
    rendered = _recent_history(msgs, max_turns=2)
    assert rendered.count("\n") == 1  # exactly two rendered lines
    assert "a9" in rendered


def test_plan_defaults_come_from_config():
    plan = Plan()
    assert plan.price_days == config.agent.price_lookback_days
    assert plan.news_count == config.agent.default_news_count
    assert plan.needs_news is True
    assert plan.companies == []


def test_company_defaults_fetch_everything_with_no_focus():
    c = Company(name="Apple", ticker="AAPL")
    assert c.needs_news is True and c.needs_price is True
    assert c.news_focus == ""
