import argparse
import sqlite3

import pandas as pd

from pathlib import Path
from typing import Union, List, Dict
from utils import setup_logger, Entity, Article
from .gatherer import main as get_data

logger = setup_logger(__name__)

ARTICLES_TABLE = '''
CREATE TABLE IF NOT EXISTS articles (
    uuid TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    url TEXT UNIQUE,
    published_at TEXT,
    source TEXT
)
'''

ENTITIES_TABLE = '''
CREATE TABLE IF NOT EXISTS entities (
    entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_uuid TEXT,
    symbol TEXT,
    name TEXT,
    normalized_name TEXT,
    sentiment TEXT,
    industry TEXT,
    FOREIGN KEY(article_uuid) REFERENCES articles(uuid) ON DELETE CASCADE,
    UNIQUE(article_uuid, normalized_name)
)
'''

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
        help="Whether to save the raw data or not."
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Number of pages to fetch for each day."
    )
    return parser.parse_args()


class MarketNewsDB:
    def __init__(self, db_path: Union[Path, str] = None, db_name: str = 'market_news.db'):
        if db_path is None:
            root_path = Path(__file__).resolve().parent.parent
            db_path = root_path / 'db'

        db_path = Path(db_path)
        db_path.mkdir(parents=True, exist_ok=True)

        self.db_name = db_path / db_name
        self.conn = None
        self._connect_to_db()
        self.create_tables()

        self.stats = {
            'articles_processed': 0,
            'articles_inserted': 0,
            'articles_duplicate': 0,
            'entities_processed': 0,
            'entities_inserted': 0,
            'entities_duplicate': 0,
            'parse_errors': 0
        }

    def _connect_to_db(self) -> None:
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.execute("PRAGMA journal_mode=WAL")
            logger.info(f"Connected to database {self.db_name}")
        except Exception as exception:
            logger.error(f"Error connecting to {self.db_name} database: {exception}")
            raise

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")

    def log_final_stats(self) -> None:
        logger.info(
            f"Insert results: "
            f"Articles: {self.stats['articles_inserted']} new, {self.stats['articles_duplicate']} duplicates | "
            f"Entities: {self.stats['entities_inserted']} new, {self.stats['entities_duplicate']} duplicates | "
            f"Parse errors: {self.stats['parse_errors']}"
        )

    def load_tables(self):
        if self.conn is None:
            logger.error("No DB connection to load tables.")
            return pd.DataFrame(), pd.DataFrame()

        try:
            articles_df = pd.read_sql_query("SELECT * FROM articles", self.conn)
            entities_df = pd.read_sql_query("SELECT * FROM entities", self.conn)
            return articles_df, entities_df
        except Exception as e:
            logger.error(f"Error loading tables from database: {e}")
            return pd.DataFrame(), pd.DataFrame()

    def create_tables(self) -> None:
        if self.conn is None:
            logger.error("Cannot create tables without DB connection.")
            return

        try:
            with self.conn:
                self.conn.execute(ARTICLES_TABLE)
                self.conn.execute(ENTITIES_TABLE)
            logger.info("Tables created or confirmed existing.")
        except Exception as exception:
            logger.error(f"Failed to create tables: {exception}")
            raise

    @staticmethod
    def _parse_article(article_json: Dict) -> Article:
        try:
            source = article_json.get("source")
            if isinstance(source, dict):
                source = source.get("domain", "")

            entities = [
                Entity(
                    article_uuid=article_json["uuid"],
                    symbol=entity_json.get("symbol", ""),
                    name=entity_json.get("name", ""),
                    raw_sentiment=float(entity_json.get("sentiment_score", 0.0)),
                    industry=entity_json.get("industry")
                )
                for entity_json in article_json.get("entities", [])
                if entity_json
            ]

            return Article(
                uuid=article_json["uuid"],
                title=article_json.get("title", ""),
                description=article_json.get("description", ""),
                url=article_json.get("url", ""),
                published_at=article_json.get("published_at", ""),
                source=source,
                entities=entities
            )

        except (KeyError, ValueError) as exception:
            logger.error(f"Error parsing article: {exception}")
            raise

    @staticmethod
    def _parse_entity(article_uuid: str, entity_json: Dict) -> Entity:
        try:
            return Entity(
                article_uuid=article_uuid,
                symbol=entity_json.get("symbol", ""),
                name=entity_json.get("name", ""),
                raw_sentiment=float(entity_json.get("sentiment_score", 0.0)),
                industry=entity_json.get("industry")
            )
        except ValueError as exception:
            logger.error(f"Invalid sentiment score in entity: {exception}")
            raise

    def add_articles(self, data: Union[Dict, List[Dict]]) -> None:
        if self.conn is None:
            logger.error("No DB connection to add articles.")
            return

        batches = [data] if isinstance(data, dict) else data
        if not batches:
            logger.warning("Received empty data batch.")
            return

        article_records = []
        entity_records = []

        for batch in batches:
            if not batch or not isinstance(batch, dict):
                continue

            articles = batch.get("data", [])
            if not isinstance(articles, list):
                continue

            for article_json in articles:
                self.stats['articles_processed'] += 1
                try:
                    article = self._parse_article(article_json)
                    article_records.append((
                        article.uuid,
                        article.title,
                        article.description,
                        article.url,
                        article.published_at,
                        article.source,
                    ))

                    for entity in article.entities:
                        self.stats['entities_processed'] += 1
                        entity_records.append((
                            article.uuid,
                            entity.symbol,
                            entity.name,
                            entity.normalized_name,
                            entity.formatted_sentiment,
                            entity.industry,
                        ))

                except Exception as exception:
                    self.stats['parse_errors'] += 1
                    logger.error(f"Skipping article due to error: {exception}")
                    continue

        try:
            with self.conn:
                cursor = self.conn.executemany('''
                    INSERT OR IGNORE INTO articles 
                    (uuid, title, description, url, published_at, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', article_records)
                self.stats['articles_inserted'] = cursor.rowcount
                self.stats['articles_duplicate'] = len(article_records) - cursor.rowcount

                if entity_records:
                    cursor = self.conn.executemany('''
                        INSERT OR IGNORE INTO entities 
                        (article_uuid, symbol, name, normalized_name, sentiment, industry)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', entity_records)
                    self.stats['entities_inserted'] = cursor.rowcount
                    self.stats['entities_duplicate'] = len(entity_records) - cursor.rowcount

            self.log_final_stats()

        except sqlite3.Error as exception:
            logger.error(f"Database error during insert: {exception}")
            raise
        except Exception as exception:
            logger.error(f"Unexpected error during database operations: {exception}")
            raise

    def add_article(self, article: Article) -> None:
        if self.conn is None:
            raise RuntimeError("Database connection is not established.")

        self.stats['articles_processed'] += 1
        try:
            with self.conn:
                cursor = self.conn.execute(
                    '''
                    INSERT OR IGNORE INTO articles
                    (uuid, title, description, url, published_at, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        article.uuid,
                        article.title,
                        article.description,
                        article.url,
                        article.published_at,
                        article.source,
                    )
                )
                inserted = cursor.rowcount
                self.stats['articles_inserted'] += inserted
                self.stats['articles_duplicate'] += (1 - inserted)

                if article.entities:
                    entity_records = [
                        (
                            entity.article_uuid,
                            entity.symbol,
                            entity.name,
                            entity.normalized_name,
                            entity.formatted_sentiment,
                            entity.industry
                        )
                        for entity in article.entities
                    ]
                    cursor = self.conn.executemany(
                        '''
                        INSERT OR IGNORE INTO entities
                        (article_uuid, symbol, name, normalized_name, sentiment, industry)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''',
                        entity_records
                    )
                    inserted_entities = cursor.rowcount
                    self.stats['entities_processed'] += len(entity_records)
                    self.stats['entities_inserted'] += inserted_entities
                    self.stats['entities_duplicate'] += len(entity_records) - inserted_entities


        except Exception as error:
            self.stats['parse_errors'] += 1
            logger.error(f"Error inserting article {article.uuid}: {error}")
            raise


def main(symbols: List[str], days: int = 1, save_data: bool = False, max_pages: int = 1):
    logger.info(f"Starting processing for symbols: {symbols} over {days} days, with {max_pages} pages per day.")
    try:
        data = get_data(symbols=symbols, days=days, save_data=save_data, max_pages=max_pages)
        if not data:
            logger.warning("No data received from gatherer")
            return

        db = MarketNewsDB()
        try:
            db.add_articles(data)
        finally:
            db.close()

        logger.info("Processing completed successfully")
    except Exception as exception:
        logger.error(f"Fatal error in main processing: {exception}")
        raise


if __name__ == "__main__":
    try:
        args = parse_args()
        main(
            symbols=args.symbols,
            days=args.days,
            save_data=args.save_data,
            max_pages=args.max_pages
        )
    except Exception as e:
        logger.error(f"Application failed: {e}")
        raise