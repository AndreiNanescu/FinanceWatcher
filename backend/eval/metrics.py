"""Retrieval and citation metrics for the FinanceWatcher evaluation.

All functions are self-contained (no sklearn dependency required). nDCG follows
relation (8.4); MAP follows (8.5); citation accuracy follows (8.6).

Conventions
-----------
- `ranked_ids`: list of article ids in the order the system returned them.
- `relevance`: dict {article_id: graded_relevance} with grades in {0,1,2,3}.
  An article is "relevant" iff its grade >= 1.
"""

import math
import re

_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def _relevant_set(relevance: dict[str, int]) -> set[str]:
    return {aid for aid, grade in relevance.items() if grade >= 1}


def precision_at_k(ranked_ids: list[str], relevance: dict[str, int], k: int) -> float:
    if k <= 0:
        return 0.0
    rel = _relevant_set(relevance)
    topk = ranked_ids[:k]
    hits = sum(1 for aid in topk if aid in rel)
    return hits / k


def recall_at_k(ranked_ids: list[str], relevance: dict[str, int], k: int) -> float:
    rel = _relevant_set(relevance)
    if not rel:
        return 0.0
    topk = set(ranked_ids[:k])
    hits = sum(1 for aid in rel if aid in topk)
    return hits / len(rel)


def reciprocal_rank(ranked_ids: list[str], relevance: dict[str, int]) -> float:
    rel = _relevant_set(relevance)
    for i, aid in enumerate(ranked_ids, start=1):
        if aid in rel:
            return 1.0 / i
    return 0.0


def dcg_at_k(ranked_ids: list[str], relevance: dict[str, int], k: int) -> float:
    dcg = 0.0
    for i, aid in enumerate(ranked_ids[:k], start=1):
        grade = relevance.get(aid, 0)
        if grade:
            dcg += (2**grade - 1) / math.log2(i + 1)
    return dcg


def ndcg_at_k(ranked_ids: list[str], relevance: dict[str, int], k: int) -> float:
    dcg = dcg_at_k(ranked_ids, relevance, k)
    # Ideal DCG: sort the graded relevances descending.
    ideal_ids = sorted(relevance, key=lambda a: relevance[a], reverse=True)
    idcg = dcg_at_k(ideal_ids, relevance, k)
    return dcg / idcg if idcg > 0 else 0.0


def average_precision(ranked_ids: list[str], relevance: dict[str, int]) -> float:
    rel = _relevant_set(relevance)
    if not rel:
        return 0.0
    hits = 0
    score = 0.0
    for i, aid in enumerate(ranked_ids, start=1):
        if aid in rel:
            hits += 1
            score += hits / i
    return score / len(rel)


def extract_urls(text: str) -> set[str]:
    """Extract URLs from free text, stripping common trailing punctuation."""
    urls = set()
    for raw in _URL_RE.findall(text or ""):
        urls.add(raw.rstrip(".,);]>\"'"))
    return urls


def citation_accuracy(answer: str, context_urls: set[str]) -> float | None:
    """Relation (8.6): fraction of URLs cited in the answer that actually appear
    in the retrieved context. Returns None when the answer cites no URL (so it
    can be excluded from the average instead of counted as 0 or 1).
    """
    cited = extract_urls(answer)
    if not cited:
        return None
    grounded = sum(1 for u in cited if u in context_urls)
    return grounded / len(cited)


def mean(values: list[float]) -> float:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0
