import chromadb
from typing import List, Dict, Optional
from data.embedder import Embedder
from data.market_news_db import MarketNewsDB
from utils import NewsDocument, Article, Entity
from pathlib import Path

class ChromaMarketNews:
    def __init__(self, market_news_db: MarketNewsDB, db_path: str = "embeddings"):
        root_path = Path(__file__).resolve().parent.parent
        chroma_path = root_path / db_path

        self.client = chromadb.PersistentClient(path=str(chroma_path))
        self.embedder = Embedder()

        self.collection = self.client.get_or_create_collection(
            name="embeddings",
            embedding_function=self.embedder
        )
        self.market_news_db = market_news_db


    def _load_news(self) -> None:
        documents = []
        metadatas = []
        ids = []

        articles_df, entities_df = self.market_news_db.load_tables()

        for _, article_row in articles_df.iterrows():
            article_entities = entities_df[entities_df['article_uuid'] == article_row['uuid']]
            entities = [
                Entity(
                    article_uuid=entity_row['article_uuid'],
                    symbol=entity_row['symbol'],
                    name=entity_row['name'],
                    raw_sentiment=entity_row['sentiment'],
                    industry=entity_row.get('industry')
                )
                for _, entity_row in article_entities.iterrows()
            ]

            article = Article(
                uuid=article_row['uuid'],
                title=article_row['title'],
                description=article_row['description'],
                url=article_row['url'],
                published_at=article_row['published_at'],
                source=article_row['source'],
                entities=entities
            )

            if not entities:
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
                documents.append(doc.content)
                metadatas.append(doc.metadata)
                ids.append(doc.id)
            else:
                for entity in entities:
                    doc = NewsDocument.from_article_entity(article, entity)
                    documents.append(doc.content)
                    metadatas.append(doc.metadata)
                    ids.append(doc.id)

        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

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
            sentiment: Optional[str] = None,
            date_range: Optional[tuple] = None,
            n_results: int = 10
    ) -> List[Dict]:
        filters = {}

        if entity_name:
            filters["entity"] = {"$eq": entity_name}

        if symbol:
            filters["symbol"] = {"$eq": symbol}

        if sentiment:
            filters["sentiment_label"] = {"$eq": sentiment}

        if date_range:
            filters["published_at"] = {
                "$gte": date_range[0],
                "$lte": date_range[1]
            }

        return self.query(
            query_text=entity_name or symbol or "market",
            n_results=n_results,
            filters=filters if filters else None
        )

    def delete_article(self, article_id: str) -> None:
        results = self.collection.get(
            where={"article_id": {"$eq": article_id}}
        )

        if results['ids']:
            self.collection.delete(ids=results['ids'])

def main():
    db = MarketNewsDB()
    news = ChromaMarketNews(market_news_db=db, db_path ='embeddings')

    news._load_news()
    results = news.query(query_text="tech", n_results=5)
    for r in results:
        print("\nDocument:\n", r["document"])
        print("Metadata:", r["metadata"])
        print("Score:", r["score"])

if __name__ == '__main__':
    main()