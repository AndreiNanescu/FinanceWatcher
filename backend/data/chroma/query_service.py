import math
import re
import time
from datetime import UTC, datetime, timedelta

from backend.config import config
from backend.rag import BGEReranker
from backend.utils import Candidate, logger, symbol_flag_key

from .chroma_client import ChromaClient

# Recency weighting: final_score = reranker_score * ((1 - weight) + weight * decay)
# where decay = exp(-age_days / tau). So recency adjusts a relevant article's
# score by at most `weight`, enough to favour fresher news without letting a
# barely-relevant new article beat a clearly-relevant slightly-older one.

# Cap how many candidates we rerank, to bound CPU cost when a ticker has a lot
# of articles. We keep the most recent ones before reranking.



class Querier:
    def __init__(
        self,
        chroma_client: ChromaClient,
        reranker: BGEReranker,
        recency_weight: float = config.retrieval.recency_weight,
        recency_tau_days: float = config.retrieval.recency_tau_days,
        max_rerank_candidates: int = config.retrieval.max_rerank_candidates,
        use_reranker: bool = True,
    ):
        if chroma_client is None:
            raise ValueError("chroma_client parameter cannot be None in Querier")

        self.reranker = reranker
        self.client = chroma_client

        self.recency_weight = recency_weight
        self.recency_tau_days = recency_tau_days
        self.max_rerank_candidates = max_rerank_candidates
        self.use_reranker = use_reranker

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
        collect_timings: bool = False,
    ) -> list[dict] | tuple[list[dict], dict]:

        timings: dict[str, float] = {}
        rerank_query = rerank_query or query_text

        if tickers is None:
            tickers = self._extract_ticker(query_text)
        logger.info(f"Requested tickers {tickers}")

        # C1 (cosine baseline) needs the stored embeddings to score against.
        need_embeddings = not self.use_reranker

        t0 = time.perf_counter()
        if tickers:
            # Ticker-scoped retrieval: pull EVERY article tagged with the ticker
            # (DB-level metadata filter) so recall doesn't depend on the company
            # appearing in a global semantic top-k.
            candidates = self._get_by_tickers(tickers, with_embeddings=need_embeddings)
        else:
            raw_results = self._execute_query(
                query_text=query_text, n_results=n_results, filters=None, contains_text=contains_text
            )
            candidates = self._build_candidates(raw_results)
        timings["fetch"] = time.perf_counter() - t0

        if not candidates:
            return ([], timings) if collect_timings else []

        recent_candidates = self._filter_by_date(candidates, months=6)
        if not recent_candidates:
            return ([], timings) if collect_timings else []

        # Bound rerank cost: keep the most recent candidates if there are many.
        recent_candidates = self._cap_recent(recent_candidates, self.max_rerank_candidates)

        if self.use_reranker:
            final_results = self._rerank_candidates(
                rerank_query, recent_candidates, top_n_rerank, threshold, min_floor, timings
            )
        else:
            final_results = self._rank_by_cosine(rerank_query, recent_candidates, top_n_rerank, timings)

        return (final_results, timings) if collect_timings else final_results

    def _get_by_tickers(self, tickers: list[str], with_embeddings: bool = False) -> list[dict]:
        keys = [symbol_flag_key(t) for t in tickers if t and t.strip()]
        if not keys:
            return []
        where = {keys[0]: True} if len(keys) == 1 else {"$or": [{k: True} for k in keys]}

        if with_embeddings:
            results = self.client.get_where_with_embeddings(where)
        else:
            results = self.client.get_where(where)

        ids = results.get("ids") or []
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        embs = results.get("embeddings") if with_embeddings else None

        out = []
        for i in range(len(docs)):
            # .get() carries no similarity distance; score is informational only.
            cand = {
                "id": ids[i] if i < len(ids) else None,
                "document": docs[i],
                "metadata": metas[i],
                "score": 0.0,
            }
            if with_embeddings and embs is not None and i < len(embs):
                cand["embedding"] = embs[i]
            out.append(cand)
        return out

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

    def _recency_factor(self, published_at_str: str | None) -> float:
        """Multiplier in [(1 - weight), 1.0]: 1.0 for brand-new, decaying with age."""
        dt = self._parse_published_at(published_at_str)
        if dt is None:
            return 1.0 - self.recency_weight
        age_days = max((datetime.now(UTC).replace(tzinfo=None) - dt).days, 0)
        decay = math.exp(-age_days / self.recency_tau_days)
        return (1.0 - self.recency_weight) + self.recency_weight * decay

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
        ids = results.get("ids", [[]])[0]
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        scores = results["distances"][0]
        return [
            {"id": id_, "document": doc, "metadata": meta, "score": score}
            for id_, doc, meta, score in zip(ids, docs, metas, scores, strict=False)
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

    def _rank_by_cosine(
        self, query_text: str, candidates: list[dict], top_n: int, timings: dict | None = None
    ) -> list[dict]:
        """C1 baseline: order candidates by bge-m3 cosine similarity to the query.

        Embeddings stored in Chroma are L2-normalized, so cosine == dot product.
        No reranker, no recency — the pure dense-retrieval baseline.
        """
        t0 = time.perf_counter()
        q_emb = self.client.embedder.embed(query_text)[0]
        if timings is not None:
            timings["embed"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        scored = []
        for c in candidates:
            emb = c.get("embedding")
            if emb is not None:
                score = sum(a * b for a, b in zip(q_emb, emb, strict=False))
            else:
                # Fallback (e.g. no-ticker path without embeddings): use the
                # negated Chroma distance so smaller distance ranks higher.
                score = -float(c.get("score", 0.0))
            scored.append(
                {
                    "id": c.get("id"),
                    "document": c["document"],
                    "metadata": c["metadata"],
                    "retriever_score": score,
                    "reranker_score": None,
                    "recency_factor": 1.0,
                    "final_score": score,
                }
            )
        scored.sort(key=lambda x: x["final_score"], reverse=True)
        if timings is not None:
            timings["rerank"] = time.perf_counter() - t0
            timings["recency"] = 0.0
        return scored[:top_n]

    def _rerank_candidates(
        self,
        query_text: str,
        candidates: list[dict],
        top_n: int,
        threshold: float,
        min_floor: float = 0.1,
        timings: dict | None = None,
    ) -> list[dict]:
        passages = [c["document"] for c in candidates]
        # Score ALL candidates (the cross-encoder already scores every passage;
        # asking for all just keeps them) so recency can influence which top_n win.
        t0 = time.perf_counter()
        reranked = self.reranker.rerank(query_text, passages, top_k=len(passages))
        if timings is not None:
            timings["rerank"] = time.perf_counter() - t0

        t0 = time.perf_counter()

        def _to_result(passage: str, rerank_score: float) -> dict:
            orig = next(c for c in candidates if c["document"] == passage)
            recency = self._recency_factor(orig["metadata"].get("published_at"))
            return {
                "id": orig.get("id"),
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
        if timings is not None:
            timings["recency"] = time.perf_counter() - t0
        return kept[:top_n]
