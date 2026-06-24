"""E3 citation accuracy -> Table 8.3 (row 1), and saves answer+context samples
for the optional manual fidelity labelling (E6, Table 8.3 rows 2-4).

Requires the MCP server running (python -m backend.mcp_server.server) and Ollama.

    python -m backend.eval.run_end_to_end --gold backend/eval/datasets/retrieval_gold.json
"""

import argparse
import asyncio
import json

from . import metrics
from .harness import DATASETS_DIR, RESULTS_DIR, load_json, make_querier, write_csv


def _context_urls(querier, item: dict) -> set[str]:
    """URL universe the agent could ground in: ALL articles tagged with the
    query's tickers (ticker-scoped retrieval draws from exactly this pool, so a
    cited URL that belongs to an in-scope article is grounded regardless of the
    specific top-k / rerank query the agent used)."""
    urls: set[str] = set()
    for cand in querier._get_by_tickers(item.get("tickers", [])):
        u = cand["metadata"].get("url")
        if u:
            urls.add(u.rstrip(".,);]>\"'"))
    return urls


async def _run(gold: list[dict]) -> list[dict]:
    from backend.mcp_server.agent import Agent

    agent = Agent()
    await agent.initialize_tools()  # connects to the MCP server
    querier = make_querier()

    rows = []
    samples = []
    for item in gold:
        q = item["query"]
        try:
            answer = await agent.ask(q, thread_id=f"eval-{abs(hash(q))}")
        except Exception as exc:  # noqa: BLE001
            print(f"  agent failed for {q!r}: {exc}")
            continue

        ctx_urls = _context_urls(querier, item)
        acc = metrics.citation_accuracy(answer, ctx_urls)
        cited = metrics.extract_urls(answer)
        rows.append(
            {
                "query": q,
                "n_cited": len(cited),
                "n_grounded": sum(1 for u in cited if u in ctx_urls),
                "citation_accuracy": None if acc is None else round(acc, 4),
            }
        )
        samples.append({"query": q, "answer": answer, "context_urls": sorted(ctx_urls)})

    await agent.close()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "e6_samples.jsonl").write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in samples), encoding="utf-8"
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="E3 citation accuracy + E6 samples")
    parser.add_argument("--gold", default=str(DATASETS_DIR / "retrieval_gold.json"))
    args = parser.parse_args()

    gold = load_json(args.gold)
    print(f"Running agent end-to-end on {len(gold)} queries (needs MCP server + Ollama)...")
    rows = asyncio.run(_run(gold))
    write_csv("e3_citations.csv", rows)

    accs = [r["citation_accuracy"] for r in rows if r["citation_accuracy"] is not None]
    print(f"\n=== E3 citation accuracy ({len(accs)} answers with citations) ===")
    print(f"  mean citation accuracy: {metrics.mean(accs):.4f}")
    print("Wrote e3_citations.csv and e6_samples.jsonl to eval/results/")


if __name__ == "__main__":
    main()
