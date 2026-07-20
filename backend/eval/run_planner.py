"""E4 planner accuracy -> discussion 8.3. Needs Ollama running with the model.

    python -m backend.eval.run_planner --gold backend/eval/datasets/planner_gold.json
"""

import argparse
import asyncio
from typing import cast

from .harness import DATASETS_DIR, load_json, write_csv


async def _run(gold: list[dict]) -> list[dict]:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    from backend.agents.graph import Plan
    from backend.agents.prompts import build_planner_system_prompt
    from backend.config import config

    llm = ChatOllama(model=config.models.planner, num_predict=4096, temperature=0.0)
    planner_llm = llm.with_structured_output(Plan)

    rows = []
    for item in gold:
        q = item["question"]
        try:
            plan = cast(Plan, await planner_llm.ainvoke(
                [SystemMessage(content=build_planner_system_prompt()), HumanMessage(content=q)]
            ))
        except Exception as exc:  # noqa: BLE001
            print(f"  planner failed for {q!r}: {exc}")
            continue

        pred_tickers = {c.ticker.upper() for c in plan.companies}
        exp_tickers = {t.upper() for t in item.get("expected_tickers", [])}
        ticker_ok = pred_tickers == exp_tickers

        # Routing: compare the matching company's flags to the expected ones.
        exp_news = item.get("expected_needs_news")
        exp_price = item.get("expected_needs_price")
        matched = next((c for c in plan.companies if c.ticker.upper() in exp_tickers), None)
        if matched is None:
            routing_ok = False
            pred_news = pred_price = None
        else:
            pred_news, pred_price = matched.needs_news, matched.needs_price
            routing_ok = (exp_news is None or pred_news == exp_news) and (
                exp_price is None or pred_price == exp_price
            )

        rows.append(
            {
                "question": q,
                "expected_tickers": ",".join(sorted(exp_tickers)),
                "predicted_tickers": ",".join(sorted(pred_tickers)),
                "ticker_correct": ticker_ok,
                "expected_news": exp_news,
                "predicted_news": pred_news,
                "expected_price": exp_price,
                "predicted_price": pred_price,
                "routing_correct": routing_ok,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="E4 planner accuracy")
    parser.add_argument("--gold", default=str(DATASETS_DIR / "planner_gold.json"))
    args = parser.parse_args()

    gold = load_json(args.gold)
    print(f"Evaluating planner on {len(gold)} questions (needs Ollama)...")
    rows = asyncio.run(_run(gold))
    write_csv("e4_planner.csv", rows)

    n = len(rows)
    if n:
        ticker_acc = sum(1 for r in rows if r["ticker_correct"]) / n
        routing_acc = sum(1 for r in rows if r["routing_correct"]) / n
        print(f"\n=== E4 planner ({n} questions) ===")
        print(f"  ticker correct : {ticker_acc:.1%}")
        print(f"  routing correct: {routing_acc:.1%}")
    print("Wrote e4_planner.csv to eval/results/")


if __name__ == "__main__":
    main()
