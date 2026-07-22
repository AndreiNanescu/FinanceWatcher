"""Fixture tests for the corpus-stats aggregations.

These pin the numbers the Phase 2 migration parity check will lean on: the
per-ticker coverage and corpus statistics must be computed identically before
and after the storage swap. Pure functions only — no DB, no Chroma.
"""

from backend.corpus_stats import corpus_statistics, ticker_coverage_analysis
from backend.utils import Article, Entity


def _article(
    uuid: str = "u",
    url: str = "https://www.example.com/a",
    published_at: str = "2026-06-01T12:00:00.000000Z",
    full_text: str | None = "x" * 1000,
    full_text_status: str | None = "ok",
    symbols: tuple[str, ...] = ("AAPL",),
) -> Article:
    return Article(
        uuid=uuid,
        title="t",
        description="d",
        keywords="k",
        url=url,
        published_at=published_at,
        fetched_on="whenever",
        entities=[Entity(symbol=s, name=s, sentiment="Neutral (0.00)") for s in symbols],
        full_text=full_text,
        full_text_status=full_text_status,
    )


# --- corpus_statistics -------------------------------------------------------


def test_corpus_statistics_lengths_and_flags():
    articles = [
        _article(uuid="a", full_text="x" * 1000),
        _article(uuid="b", full_text="y" * 100),   # under 300
        _article(uuid="c", full_text="", full_text_status="failed"),  # empty + under 300
    ]
    stats = corpus_statistics(articles)
    t = stats["text_lengths"]
    assert stats["article_count"] == 3
    assert t["min"] == 0
    assert t["max"] == 1000
    assert t["under_300"] == 2
    assert t["empty"] == 1


def test_corpus_statistics_status_and_domain_distribution():
    articles = [
        _article(uuid="a", url="https://www.finance.yahoo.com/x", full_text_status="ok"),
        _article(uuid="b", url="https://finance.yahoo.com/y", full_text_status="ok"),   # www stripped -> same domain
        _article(uuid="c", url="https://seekingalpha.com/z", full_text_status="failed"),
    ]
    stats = corpus_statistics(articles)
    assert stats["status_distribution"] == {"ok": 2, "failed": 1}
    assert stats["domain_distribution"]["finance.yahoo.com"] == 2  # www. normalized away
    assert stats["domain_distribution"]["seekingalpha.com"] == 1


def test_corpus_statistics_empty_corpus_does_not_crash():
    # A fresh/empty DB must produce a report, not a ZeroDivisionError/ValueError.
    stats = corpus_statistics([])
    assert stats["article_count"] == 0


# --- ticker_coverage_analysis ------------------------------------------------


def test_ticker_coverage_counts_only_watchlist_symbols():
    articles = [
        _article(uuid="a", symbols=("AAPL",)),
        _article(uuid="b", symbols=("AAPL", "ZZZZ")),   # ZZZZ not on the watchlist
        _article(uuid="c", symbols=("NVDA",)),
    ]
    cov = ticker_coverage_analysis(articles)
    assert cov["AAPL"]["count"] == 2
    assert cov["NVDA"]["count"] == 1
    assert "ZZZZ" not in cov                 # non-watchlist entity never becomes a key


def test_ticker_coverage_reports_zero_for_uncovered_watchlist_tickers():
    cov = ticker_coverage_analysis([_article(symbols=("AAPL",))])
    # Every watchlist symbol appears; uncovered ones read as an explicit zero.
    assert cov["RTX"]["count"] == 0
    assert cov["RTX"]["oldest"] is None


def test_ticker_coverage_oldest_newest():
    articles = [
        _article(uuid="a", symbols=("AAPL",), published_at="2026-05-01T00:00:00.000000Z"),
        _article(uuid="b", symbols=("AAPL",), published_at="2026-06-01T00:00:00.000000Z"),
    ]
    cov = ticker_coverage_analysis(articles)
    assert cov["AAPL"]["oldest"] == "2026-05-01T00:00:00.000000Z"
    assert cov["AAPL"]["newest"] == "2026-06-01T00:00:00.000000Z"


def test_ticker_coverage_survives_unparseable_date():
    # marketaux defaults published_at to "no date" when the field is missing;
    # one such row must not crash the whole report.
    articles = [
        _article(uuid="a", symbols=("AAPL",), published_at="no date"),
        _article(uuid="b", symbols=("AAPL",), published_at="2026-06-01T00:00:00.000000Z"),
    ]
    cov = ticker_coverage_analysis(articles)
    assert cov["AAPL"]["count"] == 2
