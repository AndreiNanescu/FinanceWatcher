"""Round-trip tests for cross-boundary string contracts.

Each contract has a producer and a consumer on opposite sides of a module or
process boundary. These tests exercise producer output against consumer logic
directly, so a rewording on either side fails here instead of silently
degrading answers in production.
"""

from datetime import UTC, datetime

from backend.utils import (
    KEYWORDS_LINE_PREFIX,
    NO_NEWS_AVAILABLE_SENTINEL,
    NO_RELEVANT_NEWS_MESSAGE,
    Article,
    NewsDocument,
    parse_published_at,
    strip_keywords_line,
)


def _article(**overrides) -> Article:
    base = dict(
        uuid="u-1",
        title="Apple beats expectations",
        description="Apple reported strong quarterly results.",
        keywords="apple, earnings, revenue",
        url="https://example.com/a",
        published_at="2026-07-01T12:00:00.000000Z",
        fetched_on="July 01, 2026 at 12:30 PM",
        entities=[],
    )
    base.update(overrides)
    return Article(**base)


# --- keywords line: written by NewsDocument, stripped by the MCP server ------


def test_keywords_line_roundtrip():
    doc = NewsDocument.from_article(_article())
    assert KEYWORDS_LINE_PREFIX in doc.content  # producer wrote it

    stripped = strip_keywords_line(doc.content)
    assert KEYWORDS_LINE_PREFIX not in stripped  # consumer removed it
    assert "Apple beats expectations" in stripped  # and nothing else
    assert "strong quarterly results" in stripped


def test_strip_keywords_line_only_strips_line_start():
    text = f"Title: x\nBody mentions {KEYWORDS_LINE_PREFIX} mid-sentence\n{KEYWORDS_LINE_PREFIX} a, b\nEnd"
    stripped = strip_keywords_line(text)
    assert "mid-sentence" in stripped  # inline mention untouched
    assert f"\n{KEYWORDS_LINE_PREFIX} a, b" not in stripped  # real line removed


# --- no-news sentinels: tool -> gather -> synthesis prompt -------------------


def test_empty_retrieval_message_detected_by_gather():
    from backend.mcp_server.agents.graph import _is_no_news

    assert _is_no_news(NO_RELEVANT_NEWS_MESSAGE)
    assert _is_no_news(f"  {NO_RELEVANT_NEWS_MESSAGE.upper()}  ")  # case/space robust
    assert not _is_no_news("Apple had news today.")


def test_no_news_sentinel_reaches_synthesis_rules():
    from backend.mcp_server.agents.prompts import SYNTHESIS_SYSTEM_PROMPT

    # The grounding rules must reference the exact sentinel the gather node
    # writes; if either side drifts, permission to say "no recent news" breaks.
    assert NO_NEWS_AVAILABLE_SENTINEL in SYNTHESIS_SYSTEM_PROMPT


# --- planner prompt freshness (regression for the frozen-_DATETIME bug) ------


def test_planner_prompt_contains_current_datetime():
    from backend.mcp_server.agents.prompts import build_planner_system_prompt

    before = datetime.now(UTC).strftime("%Y-%m-%d")
    prompt = build_planner_system_prompt()
    after = datetime.now(UTC).strftime("%Y-%m-%d")
    # Accept either date to stay flake-free across a midnight boundary.
    assert (before in prompt) or (after in prompt)
    assert "Current datetime:" in prompt


def test_planner_prompt_is_rebuilt_per_call():
    import backend.mcp_server.agents.prompts as prompts

    # The bug this guards against: a module-level timestamp frozen at import.
    # A callable rebuilt per request must not be importable as a constant str.
    assert callable(prompts.build_planner_system_prompt)
    assert not isinstance(getattr(prompts, "PLANNER_SYSTEM_PROMPT", None), str)


# --- published_at parsing: one path for every consumer -----------------------


def test_parse_published_at_both_wire_formats():
    with_micros = parse_published_at("2026-07-01T12:34:56.000000Z")
    without = parse_published_at("2026-07-01T12:34:56Z")
    assert with_micros == without == datetime(2026, 7, 1, 12, 34, 56)


def test_parse_published_at_rejects_garbage():
    assert parse_published_at(None) is None
    assert parse_published_at("") is None
    assert parse_published_at("no date") is None
    assert parse_published_at("2026-07-01") is None  # date-only is not a wire format


def test_querier_delegates_to_shared_parser():
    from backend.data.chroma.query_service import Querier

    assert Querier._parse_published_at("2026-07-01T12:34:56Z") == parse_published_at("2026-07-01T12:34:56Z")
    assert Querier._parse_published_at("garbage") is None
