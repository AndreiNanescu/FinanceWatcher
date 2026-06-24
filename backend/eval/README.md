# FinanceWatcher — Evaluation harness (thesis Chapter 8)

Implements experiments E1–E6 from `Implementare_Evaluare_FinanceWatcher.md`.
All backend changes are additive; production defaults are unchanged.

## Layout
- `metrics.py` — P@k, R@k, MRR, nDCG@k, MAP, citation accuracy (no sklearn needed).
- `harness.py` — shared client/Querier builders, dataset loading, CSV writing.
- `export_corpus.py` — dump the corpus for labelling (`corpus_dump.json`).
- `make_scaffold.py` — build a pooled (C1∪C2∪C3) `retrieval_gold` scaffold to label.
- `run_retrieval.py` — **E1** ablation (Table 8.1) + **E5** threshold/recency sweeps.
- `run_latency.py` — **E2** per-stage latency (Table 8.2); `--with-agent` adds planner/synthesis.
- `run_end_to_end.py` — **E3** citation accuracy (Table 8.3) + saves `e6_samples.jsonl` for **E6**.
- `run_planner.py` — **E4** planner ticker/routing accuracy.
- `report.py` — aggregates `results/*.csv` into `results/tables.md`.

## Configs
- **C1** = cosine bge-m3 baseline (`use_reranker=False`).
- **C2** = cross-encoder rerank, no recency (`recency_weight=0`).
- **C3** = rerank + recency (production, `recency_weight=0.3`).

## How to run (from the repo root)
```bash
# 1. export + label gold (one-time, manual)
python -m backend.eval.export_corpus
python -m backend.eval.make_scaffold          # -> datasets/retrieval_gold.scaffold.json
#   label the `relevant` grades 0-3 (read `_pool` titles) and save as
#   datasets/retrieval_gold.json ; verify datasets/planner_gold.json

# 2. experiments
python -m backend.eval.run_retrieval   --gold backend/eval/datasets/retrieval_gold.json   # E1 + E5
python -m backend.eval.run_latency     --gold backend/eval/datasets/retrieval_gold.json   # E2 (add --with-agent)
python -m backend.eval.run_end_to_end  --gold backend/eval/datasets/retrieval_gold.json   # E3 (+ E6 samples)
python -m backend.eval.run_planner     --gold backend/eval/datasets/planner_gold.json     # E4

# 3. aggregate
python -m backend.eval.report                 # -> results/tables.md
```

Preconditions: E2 (`--with-agent`), E3, E4 need Ollama up with `qwen2.5:7b`;
E3 also needs the MCP server (`python -m backend.mcp_server.server`).
E1/E5 need neither — pure retrieval.

## Reproducibility
`datasets/corpus_snapshot/` + `SNAPSHOT.txt` freeze the 421-article corpus used
for the reported numbers. Restore it over `backend/data/db` and `backend/db` to
reproduce. The grades you assign in `retrieval_gold.json` are the only manual
input; everything else is computed.
