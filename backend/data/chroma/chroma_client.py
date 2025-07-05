import chromadb
import json

from datetime import datetime
from pathlib import Path

from backend.rag import Embedder
from backend.utils import logger

class ChromaClient:
    def __init__(self, db_name: str = 'embeddings'):
        self.db_name = db_name

        self._setup_chroma()

    def _init_path(self) -> str:
        root_path = Path(__file__).resolve().parent.parent
        chroma_path = root_path / 'db' / self.db_name

        return str(chroma_path)

    def _setup_chroma(self) -> None:
        db_path = self._init_path()
        try:
            self.client = chromadb.PersistentClient(path=db_path)
            self.embedder = Embedder()
            self.collection = self.client.get_or_create_collection(
                name=self.db_name,
                embedding_function=self.embedder
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

    def get(self, ids):
        return self.collection.get(ids=ids)

    def query(self, query_texts, n_results, where, where_document):
        return self.collection.query(
            query_texts=query_texts,
            n_results=n_results,
            where=where,
            where_document=where_document
        )

    def delete_article(self, article_id: str) -> None:
        results = self.collection.get(where={"article_id": {"$eq": article_id}})
        if results['ids']:
            self.collection.delete(ids=results['ids'])

    def export_as_json(self, output_path: str):
        results = self.collection.get(
            limit=1000000,
            include=["documents", "metadatas"]
        )

        export_data = []
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])

        for doc, meta, id_ in zip(docs, metas, ids):
            doc_lines = doc.splitlines()
            doc_cleaned = "\n\n".join(line.strip() for line in doc_lines)

            pub_at = meta.get("published_at")
            if pub_at:
                try:
                    dt = datetime.strptime(pub_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                    meta["published_at"] = dt.strftime("%b %d, %Y %H:%M UTC")
                except Exception:
                    pass

            entities_str = meta.get("entities", None)
            try:
                if entities_str and isinstance(entities_str, str):
                    meta["entities"] = json.loads(entities_str)
            except json.JSONDecodeError:
                pass

            export_data.append({
                "id": id_,
                "document": doc_cleaned,
                "metadata": meta,
            })

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(export_data)} articles to {output_path} with human-readable formatting.")