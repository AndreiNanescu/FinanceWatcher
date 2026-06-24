"""Evaluation harness for FinanceWatcher (thesis Chapter 8).

Run the experiments from the repository root, e.g.:

    python -m backend.eval.export_corpus
    python -m backend.eval.run_retrieval  --gold backend/eval/datasets/retrieval_gold.json
    python -m backend.eval.run_latency    --gold backend/eval/datasets/retrieval_gold.json
    python -m backend.eval.run_end_to_end --gold backend/eval/datasets/retrieval_gold.json
    python -m backend.eval.run_planner    --gold backend/eval/datasets/planner_gold.json
    python -m backend.eval.report
"""
