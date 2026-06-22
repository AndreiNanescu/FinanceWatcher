from datetime import datetime, timedelta

from backend.data.chroma.query_service import Querier


def _candidate(symbols: str, published_at: str = None) -> dict:
    meta = {"entity_symbols": symbols}
    if published_at is not None:
        meta["published_at"] = published_at
    return {"document": f"doc::{symbols}", "metadata": meta, "score": 0.1}


def test_filter_by_tickers_keeps_matching():
    cands = [_candidate("AAPL, MSFT"), _candidate("TSLA, RELIANCE.BO")]
    out = Querier._filter_by_tickers(cands, ["AAPL"])
    assert len(out) == 1
    assert out[0]["metadata"]["entity_symbols"] == "AAPL, MSFT"


def test_filter_by_tickers_drops_unrelated_cotagged():
    cands = [_candidate("TSLA, ^NSEI, RELIANCE.BO")]
    assert Querier._filter_by_tickers(cands, ["AAPL"]) == []
    assert len(Querier._filter_by_tickers(cands, ["TSLA"])) == 1


def test_filter_by_tickers_is_case_insensitive():
    cands = [_candidate("AAPL")]
    assert len(Querier._filter_by_tickers(cands, ["aapl"])) == 1


def test_filter_by_tickers_handles_empty_symbols():
    cands = [_candidate("")]
    assert Querier._filter_by_tickers(cands, ["AAPL"]) == []


def test_extract_ticker_single():
    assert Querier._extract_ticker("Apple (AAPL) outlook") == ["AAPL"]


def test_extract_ticker_multiple():
    assert Querier._extract_ticker("Apple (AAPL) vs Microsoft (MSFT)") == ["AAPL", "MSFT"]


def test_extract_ticker_none_when_absent():
    assert Querier._extract_ticker("how is apple doing") is None


def test_filter_by_date_keeps_recent_drops_old():
    recent = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    old = "2000-01-01T00:00:00.000000Z"
    cands = [_candidate("AAPL", recent), _candidate("MSFT", old)]
    out = Querier._filter_by_date(cands, months=6)
    assert len(out) == 1
    assert out[0]["metadata"]["published_at"] == recent


def test_filter_by_date_supports_no_microseconds_format():
    recent = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = Querier._filter_by_date([_candidate("AAPL", recent)], months=6)
    assert len(out) == 1


def test_filter_by_date_skips_missing_date():
    out = Querier._filter_by_date([_candidate("AAPL")], months=6)
    assert out == []
