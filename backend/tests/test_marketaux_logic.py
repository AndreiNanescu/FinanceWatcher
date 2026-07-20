"""Deterministic core of the MarketAux gatherer: response cleaning, dedup
seeding, blacklist filtering, entity clustering, and day-range planning.

MarketAuxGatherer.__init__ launches a browser, so instances are built with
__new__ and only the attributes _clean_data actually reads."""

from backend.data_pipeline.gatherers.marketaux import MarketAuxGatherer
from backend.utils import Entity


def _gatherer(uuids=(), urls=(), blacklist=()) -> MarketAuxGatherer:
    g = MarketAuxGatherer.__new__(MarketAuxGatherer)
    g.uuids = list(uuids)
    g.urls = list(urls)
    g.blacklist = list(blacklist)
    g.stats = {"duplicates": 0, "blacklisted": 0}
    return g


def _api_article(uuid="u1", url="https://news.example.com/a1", **overrides):
    base = {
        "uuid": uuid,
        "title": "Apple beats",
        "description": "desc",
        "url": url,
        "published_at": "2026-07-01T10:00:00.000000Z",
        "entities": [
            {"symbol": "AAPL", "name": "Apple Inc", "sentiment_score": 0.5, "industry": "Technology"},
        ],
    }
    base.update(overrides)
    return base


def test_clean_data_builds_articles_with_formatted_sentiment():
    g = _gatherer()
    articles = g._clean_data([{"data": [_api_article()]}])
    assert len(articles) == 1
    art = articles[0]
    assert art.uuid == "u1"
    assert art.full_text is None  # populated later by the scraper stage
    assert art.entities[0].symbol == "AAPL"
    assert art.entities[0].sentiment == "Positive (0.50)"


def test_clean_data_dedups_on_seen_uuid_and_url():
    g = _gatherer(uuids=["known-uuid"], urls=["https://news.example.com/known"])
    data = [
        {
            "data": [
                _api_article(uuid="known-uuid", url="https://news.example.com/new1"),  # uuid dupe
                _api_article(uuid="fresh", url="https://news.example.com/known"),  # url dupe
                _api_article(uuid="fresh2", url="https://news.example.com/new2"),  # genuinely new
            ]
        }
    ]
    articles = g._clean_data(data)
    assert [a.uuid for a in articles] == ["fresh2"]
    assert g.stats["duplicates"] == 2


def test_clean_data_dedups_within_single_batch():
    g = _gatherer()
    same = _api_article()
    articles = g._clean_data([{"data": [same, same]}])
    assert len(articles) == 1
    assert g.stats["duplicates"] == 1


def test_clean_data_blacklists_by_url_and_domain():
    g = _gatherer(blacklist=["https://bad.example.com/x", "paywall.example.com"])
    data = [
        {
            "data": [
                _api_article(uuid="a", url="https://bad.example.com/x"),  # exact url
                _api_article(uuid="b", url="https://paywall.example.com/anything"),  # netloc match
                _api_article(uuid="c", url="https://ok.example.com/fine"),
            ]
        }
    ]
    articles = g._clean_data(data)
    assert [a.uuid for a in articles] == ["c"]
    assert g.stats["blacklisted"] == 2


def test_deduplicate_entities_merges_same_company_prefers_simple_symbol():
    ents = [
        Entity(symbol="AAPL.BA", name="Apple Incorporated", sentiment="Neutral (0.00)"),
        Entity(symbol="AAPL", name="Apple Inc", sentiment="Neutral (0.00)"),
        Entity(symbol="MSFT", name="Microsoft Corporation", sentiment="Neutral (0.00)"),
    ]
    deduped = MarketAuxGatherer._deduplicate_entities(ents)
    symbols = sorted(e.symbol for e in deduped)
    assert symbols == ["AAPL", "MSFT"]  # Apples merged; dot-free symbol won


def test_build_day_range_both_bounds_inclusive():
    days = MarketAuxGatherer._build_day_range("2026-01-01", "2026-01-03", days=99)
    assert days == ["2026-01-01", "2026-01-02", "2026-01-03"]


def test_build_day_range_walks_back_from_before():
    days = MarketAuxGatherer._build_day_range(None, "2026-01-05", days=3)
    assert days == ["2026-01-03", "2026-01-04", "2026-01-05"]


def test_build_day_range_walks_forward_from_after():
    days = MarketAuxGatherer._build_day_range("2026-01-01", None, days=3)
    assert days == ["2026-01-01", "2026-01-02", "2026-01-03"]


def test_build_day_range_swaps_inverted_bounds_and_rejects_bad_format():
    assert MarketAuxGatherer._build_day_range("2026-01-03", "2026-01-01", days=1) == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert MarketAuxGatherer._build_day_range("01/01/2026", None, days=1) == []
