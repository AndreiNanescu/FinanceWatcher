"""E2 latency per stage -> Table 8.2.

Retrieval timing (default) needs no LLM. Agent timing (planner + synthesis)
needs Ollama running with the production model; enable it with --with-agent.

    python -m backend.eval.run_latency --gold backend/eval/datasets/retrieval_gold.json
    python -m backend.eval.run_latency --gold ... --with-agent
"""

import argparse
import asyncio
import time

from . import metrics
from .harness import DATASETS_DIR, load_json, make_querier, write_csv

_STAGES = ("embed", "fetch", "rerank", "recency")


def run_retrieval_latency(gold: list[dict], warmup: bool = True) -> dict:
    """Mean per-stage retrieval latency (ms) for the production config (C3)."""
    querier = make_querier(use_reranker=True, recency_weight=0.3)

    if warmup and gold:  # first call pays one-off model warmup; don't measure it
        item = gold[0]
        querier.search(
            item.get("rerank_query") or item["query"],
            tickers=item["tickers"],
            rerank_query=item.get("rerank_query"),
            collect_timings=True,
        )

    acc = {s: [] for s in _STAGES}
    totals = []
    for item in gold:
        sq = item.get("rerank_query") or item["query"]
        t0 = time.perf_counter()
        _, timings = querier.search(sq, tickers=item["tickers"], rerank_query=sq, collect_timings=True)
        total = time.perf_counter() - t0
        for s in _STAGES:
            acc[s].append(timings.get(s, 0.0))
        totals.append(total)

    return {
        **{s: round(metrics.mean(acc[s]) * 1000, 2) for s in _STAGES},
        "total_retrieval": round(metrics.mean(totals) * 1000, 2),
    }


async def run_agent_latency(gold: list[dict]) -> dict:
    """Mean planner + synthesis latency (ms). Requires Ollama up with the model."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    from backend.config import config
    from backend.agents.graph import Plan
    from backend.agents.prompts import build_planner_system_prompt, SYNTHESIS_SYSTEM_PROMPT

    llm = ChatOllama(model=config.models.planner, num_predict=4096, temperature=0.0)
    planner_llm = llm.with_structured_output(Plan)

    planner_times, synth_times = [], []
    sample_context = (
        "Company: Nvidia (NVDA)\nNews for Nvidia (NVDA):\nTitle: Nvidia AI demand strong\n"
        "Price summary for Nvidia (NVDA) over the last 30 days: closed at 208.65 ...\n"
    )
    for item in gold:
        q = item["query"]
        t0 = time.perf_counter()
        try:
            await planner_llm.ainvoke([SystemMessage(content=build_planner_system_prompt()), HumanMessage(content=q)])
        except Exception as exc:  # noqa: BLE001
            print(f"  planner failed for {q!r}: {exc}")
            continue
        planner_times.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        prompt = f"User question:\n{q}\n\nRetrieved data:\n{sample_context}\n\nWrite the analysis:"
        await llm.ainvoke([SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT), HumanMessage(content=prompt)])
        synth_times.append(time.perf_counter() - t0)

    return {
        "planner": round(metrics.mean(planner_times) * 1000, 2),
        "synthesis": round(metrics.mean(synth_times) * 1000, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="E2 latency per stage")
    parser.add_argument("--gold", default=str(DATASETS_DIR / "retrieval_gold.json"))
    parser.add_argument("--with-agent", action="store_true", help="Also time planner+synthesis (needs Ollama)")
    args = parser.parse_args()

    gold = load_json(args.gold)
    print(f"Timing retrieval over {len(gold)} queries...")
    ret = run_retrieval_latency(gold)
    row = {"stage_group": "retrieval", **ret}

    if args.with_agent:
        print("Timing agent (planner + synthesis) over queries (needs Ollama)...")
        agent = asyncio.run(run_agent_latency(gold))
        row.update(agent)
        row["total_agent"] = round(row.get("planner", 0) + row.get("synthesis", 0), 2)

    write_csv("e2_latency.csv", [row])
    print("\n=== E2 latency (ms) ===")
    for k, v in row.items():
        print(f"  {k:18} {v}")
    print("\nWrote e2_latency.csv to eval/results/")


if __name__ == "__main__":
    main()
