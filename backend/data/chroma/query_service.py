import re
from datetime import UTC, datetime, timedelta

from backend.rag import BGEReranker
from backend.utils import Candidate, logger

from .chroma_client import ChromaClient


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
        raw_results = self._execute_query(
            query_text=query_text, n_results=n_results, filters=None, contains_text=contains_text
        )
        candidates = self._build_candidates(raw_results)

        if not candidates:
            return []

        if tickers:
            candidates = self._filter_by_tickers(candidates, tickers)
            if not candidates:
                return []

        recent_candidates = self._filter_by_date(candidates, months=6)
        if not recent_candidates:
            return []

        final_results = self._rerank_candidates(rerank_query, recent_candidates, top_n_rerank, threshold, min_floor)
        return final_results

    @staticmethod
    def _filter_by_tickers(candidates: list[dict], tickers: list[str]) -> list[dict]:
        wanted = {t.strip().upper() for t in tickers if t.strip()}
        filtered = []
        for c in candidates:
            symbols_str = c["metadata"].get("entity_symbols", "") or ""
            have = {s.strip().upper() for s in symbols_str.split(",") if s.strip()}
            if wanted & have:
                filtered.append(c)
        return filtered

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

    @staticmethod
    def _filter_by_date(candidates: list[Candidate], months: int = 6) -> list[Candidate]:
        cutoff_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30 * months)
        filtered = []

        for c in candidates:
            published_at_str = c["metadata"].get("published_at")
            if not published_at_str:
                continue
            try:
                published_at_dt = datetime.strptime(published_at_str, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                try:
                    published_at_dt = datetime.strptime(published_at_str, "%Y-%m-%dT%H:%M:%SZ")
                except Exception as e:
                    logger.debug(f"Failed to parse date {published_at_str}: {e}")
                    continue
            if published_at_dt >= cutoff_date:
                filtered.append(c)

        return filtered

    def _rerank_candidates(
        self, query_text: str, candidates: list[dict], top_n: int, threshold: float, min_floor: float = 0.1
    ) -> list[dict]:
        passages = [c["document"] for c in candidates]
        reranked = self.reranker.rerank(query_text, passages, top_k=top_n)

        def _to_result(passage: str, rerank_score: float) -> dict:
            orig = next(c for c in candidates if c["document"] == passage)
            return {
                "document": passage,
                "metadata": orig["metadata"],
                "retriever_score": orig["score"],
                "reranker_score": rerank_score,
            }

        top_candidates = [_to_result(p, s) for p, s in reranked if s >= threshold]

        if not top_candidates and reranked and reranked[0][1] >= min_floor:
            logger.info(
                f"No passage cleared threshold {threshold}; "
                f"keeping best at {reranked[0][1]:.3f} (>= floor {min_floor})"
            )
            top_candidates.append(_to_result(*reranked[0]))
        elif not top_candidates:
            best = f"{reranked[0][1]:.3f}" if reranked else "n/a"
            logger.info(f"No passage cleared threshold {threshold} or floor {min_floor}; best was {best}")

        top_candidates.sort(key=lambda x: x["reranker_score"], reverse=True)

        return top_candidates
