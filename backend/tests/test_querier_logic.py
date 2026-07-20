"""Deterministic core of the Querier: candidate shaping, date filtering,
recency math, ticker extraction, and the cosine baseline ranking.

Querier.__init__ needs a live Chroma client, so instances are built with
__new__ plus the attributes each method actually reads."""

from datetime import UTC, datetime, timedelta

from backend.config import config
from backend.data.chroma.query_service import Querier

WIRE_FMT = "%Y-%m-%dT%H:%M:%SZ"


class _StubEmbedder:
    def __init__(self, vector):
        self._vector = vector

    def embed(self, text):
        return [self._vector]


class _StubClient:
    def __init__(self, vector):
        self.embedder = _StubEmbedder(vector)


def _querier(**attrs) -> Querier:
    q = Querier.__new__(Querier)
    q.recency_weight = attrs.get("recency_weight", config.retrieval.recency_weight)
    q.recency_tau_days = attrs.get("recency_tau_days", config.retrieval.recency_tau_days)
    q.max_rerank_candidates = attrs.get("max_rerank_candidates", config.retrieval.max_rerank_candidates)
    q.use_reranker = attrs.get("use_reranker", True)
    q.client = attrs.get("client")
    q.reranker = None
    return q


def _candidate(days_old: int, doc: str = "doc", embedding=None) -> dict:
    published = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_old)).strftime(WIRE_FMT)
    cand = {"id": doc, "document": doc, "metadata": {"published_at": published}, "score": 0.0}
    if embedding is not None:
        cand["embedding"] = embedding
    return cand


def test_extract_ticker_reads_parenthesized_symbols():
    assert Querier._extract_ticker("Apple (AAPL) earnings") == ["AAPL"]
    assert Querier._extract_ticker("Apple (AAPL) vs Microsoft (MSFT)") == ["AAPL", "MSFT"]
    assert Querier._extract_ticker("no ticker here") is None


def test_filter_by_date_keeps_recent_drops_old_and_unparseable():
    q = _querier()
    recent, old = _candidate(days_old=30), _candidate(days_old=300)
    undated = {"document": "x", "metadata": {}, "score": 0.0}
    kept = q._filter_by_date([recent, old, undated], months=6)
    assert kept == [recent]


def test_cap_recent_keeps_newest_up_to_limit():
    q = _querier()
    cands = [_candidate(days_old=d, doc=f"d{d}") for d in (50, 5, 100, 1)]
    capped = q._cap_recent(cands, limit=2)
    assert [c["document"] for c in capped] == ["d1", "d5"]
    assert q._cap_recent(cands, limit=10) == cands  # under limit: untouched


def test_recency_factor_bounds_and_decay():
    q = _querier(recency_weight=0.3, recency_tau_days=30.0)
    fresh = q._recency_factor(datetime.now(UTC).replace(tzinfo=None).strftime(WIRE_FMT))
    old = q._recency_factor("2020-01-01T00:00:00Z")
    assert 0.99 <= fresh <= 1.0
    assert abs(old - 0.7) < 0.01  # decays toward (1 - weight)
    assert q._recency_factor(None) == 0.7  # unparseable date: no recency boost
    assert q._recency_factor("garbage") == 0.7


def test_rank_by_cosine_orders_by_dot_product_and_caps():
    q = _querier(client=_StubClient(vector=[1.0, 0.0]))
    cands = [
        _candidate(1, doc="orthogonal", embedding=[0.0, 1.0]),
        _candidate(1, doc="aligned", embedding=[1.0, 0.0]),
        _candidate(1, doc="partial", embedding=[0.5, 0.5]),
    ]
    ranked = q._rank_by_cosine("query", cands, top_n=2)
    assert [r["document"] for r in ranked] == ["aligned", "partial"]
    assert ranked[0]["final_score"] == 1.0
    assert ranked[0]["reranker_score"] is None  # cosine path never fakes a rerank score


def test_rank_by_cosine_falls_back_to_negated_distance_without_embeddings():
    q = _querier(client=_StubClient(vector=[1.0, 0.0]))
    near = {"id": "near", "document": "near", "metadata": {}, "score": 0.1}  # small distance
    far = {"id": "far", "document": "far", "metadata": {}, "score": 0.9}
    ranked = q._rank_by_cosine("query", [far, near], top_n=2)
    assert [r["document"] for r in ranked] == ["near", "far"]


def test_build_candidates_zips_chroma_result_lists():
    raw = {
        "ids": [["a", "b"]],
        "documents": [["doc a", "doc b"]],
        "metadatas": [[{"k": 1}, {"k": 2}]],
        "distances": [[0.1, 0.2]],
    }
    cands = Querier._build_candidates(raw)
    assert [c["id"] for c in cands] == ["a", "b"]
    assert cands[1]["score"] == 0.2
