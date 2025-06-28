import argparse

from dotenv import load_dotenv
from tqdm import tqdm
from typing import List, Dict, Optional

from backend.data import MarketNewsDB, ChromaMarketNews
from backend.data.gatherers import MarketAuxGatherer
from .utils import Article, Entity, setup_logger, normalize_name

logger = setup_logger(__name__)
load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch MarketAux articles for given symbols over past days.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="List of stock symbols, e.g. AAPL GOOGL MSFT"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days in the past to fetch data for. 1 means today only."
    )
    parser.add_argument(
        "--save-data",
        action="store_true",
        help="Save the raw data or not."
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Number of pages to fetch for each day."
    )
    return parser.parse_args()


class DataPipeline:
    def __init__(self, gatherer: MarketAuxGatherer, db: MarketNewsDB, indexer: ChromaMarketNews, days: int = 1,
                 max_pages: int = 1):
        self.gatherer = gatherer
        self.db = db
        self.indexer = indexer

        self.days = days
        self.max_pages = max_pages

    def _get_data(self):
        if self.days == 1:
            return self.gatherer.get_data(max_pages=self.max_pages)
        else:
            return self.gatherer.get_historical_data(days=self.days, max_pages_per_day=self.max_pages)

    @staticmethod
    def _parse_article(art_json: Dict) -> Article:
        if "uuid" not in art_json:
            raise ValueError("Missing 'uuid' in article JSON")

        source = art_json.get("source")
        if isinstance(source, dict):
            source = source.get("domain", "")

        seen = set()
        entities = []
        for ent in art_json.get("entities", []):
            if not ent:
                continue
            normalized_name = normalize_name(ent.get("name", ""))
            if normalized_name in seen:
                continue
            seen.add(normalized_name)

            entity = Entity(
                article_uuid=art_json["uuid"],
                symbol=ent.get("symbol", ""),
                name=ent.get("name", ""),
                raw_sentiment=float(ent.get("sentiment_score", 0.0)),
                industry=ent.get("industry")
            )
            entities.append(entity)

        return Article(
            uuid=art_json["uuid"],
            title=art_json.get("title", ""),
            description=art_json.get("description", ""),
            url=art_json.get("url", ""),
            published_at=art_json.get("published_at", ""),
            source=source,
            entities=entities
        )

    def _store_article(self, article: Article) -> None:
        self.db.add_article(article)

    def _index_articles(self, articles: List[Article]) -> None:
        self.indexer.index(articles)

    def process(self) -> None:
        data = self._get_data()

        batches = [data] if isinstance(data, dict) else data
        to_index = []

        for batch in tqdm(batches, desc="Processing batches"):
            articles = batch.get("data", [])
            for art_json in articles:
                try:
                    article = self._parse_article(art_json)
                    self._store_article(article)
                    to_index.append(article)
                except Exception as e:
                    logger.error(f"Error processing article: {e}")

        if to_index:
            self._index_articles(to_index)


def main(symbols: List[str], days: int = 1, save_data: bool = False, max_pages: int = 1,
         gatherer_obj: Optional[MarketAuxGatherer] = None, db_obj: Optional[MarketNewsDB] = None,
         chroma_obj: Optional[ChromaMarketNews] = None):
    logger.info(f"Starting processing for symbols: {symbols} over {days} days, with {max_pages} pages per day.")
    try:
        gatherer = gatherer_obj if gatherer_obj is not None else MarketAuxGatherer(symbols=symbols, save_data=save_data)
        db = db_obj if db_obj is not None else MarketNewsDB()
        chroma_indexer = chroma_obj if chroma_obj is not None else ChromaMarketNews()

        pipeline = DataPipeline(gatherer=gatherer, db=db, indexer=chroma_indexer, days=days, max_pages=max_pages)
        pipeline.process()

        db.log_final_stats()
        chroma_indexer.log_final_stats()
        db.close()
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")


if __name__ == "__main__":
    args = parse_args()
    main(symbols=args.symbols,
         days=args.days,
         save_data=args.save_data,
         max_pages=args.max_pages)
