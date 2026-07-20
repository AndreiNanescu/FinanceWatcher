"""Export the current corpus for manual gold-set labelling.

Writes backend/eval/datasets/corpus_dump.json (id, title, url, published_at,
entity_symbols, document) — the `id` is the ChromaDB/SQLite uuid used as the
relevance key in retrieval_gold.json.

    python -m backend.eval.export_corpus
"""

import json
import os
import sys
from pathlib import Path

# Allow running as a plain script from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from backend.data.chroma.chroma_client import ChromaClient  # noqa: E402
from backend.utils import logger  # noqa: E402

_OUT = Path(__file__).resolve().parent / "datasets" / "corpus_dump.json"


def main() -> None:
    client = ChromaClient()
    res = client.collection.get(include=["documents", "metadatas"])
    ids = res.get("ids") or []
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []

    rows = []
    for id_, doc, meta in zip(ids, docs, metas, strict=False):
        title = (doc or "").splitlines()[0].removeprefix("Title:").strip()
        rows.append(
            {
                "id": id_,
                "title": title,
                "url": meta.get("url", ""),
                "published_at": meta.get("published_at", ""),
                "entity_symbols": meta.get("entity_symbols", ""),
                "document": doc,
            }
        )

    rows.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Exported {len(rows)} articles to {_OUT}")
    print(f"Exported {len(rows)} articles -> {_OUT}")


if __name__ == "__main__":
    main()
