import chromadb
import json

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from backend.rag import BGEReranker
from backend.rag import Embedder
from backend.utils import NewsDocument, Article, setup_logger, Candidate

logger = setup_logger(__name__)


class ChromaMarketNews:
    def __init__(self, db_path: str = "embeddings"):
        self._setup_chroma(db_path)
        self.reranker = BGEReranker()
        self.stats = {
            'articles_count': 0,
            'entities_count': 0,
            'duplicated_entities': 0
        }

    def delete_article(self, article_id: str) -> None:
        results = self.collection.get(where={"article_id": {"$eq": article_id}})
        if results['ids']:
            self.collection.delete(ids=results['ids'])

    def log_final_stats(self) -> None:
        logger.info(
            f"Index results: "
            f"Articles: {self.stats['articles_count']} | "
            f"Entities: {self.stats['entities_count']} new, {self.stats['duplicated_entities']} duplicates"
        )

    def _setup_chroma(self, db_path: str):
        root_path = Path(__file__).resolve().parent.parent
        chroma_path = root_path / 'db' / db_path
        try:
            self.client = chromadb.PersistentClient(path=str(chroma_path))
            self.embedder = Embedder()
            self.collection = self.client.get_or_create_collection(
                name="embeddings",
                embedding_function=self.embedder
            )
            logger.info(f"Initialized ChromaMarketNews with collection 'embeddings' at {chroma_path}")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaMarketNews: {e}")
            raise

    def index(self, articles: List[Article]) -> None:
        if not articles:
            logger.warning("No articles to index.")
            return

        self.stats['articles_count'] = len(articles)

        docs, metas, ids = self._build_documents(articles)

        new_docs, new_metas, new_ids = self._filter_existing_documents(docs, metas, ids)

        if not new_ids:
            logger.info("No new documents to add — all were already indexed.")
            self.stats.update({
                'entities_count': 0,
                'duplicated_entities': len(docs)
            })
            return

        self._add_to_collection(new_docs, new_metas, new_ids)
        self.stats.update({
            'entities_count': len(new_ids),
            'duplicated_entities': len(docs) - len(new_ids)
        })

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
        existing_docs = self.collection.get(ids=ids)
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
                self.collection.add(
                    documents=batch_docs,
                    metadatas=batch_metas,
                    ids=batch_ids
                )
        except Exception as e:
            logger.error(f"Error during batch indexing: {e}")
            raise

    def query(self, query_text: str, n_results: int = 50, filters: Optional[dict] = None,
              contains_text: Optional[str] = None, top_n_rerank: int = 5) -> List[Dict]:

        raw_results = self._execute_query(query_text, n_results, filters, contains_text)
        candidates = self._build_candidates(raw_results)

        if not candidates:
            return []

        recent_candidates = self._filter_by_date(candidates, months=6)
        if not recent_candidates:
            return []

        final_results = self._rerank_candidates(query_text, recent_candidates, top_n_rerank)
        return final_results

    def _execute_query(self, query_text: str, n_results: int,
                       filters: Optional[dict], contains_text: Optional[str]) -> Dict:
        return self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=filters if filters else None,
            where_document={"$contains": contains_text} if contains_text else None
        )

    @staticmethod
    def _build_candidates(results: Dict) -> List[Dict]:
        docs = results['documents'][0]
        metas = results['metadatas'][0]
        scores = results['distances'][0]
        return [
            {"document": doc, "metadata": meta, "score": score}
            for doc, meta, score in zip(docs, metas, scores)
        ]

    @staticmethod
    def _filter_by_date(candidates: List[Candidate], months: int = 6) -> List[Candidate]:
        cutoff_date = datetime.utcnow() - timedelta(days=30 * months)
        filtered = []
        for c in candidates:
            published_at_str = c["metadata"].get("published_at")
            if not published_at_str:
                continue
            try:
                published_at_dt = datetime.strptime(published_at_str, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                try:
                    published_at_dt = datetime.strptime(published_at_str, "%Y-%m-%dT%H:%M:%SZ")
                except Exception as e:
                    logger.debug(f"Failed to parse date {published_at_str}: {e}")
                    continue
            if published_at_dt >= cutoff_date:
                filtered.append(c)
        return filtered

    def _rerank_candidates(self, query_text: str, candidates: List[Dict], top_n: int) -> List[Dict]:
        passages = [c["document"] for c in candidates]
        reranked = self.reranker.rerank(query_text, passages, top_k=top_n)

        top_candidates = []
        for passage, rerank_score in reranked:
            orig = next(c for c in candidates if c["document"] == passage)
            top_candidates.append({
                "document": passage,
                "metadata": orig["metadata"],
                "retriever_score": orig["score"],
                "reranker_score": rerank_score,
            })
        top_candidates.sort(key=lambda x: x["reranker_score"], reverse=True)
        return top_candidates

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


