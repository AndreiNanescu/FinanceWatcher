import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Union, List, Dict, Optional
from utils import setup_logger
from gatherer import main as get_data

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
    sentiment_score REAL,
    industry TEXT,
    FOREIGN KEY(article_uuid) REFERENCES articles(uuid) ON DELETE CASCADE,
    UNIQUE(article_uuid, symbol) 
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
    return parser.parse_args()


@dataclass
class Article:
    uuid: str
    title: Optional[str]
    description: Optional[str]
    url: Optional[str]
    published_at: Optional[str]
    source: Optional[str]
    entities: Optional[List[Dict]] = None


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
        self._init_stats_counters()

    def _init_stats_counters(self):
        self.articles_processed = 0
        self.articles_inserted = 0
        self.articles_duplicate = 0
        self.entities_processed = 0
        self.entities_inserted = 0
        self.entities_duplicate = 0
        self.parse_errors = 0

    def _connect_to_db(self) -> None:
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.execute("PRAGMA journal_mode=WAL")
            logger.info(f"Connected to database {self.db_name}")
        except Exception as e:
            logger.error(f"Error connecting to {self.db_name} database: {e}")
            raise

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")

    def _log_final_stats(self) -> None:
        logger.info(
            f"Insert results: "
            f"Articles: {self.articles_inserted} new, {self.articles_duplicate} duplicates | "
            f"Entities: {self.entities_inserted} new, {self.entities_duplicate} duplicates | "
            f"Parse errors: {self.parse_errors}"
        )

    def create_tables(self) -> None:
        if self.conn is None:
            logger.error("Cannot create tables without DB connection.")
            return

        try:
            with self.conn:
                self.conn.execute(ARTICLES_TABLE)
                self.conn.execute(ENTITIES_TABLE)
            logger.info("Tables created or confirmed existing.")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise

    @staticmethod
    def _parse_article(article_json: Dict) -> Article:
        try:
            source = article_json.get("source")
            if isinstance(source, dict):
                source = source.get("domain", "")

            return Article(
                uuid=article_json["uuid"],
                title=article_json.get("title"),
                description=article_json.get("description"),
                url=article_json.get("url"),
                published_at=article_json.get("published_at"),
                source=source,
                entities=article_json.get("entities", [])
            )
        except KeyError as e:
            logger.error(f"Missing required field in article: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error parsing article: {e}")
            raise

    def add_articles(self, data: Union[Dict, List[Dict]]) -> None:
        if self.conn is None:
            logger.error("No DB connection to add articles.")
            return

        self._init_stats_counters()

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
                self.articles_processed += 1
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
                        self.entities_processed += 1
                        entity_records.append((
                            article.uuid,
                            entity.get("symbol"),
                            entity.get("name"),
                            entity.get("sentiment_score", 0.0),
                            entity.get("industry", ""),
                        ))

                except Exception as e:
                    self.parse_errors += 1
                    logger.error(f"Skipping article due to error: {e}")
                    continue

        try:
            with self.conn:
                cursor = self.conn.executemany('''
                    INSERT OR IGNORE INTO articles 
                    (uuid, title, description, url, published_at, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', article_records)
                self.articles_inserted = cursor.rowcount
                self.articles_duplicate = len(article_records) - cursor.rowcount

                if entity_records:
                    cursor = self.conn.executemany('''
                        INSERT OR IGNORE INTO entities 
                        (article_uuid, symbol, name, sentiment_score, industry)
                        VALUES (?, ?, ?, ?, ?)
                    ''', entity_records)
                    self.entities_inserted = cursor.rowcount
                    self.entities_duplicate = len(entity_records) - cursor.rowcount

            self._log_final_stats()

        except sqlite3.Error as e:
            logger.error(f"Database error during insert: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during database operations: {e}")
            raise


def main(symbols: List[str], days: int = 1, save_data: bool = False):
    logger.info(f"Starting processing for symbols: {symbols} over {days} days")
    try:
        data = get_data(symbols=symbols, days=days, save_data=save_data)
        if not data:
            logger.warning("No data received from gatherer")
            return

        db = MarketNewsDB()
        try:
            db.add_articles(data)
        finally:
            db.close()

        logger.info("Processing completed successfully")
    except Exception as e:
        logger.error(f"Fatal error in main processing: {e}")
        raise


if __name__ == "__main__":
    try:
        args = parse_args()
        main(
            symbols=args.symbols,
            days=args.days,
            save_data=args.save_data
        )
    except Exception as e:
        logger.error(f"Application failed: {e}")
        raise