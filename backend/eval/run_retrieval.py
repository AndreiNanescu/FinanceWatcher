"""E1 (retrieval ablation -> Table 8.1) and E5 (threshold / recency sensitivity).

    python -m backend.eval.run_retrieval --gold backend/eval/datasets/retrieval_gold.json
"""

import argparse

from . import metrics
from .harness import DATASETS_DIR, load_json, make_querier, ranked_ids, returned_set, write_csv

# C1 = cosine baseline, C2 = reranker w/o recency, C3 = reranker + recency (prod).
CONFIGS = {
    "C1_cosine": dict(use_reranker=False, recency_weight=0.0),
    "C2_rerank": dict(use_reranker=True, recency_weight=0.0),
    "C3_rerank_recency": dict(use_reranker=True, recency_weight=0.3),
}


def _metrics_for(ranked: list[str], relevance: dict[str, int]) -> dict:
    return {
        "P@5": metrics.precision_at_k(ranked, relevance, 5),
        "R@5": metrics.recall_at_k(ranked, relevance, 5),
        "MRR": metrics.reciprocal_rank(ranked, relevance),
        "nDCG@5": metrics.ndcg_at_k(ranked, relevance, 5),
        "AP": metrics.average_precision(ranked, relevance),
    }


def run_e1(gold: list[dict]) -> list[dict]:
    """Per-config, per-query metrics + macro averages (overall and per company)."""
    rows = []
    for cfg_name, cfg in CONFIGS.items():
        querier = make_querier(**cfg)
        for item in gold:
            relevance = {k: int(v) for k, v in item.get("relevant", {}).items()}
            if not metrics._relevant_set(relevance):
                continue  # skip unlabelled queries
            ranked = ranked_ids(querier, item)
            m = _metrics_for(ranked, relevance)
            rows.append(
                {
                    "config": cfg_name,
                    "query": item["query"],
                    "ticker": ",".join(item.get("tickers", [])),
                    **{k: round(v, 4) for k, v in m.items()},
                }
            )
    return rows


def aggregate(rows: list[dict]) -> list[dict]:
    """Macro-average the per-query rows by config (and config x ticker)."""
    metric_keys = ["P@5", "R@5", "MRR", "nDCG@5", "AP"]
    out = []

    def avg(subset: list[dict], label_key: str, label_val: str) -> dict:
        return {
            "config": subset[0]["config"],
            "scope": label_val,
            "n": len(subset),
            **{k: round(metrics.mean([r[k] for r in subset]), 4) for k in metric_keys},
        }

    by_cfg: dict[str, list[dict]] = {}
    for r in rows:
        by_cfg.setdefault(r["config"], []).append(r)
    for subset in by_cfg.values():
        out.append(avg(subset, "scope", "ALL"))
        by_ticker: dict[str, list[dict]] = {}
        for r in subset:
            by_ticker.setdefault(r["ticker"], []).append(r)
        for tk, ts in sorted(by_ticker.items()):
            out.append(avg(ts, "scope", tk))
    # MAP == mean of AP across queries; expose it explicitly per config/scope.
    for row in out:
        row["MAP"] = row.pop("AP")
    return out


def run_e5_threshold(gold: list[dict]) -> list[dict]:
    """C3 set-precision/recall as the display threshold varies (P-R curve)."""
    querier = make_querier(use_reranker=True, recency_weight=0.3)
    rows = []
    for thr in (0.1, 0.2, 0.3, 0.4, 0.5):
        precs, recs = [], []
        for item in gold:
            relevance = {k: int(v) for k, v in item.get("relevant", {}).items()}
            rel = metrics._relevant_set(relevance)
            if not rel:
                continue
            returned = returned_set(querier, item, threshold=thr)
            if returned:
                precs.append(sum(1 for i in returned if i in rel) / len(returned))
            recs.append(sum(1 for i in rel if i in returned) / len(rel))
        rows.append(
            {
                "threshold": thr,
                "precision": round(metrics.mean(precs), 4),
                "recall": round(metrics.mean(recs), 4),
                "n_queries": len(precs),
            }
        )
    return rows


def run_e5_recency(gold: list[dict]) -> list[dict]:
    """nDCG@5 / MAP grid over recency_weight x recency_tau_days."""
    rows = []
    for weight in (0.0, 0.3, 0.5):
        for tau in (7.0, 15.0, 30.0, 60.0):
            querier = make_querier(use_reranker=True, recency_weight=weight, recency_tau_days=tau)
            ndcgs, aps = [], []
            for item in gold:
                relevance = {k: int(v) for k, v in item.get("relevant", {}).items()}
                if not metrics._relevant_set(relevance):
                    continue
                ranked = ranked_ids(querier, item)
                ndcgs.append(metrics.ndcg_at_k(ranked, relevance, 5))
                aps.append(metrics.average_precision(ranked, relevance))
            rows.append(
                {
                    "recency_weight": weight,
                    "recency_tau_days": tau,
                    "nDCG@5": round(metrics.mean(ndcgs), 4),
                    "MAP": round(metrics.mean(aps), 4),
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="E1 retrieval ablation + E5 sensitivity")
    parser.add_argument("--gold", default=str(DATASETS_DIR / "retrieval_gold.json"))
    args = parser.parse_args()

    gold = load_json(args.gold)
    labelled = [g for g in gold if metrics._relevant_set({k: int(v) for k, v in g.get("relevant", {}).items()})]
    print(f"Loaded {len(gold)} queries ({len(labelled)} labelled).")
    if not labelled:
        print("No labelled queries (every 'relevant' map is empty). Label retrieval_gold.json first.")
        return

    per_query = run_e1(gold)
    write_csv("e1_per_query.csv", per_query)
    agg = aggregate(per_query)
    write_csv("e1_aggregate.csv", agg)
    write_csv("e5_threshold.csv", run_e5_threshold(gold))
    write_csv("e5_recency.csv", run_e5_recency(gold))

    print("Wrote e1_per_query.csv, e1_aggregate.csv, e5_threshold.csv, e5_recency.csv to eval/results/")
    print("\n=== E1 aggregate (ALL scope) ===")
    for r in agg:
        if r["scope"] == "ALL":
            print(
                f"  {r['config']:20} P@5={r['P@5']} R@5={r['R@5']} "
                f"MRR={r['MRR']} nDCG@5={r['nDCG@5']} MAP={r['MAP']}"
            )


if __name__ == "__main__":
    main()
