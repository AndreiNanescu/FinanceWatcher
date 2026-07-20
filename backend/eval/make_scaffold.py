"""Generate a retrieval_gold.json scaffold for manual labelling.

For each query it POOLS the top-k from C1 (cosine), C2 (rerank) and C3
(rerank+recency), unions the article ids, and writes them with grade 0. You then
edit the grades to 0-3 (0 irrelevant, 1 marginal, 2 relevant, 3 highly relevant)
by reading the `_pool` titles. This pooled-judgement approach keeps the C1/C2/C3
comparison fair (every system's results are labelled).

    python -m backend.eval.make_scaffold            # writes retrieval_gold.scaffold.json
    python -m backend.eval.make_scaffold --out backend/eval/datasets/retrieval_gold.json
"""

import argparse
import json
from pathlib import Path
from typing import cast

from .harness import DATASETS_DIR, make_querier

# query, tickers, rerank_query, type. Covers general / topic-focused / price.
QUERIES = [
    ("How is Nvidia doing?", ["NVDA"], "Nvidia (NVDA)", "general"),
    ("What's happening with Microsoft?", ["MSFT"], "Microsoft (MSFT)", "general"),
    ("How is Apple doing?", ["AAPL"], "Apple (AAPL)", "general"),
    ("How is Alphabet (Google) doing?", ["GOOGL"], "Google (GOOGL)", "general"),
    ("What's happening with Tesla?", ["TSLA"], "Tesla (TSLA)", "general"),
    ("How is JPMorgan doing?", ["JPM"], "JPMorgan (JPM)", "general"),
    ("How is Meta doing?", ["META"], "Meta (META)", "general"),
    ("How is Broadcom doing?", ["AVGO"], "Broadcom (AVGO)", "general"),
    ("Nvidia AI and data-center demand", ["NVDA"], "Nvidia (NVDA) AI data center demand", "topic"),
    ("Nvidia earnings results", ["NVDA"], "Nvidia (NVDA) earnings", "topic"),
    ("Apple iPhone pricing", ["AAPL"], "Apple (AAPL) iPhone pricing", "topic"),
    ("Apple AI strategy and Siri", ["AAPL"], "Apple (AAPL) AI strategy Siri", "topic"),
    ("Microsoft OpenAI and cloud", ["MSFT"], "Microsoft (MSFT) OpenAI cloud", "topic"),
    ("Microsoft cash flow and valuation", ["MSFT"], "Microsoft (MSFT) cash flow valuation", "topic"),
    ("Alphabet AI strategy", ["GOOGL"], "Google (GOOGL) AI strategy", "topic"),
    ("Tesla deliveries and EV demand", ["TSLA"], "Tesla (TSLA) deliveries EV demand", "topic"),
    ("Meta AI spending", ["META"], "Meta (META) AI spending", "topic"),
    ("Nvidia memory supply concerns", ["NVDA"], "Nvidia (NVDA) memory supply", "topic"),
    ("Why is Nvidia stock down?", ["NVDA"], "Nvidia (NVDA) stock decline", "price"),
    ("Why is Microsoft stock under pressure?", ["MSFT"], "Microsoft (MSFT) stock decline", "price"),
    ("Apple stock outlook and headwinds", ["AAPL"], "Apple (AAPL) stock outlook headwinds", "price"),
    ("Is Nvidia overvalued?", ["NVDA"], "Nvidia (NVDA) valuation overvalued", "price"),
    ("Alphabet stock falling vs the market", ["GOOGL"], "Google (GOOGL) stock falling market", "price"),
    ("Tesla stock outlook", ["TSLA"], "Tesla (TSLA) stock outlook", "price"),
    ("JPMorgan results and outlook", ["JPM"], "JPMorgan (JPM) results outlook", "topic"),
    ("Microsoft Copilot and AI products", ["MSFT"], "Microsoft (MSFT) Copilot AI products", "topic"),
    ("Apple memory crisis impact", ["AAPL"], "Apple (AAPL) memory crisis", "topic"),
    ("Nvidia top stock picks and analyst views", ["NVDA"], "Nvidia (NVDA) analyst top pick", "topic"),
    ("Broadcom AI and growth", ["AVGO"], "Broadcom (AVGO) AI growth", "topic"),
    ("How is Tesla faring after recent news?", ["TSLA"], "Tesla (TSLA)", "general"),
]

POOL_K = 10


def _title(doc: str) -> str:
    return (doc or "").splitlines()[0].removeprefix("Title:").strip()


def _summary(doc: str) -> str:
    """The stored summary == the text after 'Description:' (the retrieval unit)."""
    parts = (doc or "").split("Description:", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DATASETS_DIR / "retrieval_gold.scaffold.json"))
    parser.add_argument("--pool-k", type=int, default=POOL_K)
    args = parser.parse_args()

    c1 = make_querier(use_reranker=False, recency_weight=0.0)
    c2 = make_querier(use_reranker=True, recency_weight=0.0)
    c3 = make_querier(use_reranker=True, recency_weight=0.3)

    items = []
    for query, tickers, rerank_query, qtype in QUERIES:
        pool: dict[str, dict] = {}
        for q in (c1, c2, c3):
            res = q.search(rerank_query, tickers=tickers, rerank_query=rerank_query,
                           top_n_rerank=args.pool_k, threshold=0.0, min_floor=0.0)
            for r in cast(list[dict], res):
                aid = r["id"]
                if aid and aid not in pool:
                    pool[aid] = {
                        "id": aid,
                        "title": _title(r["document"]),
                        # Summary is what to label against — it is the indexed unit.
                        "summary": _summary(r["document"]),
                        "url": r["metadata"].get("url", ""),
                    }
        items.append(
            {
                "query": query,
                "type": qtype,
                "tickers": tickers,
                "rerank_query": rerank_query,
                "relevant": {aid: 0 for aid in pool},
                "_pool": list(pool.values()),
            }
        )
        print(f"  pooled {len(pool):2d} candidates for {query!r}")

    Path(args.out).write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote scaffold with {len(items)} queries -> {args.out}")
    print("Label each `relevant` grade 0-3 by reading each `_pool` entry's TITLE + SUMMARY")
    print("(the summary is the indexed unit), then save as retrieval_gold.json.")


if __name__ == "__main__":
    main()
