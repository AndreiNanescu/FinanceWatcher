import math
import re
from datetime import UTC, datetime, timedelta

from backend.rag import BGEReranker
from backend.utils import Candidate, logger, symbol_flag_key

from .chroma_client import ChromaClient

# Recency weighting: final_score = reranker_score * ((1 - weight) + weight * decay)
# where decay = exp(-age_days / tau). So recency adjusts a relevant article's
# score by at most `weight`, enough to favour fresher news without letting a
# barely-relevant new article beat a clearly-relevant slightly-older one.
_RECENCY_WEIGHT = 0.3
_RECENCY_TAU_DAYS = 30.0

# Cap how many candidates we rerank, to bound CPU cost when a ticker has a lot
# of articles. We keep the most recent ones before reranking.
_MAX_RERANK_CANDIDATES = 120


class Querier:
    def __init__(self, chroma_client: ChromaClient, reranker: BGEReranker):
        if chroma_client is None:
            raise ValueError("chroma_client parameter cannot be None in Querier")

        self.reranker = reranker
        self.client = chroma_client

    def search(
        self,
        query_text: str,
        n_results: int = 50,
        contains_text: str | None = None,
        top_n_rerank: int = 5,
        threshold: float = 0.3,
        min_floor: float = 0.1,
        tickers: list[str] | None = None,
        rerank_query: str | None = None,
    ) -> list[dict]:

        rerank_query = rerank_query or query_text

        if tickers is None:
            tickers = self._extract_ticker(query_text)
        logger.info(f"Requested tickers {tickers}")

        if tickers:
            # Ticker-scoped retrieval: pull EVERY article tagged with the ticker
            # (DB-level metadata filter) so recall doesn't depend on the company
            # appearing in a global semantic top-k. The reranker then ranks them.
            candidates = self._get_by_tickers(tickers)
        else:
            raw_results = self._execute_query(
                query_text=query_text, n_results=n_results, filters=None, contains_text=contains_text
            )
            candidates = self._build_candidates(raw_results)

        if not candidates:
            return []

        recent_candidates = self._filter_by_date(candidates, months=6)
        if not recent_candidates:
            return []

        # Bound rerank cost: keep the most recent candidates if there are many.
        recent_candidates = self._cap_recent(recent_candidates, _MAX_RERANK_CANDIDATES)

        final_results = self._rerank_candidates(rerank_query, recent_candidates, top_n_rerank, threshold, min_floor)
        return final_results

    def _get_by_tickers(self, tickers: list[str]) -> list[dict]:
        keys = [symbol_flag_key(t) for t in tickers if t and t.strip()]
        if not keys:
            return []
        where = {keys[0]: True} if len(keys) == 1 else {"$or": [{k: True} for k in keys]}
        results = self.client.get_where(where)
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        # .get() carries no similarity distance; score is informational only here.
        return [{"document": d, "metadata": m, "score": 0.0} for d, m in zip(docs, metas, strict=False)]

    def _cap_recent(self, candidates: list[dict], limit: int) -> list[dict]:
        if len(candidates) <= limit:
            return candidates
        ranked = sorted(
            candidates,
            key=lambda c: self._parse_published_at(c["metadata"].get("published_at")) or datetime.min,
            reverse=True,
        )
        return ranked[:limit]

    @staticmethod
    def _parse_published_at(published_at_str: str | None) -> datetime | None:
        if not published_at_str:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(published_at_str, fmt)
            except ValueError:
                continue
        logger.debug(f"Failed to parse date {published_at_str}")
        return None

    @classmethod
    def _recency_factor(cls, published_at_str: str | None) -> float:
        """Multiplier in [(1 - weight), 1.0]: 1.0 for brand-new, decaying with age."""
        dt = cls._parse_published_at(published_at_str)
        if dt is None:
            return 1.0 - _RECENCY_WEIGHT
        age_days = max((datetime.now(UTC).replace(tzinfo=None) - dt).days, 0)
        decay = math.exp(-age_days / _RECENCY_TAU_DAYS)
        return (1.0 - _RECENCY_WEIGHT) + _RECENCY_WEIGHT * decay

    def _execute_query(self, query_text: str, n_results: int, filters: dict | None, contains_text: str | None) -> dict:
        return self.client.query(
            query_texts=[query_text],
            n_results=n_results,
            where=filters if filters else None,
            where_document={"$contains": contains_text} if contains_text else None,
        )

    @staticmethod
    def _extract_ticker(query_text: str) -> list[str] | None:
        result = re.findall(r"\(([^)]+)\)", query_text)
        if result:
            return result
        return None

    @staticmethod
    def _build_candidates(results: dict) -> list[dict]:
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        scores = results["distances"][0]
        return [
            {"document": doc, "metadata": meta, "score": score}
            for doc, meta, score in zip(docs, metas, scores, strict=False)
        ]

    @classmethod
    def _filter_by_date(cls, candidates: list[Candidate], months: int = 6) -> list[Candidate]:
        cutoff_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30 * months)
        filtered = []
        for c in candidates:
            published_at_dt = cls._parse_published_at(c["metadata"].get("published_at"))
            if published_at_dt is not None and published_at_dt >= cutoff_date:
                filtered.append(c)
        return filtered

    def _rerank_candidates(
        self, query_text: str, candidates: list[dict], top_n: int, threshold: float, min_floor: float = 0.1
    ) -> list[dict]:
        passages = [c["document"] for c in candidates]
        # Score ALL candidates (the cross-encoder already scores every passage;
        # asking for all just keeps them) so recency can influence which top_n win.
        reranked = self.reranker.rerank(query_text, passages, top_k=len(passages))

        def _to_result(passage: str, rerank_score: float) -> dict:
            orig = next(c for c in candidates if c["document"] == passage)
            recency = self._recency_factor(orig["metadata"].get("published_at"))
            return {
                "document": passage,
                "metadata": orig["metadata"],
                "retriever_score": orig["score"],
                "reranker_score": rerank_score,
                "recency_factor": recency,
                "final_score": rerank_score * recency,
            }

        # Relevance gate stays on the raw reranker score; recency only re-weights
        # ordering and top_n selection among the relevant ones.
        kept = [_to_result(p, s) for p, s in reranked if s >= threshold]

        if not kept and reranked and reranked[0][1] >= min_floor:
            logger.info(
                f"No passage cleared threshold {threshold}; "
                f"keeping best at {reranked[0][1]:.3f} (>= floor {min_floor})"
            )
            kept.append(_to_result(*reranked[0]))
        elif not kept:
            best = f"{reranked[0][1]:.3f}" if reranked else "n/a"
            logger.info(f"No passage cleared threshold {threshold} or floor {min_floor}; best was {best}")

        kept.sort(key=lambda x: x["final_score"], reverse=True)
        return kept[:top_n]
