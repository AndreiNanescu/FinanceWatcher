"""Aggregate eval/results/*.csv into Markdown tables for Chapter 8.

    python -m backend.eval.report
"""

import csv
import sys

from .harness import RESULTS_DIR

# Tables contain Romanian diacritics; avoid a cp1252 console crash on Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_OUT = RESULTS_DIR / "tables.md"


def _read(name: str) -> list[dict]:
    path = RESULTS_DIR / name
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def table_81() -> str:
    rows = [r for r in _read("e1_aggregate.csv") if r.get("scope") == "ALL"]
    if not rows:
        return "_E1 not run (no e1_aggregate.csv)._"
    body = [[r["config"], r["P@5"], r["R@5"], r["MRR"], r["nDCG@5"], r["MAP"]] for r in rows]
    return _md_table(["Configurație", "P@5", "R@5", "MRR", "nDCG@5", "MAP"], body)


def table_81_per_company() -> str:
    rows = [r for r in _read("e1_aggregate.csv") if r.get("scope") != "ALL"]
    if not rows:
        return ""
    body = [[r["config"], r["scope"], r["n"], r["nDCG@5"], r["MAP"]] for r in rows]
    return _md_table(["Configurație", "Companie", "n", "nDCG@5", "MAP"], body)


def table_82() -> str:
    rows = _read("e2_latency.csv")
    if not rows:
        return "_E2 not run (no e2_latency.csv)._"
    r = rows[0]
    order = ["embed", "fetch", "rerank", "recency", "total_retrieval", "planner", "synthesis", "total_agent"]
    body = [[k, r[k]] for k in order if k in r]
    return _md_table(["Etapă", "Latență medie (ms)"], body)


def table_83() -> str:
    e3 = _read("e3_citations.csv")
    accs = [float(r["citation_accuracy"]) for r in e3 if r.get("citation_accuracy") not in (None, "", "None")]
    cite = str(round(sum(accs) / len(accs), 4)) if accs else "[de completat]"
    body = [
        ["Acuratețea citărilor", cite],
        ["Fidelitate (E6, manual)", "[de completat]"],
        ["Rată de halucinație (E6, manual)", "[de completat]"],
        ["Relevanță 1-5 (E6, manual)", "[de completat]"],
    ]
    return _md_table(["Metrică", "Valoare"], body)


def table_e5_threshold() -> str:
    rows = _read("e5_threshold.csv")
    if not rows:
        return "_E5 threshold not run._"
    body = [[r["threshold"], r["precision"], r["recall"]] for r in rows]
    return _md_table(["Prag", "Precizie", "Recall"], body)


def table_e5_recency() -> str:
    rows = _read("e5_recency.csv")
    if not rows:
        return "_E5 recency not run._"
    body = [[r["recency_weight"], r["recency_tau_days"], r["nDCG@5"], r["MAP"]] for r in rows]
    return _md_table(["recency_weight", "recency_tau_days", "nDCG@5", "MAP"], body)


def main() -> None:
    sections = [
        "# FinanceWatcher — rezultate evaluare (auto-generat)\n",
        "## Tabelul 8.1 — Ablația regăsirii (E1)\n",
        table_81(),
        "\n\n### 8.1 defalcat pe companie\n",
        table_81_per_company(),
        "\n\n## Tabelul 8.2 — Latență per etapă (E2)\n",
        table_82(),
        "\n\n## Tabelul 8.3 — Calitatea răspunsului (E3 + E6)\n",
        table_83(),
        "\n\n## E5 — Sensibilitate la prag\n",
        table_e5_threshold(),
        "\n\n## E5 — Sensibilitate la prospețime (τ, weight)\n",
        table_e5_recency(),
        "\n",
    ]
    text = "\n".join(s for s in sections if s)
    _OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nWrote {_OUT}")


if __name__ == "__main__":
    main()
