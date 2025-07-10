from datetime import datetime, timedelta

from typing import List, Dict, Optional

from .chroma_client import ChromaClient
from backend.rag import BGEReranker, EntityAndTickerExtractor
from backend.utils import logger, Candidate


class Querier:
    def __init__(self, chroma_client: ChromaClient, reranker: BGEReranker, extractor: EntityAndTickerExtractor):
        if chroma_client is None:
            raise ValueError(f"chroma_client parameter cannot be None in Querier")

        self.reranker = reranker
        self.extractor = extractor
        self.client = chroma_client
        logger.info('Querier initialized')

    def search(self, query_text: str, n_results: int = 50, contains_text: Optional[str] = None, top_n_rerank: int = 5,
              threshold: float = 0.75) -> List[Dict]:

        #filters = self._build_filters(query_text)

        raw_results = self._execute_query(query_text=query_text, n_results=n_results, filters=None,
                                          contains_text=contains_text)
        candidates = self._build_candidates(raw_results)

        if not candidates:
            return []

        recent_candidates = self._filter_by_date(candidates, months=6)
        if not recent_candidates:
            return []

        final_results = self._rerank_candidates(query_text, recent_candidates, top_n_rerank, threshold)
        return final_results

    def _execute_query(self, query_text: str, n_results: int,
                       filters: Optional[dict], contains_text: Optional[str]) -> Dict:
        return self.client.query(
            query_texts=[query_text],
            n_results=n_results,
            where=filters if filters else None,
            where_document={"$contains": contains_text} if contains_text else None
        )

    def _build_filters(self, query_text: str) -> Optional[Dict]:
        companies, tickers = self.extractor.extract_all(query_text)

        if not companies and not tickers:
            return None

        conditions = []
        if companies:
            conditions.append({"entity_names": {"$in": companies}})
        if tickers:
            conditions.append({"entity_symbols": {"$in": tickers}})

        if len(conditions) == 1:
            return conditions[0]

        if len(conditions) > 1:
            return {"$or": conditions}

    @staticmethod
    def _build_candidates(results: Dict) -> List[Dict]:
        docs = results['documents'][0]
        metas = results['metadatas'][0]
        scores = results['distances'][0]
        return [
            {"document": doc, "metadata": meta, "score": score}
            for doc, meta, score in zip(docs, metas, scores)
        ]

    @staticmethod
    def _filter_by_date(candidates: List[Candidate], months: int = 6) -> List[Candidate]:
        cutoff_date = datetime.utcnow() - timedelta(days=30 * months)
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

    def _rerank_candidates(self, query_text: str, candidates: List[Dict], top_n: int, threshold: float) -> List[Dict]:
        passages = [c["document"] for c in candidates]
        reranked = self.reranker.rerank(query_text, passages, top_k=top_n)

        top_candidates = []
        for passage, rerank_score in reranked:
            if rerank_score >= threshold:
                orig = next(c for c in candidates if c["document"] == passage)
                top_candidates.append({
                    "document": passage,
                    "metadata": orig["metadata"],
                    "retriever_score": orig["score"],
                    "reranker_score": rerank_score,
                })

        if not top_candidates and reranked:
            passage, rerank_score = reranked[0]
            orig = next(c for c in candidates if c["document"] == passage)
            top_candidates.append({
                "document": passage,
                "metadata": orig["metadata"],
                "retriever_score": orig["score"],
                "reranker_score": rerank_score,
            })

        top_candidates.sort(key=lambda x: x["reranker_score"], reverse=True)
        return top_candidates