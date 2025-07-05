from typing import List, Tuple, Dict, Any

from backend.utils import logger, Article, NewsDocument
from .chroma_client import ChromaClient

class Indexer:
    def __init__(self, chroma_client: ChromaClient):
        if chroma_client is None:
            raise ValueError(f"chroma_client parameter cannot be None in Indexer")

        self.client = chroma_client
        logger.info('Indexer initialized')

    def ingest(self, articles: List[Article]) -> None:
        if not articles:
            logger.warning("No articles to index.")
            return

        docs, metas, ids = self._build_documents(articles)

        new_docs, new_metas, new_ids = self._filter_existing_documents(docs, metas, ids)

        if not new_ids:
            logger.info("No new documents to add — all were already indexed.")
            return

        self._add_to_collection(new_docs, new_metas, new_ids)
        logger.info(f"Indexing results: Articles {len(new_docs)} new | {len(docs) - len(new_docs)} duplicates")

    @staticmethod
    def _build_documents(articles: List[Article]) -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
        docs, metas, ids = [], [], []
        for article in articles:
            doc = NewsDocument.from_article(article)
            docs.append(doc.content)
            metas.append(doc.metadata)
            ids.append(doc.id)
        return docs, metas, ids

    def _filter_existing_documents(self, docs: List[str], metas: List[Dict], ids: List[str]) -> Tuple[List[str], List[Dict], List[str]]:
        existing_docs = self.client.get(ids=ids)
        existing_ids = set(existing_docs.get('ids', []))
        new_docs, new_metas, new_ids = [], [], []
        for doc, meta, id_ in zip(docs, metas, ids):
            if id_ not in existing_ids:
                new_docs.append(doc)
                new_metas.append(meta)
                new_ids.append(id_)
        return new_docs, new_metas, new_ids

    def _add_to_collection(self, docs: List[str], metas: List[Dict], ids: List[str], batch_size: int = 100) -> None:
        try:
            for i in range(0, len(ids), batch_size):
                batch_docs = docs[i:i+batch_size]
                batch_metas = metas[i:i+batch_size]
                batch_ids = ids[i:i+batch_size]
                self.client.add(
                    documents=batch_docs,
                    metadatas=batch_metas,
                    ids=batch_ids
                )
        except Exception as e:
            logger.error(f"Error during batch indexing: {e}")
            raise