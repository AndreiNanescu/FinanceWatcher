import json
import logging
from typing import Any

import chromadb
from chromadb.config import Settings

from backend.config import CHROMA_DATA_DIR
from backend.rag import Embedder
from backend.utils import logger, parse_published_at

logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


class ChromaClient:
    def __init__(self, db_name: str = "embeddings"):
        self.db_name = db_name

        self._setup_chroma()

    def _init_path(self) -> str:
        return str(CHROMA_DATA_DIR / self.db_name)

    def _setup_chroma(self) -> None:
        db_path = self._init_path()
        try:
            self.client = chromadb.PersistentClient(path=db_path, settings=Settings(anonymized_telemetry=False))

            self.embedder = Embedder()
            self.collection = self.client.get_or_create_collection(
                name=self.db_name,
                # Embedder duck-types chromadb's EmbeddingFunction protocol.
                embedding_function=self.embedder,  # type: ignore[arg-type]
            )
            logger.info(f"Initialized {self.db_name} Chroma DB at {db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize Chroma DB: {e}")
            raise

    def add(self, documents, metadatas, ids):
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )

    def get(self, ids) -> Any:
        return self.collection.get(ids=ids)

    def get_where(self, where: dict) -> Any:
        """Fetch all documents whose metadata matches `where` (no similarity rank)."""
        return self.collection.get(where=where, include=["documents", "metadatas"])

    def get_where_with_embeddings(self, where: dict) -> Any:
        """Like get_where, but also returns the stored (normalized) embeddings.

        Used by the C1 cosine-similarity evaluation baseline.
        """
        return self.collection.get(where=where, include=["documents", "metadatas", "embeddings"])

    def query(self, query_texts, n_results, where, where_document) -> Any:
        return self.collection.query(
            query_texts=query_texts, n_results=n_results, where=where, where_document=where_document
        )

    def backfill_symbol_flags(self) -> int:
        """One-time migration: add per-symbol boolean flags (see symbol_flag_key)
        to existing documents that predate them. Returns the number updated."""
        from backend.utils import symbol_flag_key

        results = self.collection.get(include=["metadatas"])
        ids = results.get("ids") or []
        metas = results.get("metadatas") or []

        updated_ids: list[str] = []
        updated_metas: list[Any] = []
        for id_, meta in zip(ids, metas, strict=False):
            symbols = str(meta.get("entity_symbols") or "").split(",")
            flags = {symbol_flag_key(s): True for s in symbols if s.strip() and s.strip().upper() != "NO SYMBOL"}
            if any(k not in meta for k in flags):
                updated_ids.append(id_)
                updated_metas.append({**meta, **flags})

        if updated_ids:
            self.collection.update(ids=updated_ids, metadatas=updated_metas)
        logger.info(f"Backfilled symbol flags on {len(updated_ids)} document(s)")
        return len(updated_ids)

    def delete_article(self, article_id: str) -> None:
        where: Any = {"article_id": {"$eq": article_id}}
        results = self.collection.get(where=where)
        if results["ids"]:
            self.collection.delete(ids=results["ids"])

    def export_as_json(self, output_path: str):
        results = self.collection.get(limit=1000000, include=["documents", "metadatas"])

        export_data = []
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        ids = results.get("ids") or []

        for doc, meta, id_ in zip(docs, metas, ids, strict=False):
            meta = dict(meta)
            doc_lines = doc.splitlines()
            doc_cleaned = "\n\n".join(line.strip() for line in doc_lines)

            pub_at = meta.get("published_at")
            if isinstance(pub_at, str):
                dt = parse_published_at(pub_at)
                if dt is not None:
                    meta["published_at"] = dt.strftime("%b %d, %Y %H:%M UTC")

            entities_str = meta.get("entities", None)
            try:
                if entities_str and isinstance(entities_str, str):
                    meta["entities"] = json.loads(entities_str)
            except json.JSONDecodeError:
                pass

            export_data.append(
                {
                    "id": id_,
                    "document": doc_cleaned,
                    "metadata": meta,
                }
            )

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(export_data)} articles to {output_path} with human-readable formatting.")
