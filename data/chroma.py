import logging
import chromadb

from pathlib import Path
from typing import List, Dict, Optional

from data.embedder import Embedder
from utils import NewsDocument, Article, setup_logger

logger = setup_logger(__name__)


class ChromaMarketNews:
    def __init__(self, db_path: str = "embeddings"):
        root_path = Path(__file__).resolve().parent.parent
        chroma_path = root_path / 'db' / db_path

        self.stats = {
            'articles_count': 0,
            'entities_count': 0,
        }

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

    def query(
            self,
            query_text: str,
            n_results: int = 5,
            filters: Optional[Dict] = None,
            contains_text: Optional[str] = None
    ) -> List[Dict]:
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=filters,
            where_document={"$contains": contains_text} if contains_text else None
        )

        formatted_results = []
        for doc, metadata in zip(results['documents'][0], results['metadatas'][0]):
            formatted_results.append({
                "document": doc,
                "metadata": metadata,
                "score": results['distances'][0][results['documents'][0].index(doc)]
            })

        return formatted_results

    def get_news_by_entity(
            self,
            entity_name: Optional[str] = None,
            symbol: Optional[str] = None,
            date_range: Optional[tuple] = None,
            n_results: int = 10
    ) -> List[Dict]:
        filters = {}

        if date_range:
            filters["published_at"] = {
                "$gte": date_range[0],
                "$lte": date_range[1]
            }

        return self.query(
            query_text=entity_name or symbol,
            n_results=n_results,
            filters=filters if filters else None
        )

    def delete_article(self, article_id: str) -> None:
        results = self.collection.get(
            where={"article_id": {"$eq": article_id}}
        )

        if results['ids']:
            self.collection.delete(ids=results['ids'])

    def index(self, articles: List[Article]) -> None:
        if not articles:
            logger.warning("No articles to index.")
            return
        self.stats['articles_count'] = len(articles)

        docs, metas, ids = [], [], []

        for article in articles:
            if not article.entities:
                doc = NewsDocument(
                    id=article.uuid,
                    content=f"""
                    Title: {article.title}
                    Published on: {article.published_at}
                    Source: {article.source}
                    URL: {article.url}

                    Description: {article.description}
                    """.strip(),
                    metadata={
                        "article_id": article.uuid,
                        "title": article.title,
                        "source": article.source,
                        "published_at": article.published_at,
                        "url": article.url,
                        "entity_type": "general"
                    }
                )
                docs.append(doc.content)
                metas.append(doc.metadata)
                ids.append(doc.id)
            else:
                for entity in article.entities:
                    doc = NewsDocument.from_article_entity(article, entity)
                    docs.append(doc.content)
                    metas.append(doc.metadata)
                    ids.append(doc.id)

        try:
            self.collection.add(documents=docs, metadatas=metas, ids=ids)
            self.stats['entities_count'] = len(ids)
        except Exception as e:
            logger.error(f"Error during indexing: {e}")
            raise

    def log_final_stats(self) -> None:
        logger.info(
            f"Index results: "
            f"Articles: {self.stats['articles_count']}| Entities: {self.stats['entities_count']} | "
            f"NOTE: Chroma isn't able to log the difference between duplicates and new "
        )
