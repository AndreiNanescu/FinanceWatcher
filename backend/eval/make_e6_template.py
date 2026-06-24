"""Build the E6 manual-labelling template from the saved end-to-end answers.

Produces, in eval/results/:
  - e6_labeling.md   : readable — each answer + its context URLs (what to score against)
  - e6_labeling.csv  : score sheet — fill claims_total, claims_supported, relevance_1_5

Protocol (per answer):
  - claims_total      = number of distinct factual claims the answer makes
  - claims_supported  = how many of those are supported by the retrieved context
  - relevance_1_5     = overall usefulness/relevance of the answer to the question (1-5)
Fidelity = claims_supported / claims_total ; hallucination rate = 1 - fidelity.
`report.py` reads the filled CSV and fills Table 8.3 rows 2-4 automatically.

    python -m backend.eval.make_e6_template
"""

import csv
import json

from .harness import RESULTS_DIR

_SAMPLES = RESULTS_DIR / "e6_samples.jsonl"
_MD = RESULTS_DIR / "e6_labeling.md"
_CSV = RESULTS_DIR / "e6_labeling.csv"


def main() -> None:
    if not _SAMPLES.exists():
        print(f"{_SAMPLES} not found — run `python -m backend.eval.run_end_to_end` first.")
        return

    samples = [json.loads(line) for line in _SAMPLES.read_text(encoding="utf-8").splitlines() if line.strip()]

    md = [
        "# E6 manual fidelity labelling\n",
        "For each answer score in `e6_labeling.csv`:\n",
        "- **claims_total** = number of factual claims the answer makes\n",
        "- **claims_supported** = how many are backed by the Context URLs below\n",
        "- **relevance_1_5** = overall relevance/usefulness (1-5)\n",
        "\n---\n",
    ]
    for i, s in enumerate(samples):
        md.append(f"\n## {i}. {s['query']}\n")
        md.append(f"\n{s['answer']}\n")
        md.append("\n**Context URLs:**\n")
        for u in s.get("context_urls", []):
            md.append(f"- {u}\n")
        md.append("\n---\n")
    _MD.write_text("".join(md), encoding="utf-8")

    with _CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["idx", "query", "claims_total", "claims_supported", "relevance_1_5", "notes"])
        for i, s in enumerate(samples):
            w.writerow([i, s["query"], "", "", "", ""])

    print(f"Wrote {_MD.name} (read this) and {_CSV.name} (fill claims_total, claims_supported, relevance_1_5).")
    print(f"{len(samples)} answers to label. Then run `python -m backend.eval.report`.")


if __name__ == "__main__":
    main()
