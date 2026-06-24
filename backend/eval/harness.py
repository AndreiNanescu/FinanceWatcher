"""Shared helpers for the evaluation runners: path bootstrap, dataset loading,
Querier construction, and writing result CSVs."""

import csv
import json
import os
import sys
from pathlib import Path

# Allow running as `python -m backend.eval.X` (repo root on path) or as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from backend.data.chroma.chroma_client import ChromaClient  # noqa: E402
from backend.data.chroma.query_service import Querier  # noqa: E402
from backend.rag import BGEReranker  # noqa: E402

_EVAL_DIR = Path(__file__).resolve().parent
DATASETS_DIR = _EVAL_DIR / "datasets"
RESULTS_DIR = _EVAL_DIR / "results"

# Build the heavy singletons once and reuse across configs/queries.
_CLIENT: ChromaClient | None = None
_RERANKER: BGEReranker | None = None


def get_clients() -> tuple[ChromaClient, BGEReranker]:
    global _CLIENT, _RERANKER
    if _CLIENT is None:
        _CLIENT = ChromaClient()
    if _RERANKER is None:
        _RERANKER = BGEReranker()
    return _CLIENT, _RERANKER


def make_querier(
    use_reranker: bool = True,
    recency_weight: float = 0.3,
    recency_tau_days: float = 30.0,
) -> Querier:
    client, reranker = get_clients()
    return Querier(
        client,
        reranker,
        recency_weight=recency_weight,
        recency_tau_days=recency_tau_days,
        use_reranker=use_reranker,
    )


def load_json(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ranked_ids(
    querier: Querier, item: dict, top_n: int = 100, threshold: float = 0.0, min_floor: float = 0.0
) -> list[str]:
    """Return the full ranked list of article ids for a gold query.

    threshold/min_floor default to 0 so retrieval-quality metrics see the system's
    ranking rather than its display cutoff (which E5 studies separately).
    """
    scoring_query = item.get("rerank_query") or item["query"]
    res = querier.search(
        scoring_query,
        tickers=item["tickers"],
        rerank_query=scoring_query,
        top_n_rerank=top_n,
        threshold=threshold,
        min_floor=min_floor,
    )
    return [r["id"] for r in res]


def returned_set(querier: Querier, item: dict, threshold: float, top_n: int = 100) -> list[str]:
    """Ids the system would actually return at a given threshold (for E5)."""
    scoring_query = item.get("rerank_query") or item["query"]
    res = querier.search(
        scoring_query,
        tickers=item["tickers"],
        rerank_query=scoring_query,
        top_n_rerank=top_n,
        threshold=threshold,
        min_floor=0.0,
    )
    return [r["id"] for r in res]


def write_csv(name: str, rows: list[dict]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path
