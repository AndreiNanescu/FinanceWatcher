import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from backend.config import DB_DIR
from backend.utils import Article, Entity, logger

ARTICLES_TABLE = """
CREATE TABLE IF NOT EXISTS articles (
    uuid TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    keywords TEXT,
    url TEXT UNIQUE,
    published_at TEXT,
    fetched_on TEXT,
    entities_json TEXT, -- JSON-encoded list of Entity objects
    full_text TEXT, -- full extracted article text (source data; summaries are derived)
    full_text_status TEXT NOT NULL DEFAULT 'pending' -- pending | ok | failed
);
"""

BLACKLIST_TABLE = """
CREATE TABLE IF NOT EXISTS blacklisted_entities (
    url TEXT PRIMARY KEY
);
"""

LAST_UPDATE = """
CREATE TABLE IF NOT EXISTS last_update (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_updated TEXT
);
"""


class MarketNewsDB:
    def __init__(self, db_path: Path | str | None = None, db_name: str = "market_news.db"):
        if db_path is None:
            db_path = DB_DIR

        db_path = Path(db_path)
        db_path.mkdir(parents=True, exist_ok=True)
        self.db_name = db_path / db_name

        self.conn: sqlite3.Connection | None = None

        self._connect_to_db()
        self._create_tables()
        self._migrate_schema()

    def _connect_to_db(self) -> None:
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.execute("PRAGMA journal_mode=WAL")
            logger.info(f"Connected to database {self.db_name}")
        except Exception as exception:
            logger.error(f"Error connecting to {self.db_name} database: {exception}")
            raise

    def _create_tables(self):
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            with self.conn:
                self.conn.execute(ARTICLES_TABLE)
                self.conn.execute(BLACKLIST_TABLE)
                self.conn.execute(LAST_UPDATE)
            logger.info("Tables created or confirmed existing.")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise

    def _migrate_schema(self) -> None:
        """Add columns introduced after a DB was created (CREATE TABLE IF NOT
        EXISTS never alters existing tables). Existing rows get the column
        defaults — full_text_status 'pending' marks them for the backfill."""
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(articles)")}
        migrations = {
            "full_text": "ALTER TABLE articles ADD COLUMN full_text TEXT",
            "full_text_status": "ALTER TABLE articles ADD COLUMN full_text_status TEXT NOT NULL DEFAULT 'pending'",
        }
        try:
            with self.conn:
                for column, ddl in migrations.items():
                    if column not in existing:
                        self.conn.execute(ddl)
                        logger.info(f"Migrated articles table: added column '{column}'")
        except sqlite3.Error as e:
            logger.error(f"Failed to migrate articles schema: {e}")
            raise

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")

    @staticmethod
    def _serialize_article(article: Article) -> tuple:
        entities_json = json.dumps([asdict(e) for e in article.entities])
        return (
            article.uuid,
            article.title,
            article.description,
            article.keywords,
            article.url,
            article.published_at,
            article.fetched_on,
            entities_json,
            article.full_text,
            "ok" if article.full_text else "pending",
        )

    def _update_last_updated(self):
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        now = datetime.now().strftime("%B %d, %Y at %H:%M")
        self.conn.execute(
            """INSERT INTO last_update (id, last_updated)
               VALUES (1, ?)
               ON CONFLICT(id) DO UPDATE SET last_updated = excluded.last_updated""",
            (now,),
        )

    def add(self, articles: Article | list[Article]) -> None:
        if self.conn is None:
            raise RuntimeError("No DB connection.")

        if isinstance(articles, Article):
            articles = [articles]
        if not articles:
            logger.warning("No articles to insert.")
            return

        try:
            with self.conn:
                self.conn.executemany(
                    """INSERT OR IGNORE INTO articles
                       (uuid, title, description, keywords, url, published_at, fetched_on, entities_json,
                        full_text, full_text_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [self._serialize_article(article) for article in articles],
                )
                self._update_last_updated()
        except Exception as e:
            logger.error(f"Failed to insert articles: {e}")
            raise

    def set_full_text(self, uuid: str, full_text: str | None, status: str) -> None:
        """Upsert the full article text for an existing row (backfill path).

        status: 'ok' when text was fetched, 'failed' when the link is dead or
        extraction produced nothing — failed rows are not retried by the
        backfill, so a dead URL is only hammered once.
        """
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE articles SET full_text = ?, full_text_status = ? WHERE uuid = ?",
                    (full_text, status, uuid),
                )
        except sqlite3.Error as e:
            logger.error(f"Failed to set full text for article {uuid}: {e}")
            raise

    def get_articles_pending_full_text(self) -> list[tuple[str, str]]:
        """(uuid, url) pairs still needing a full-text fetch, oldest first —
        the oldest links are the closest to rotting away."""
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            cursor = self.conn.execute(
                "SELECT uuid, url FROM articles WHERE full_text_status = 'pending' ORDER BY published_at ASC"
            )
            return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Error fetching articles pending full text: {e}")
            raise

    def get_uuids(self) -> list[str]:
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            cursor = self.conn.execute("SELECT uuid FROM articles")
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error fetching article UUIDs: {e}")
            raise

    def get_urls(self) -> list[str]:
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            cursor = self.conn.execute("SELECT url FROM articles")
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error fetching article URLs: {e}")
            raise

    def get_blacklist(self) -> list[str]:
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            cursor = self.conn.execute("SELECT url FROM blacklisted_entities")
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error fetching blacklisted URLs: {e}")
            raise

    def add_to_blacklist(self, urls: list[str]) -> None:
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        if not urls:
            return

        try:
            with self.conn:
                self.conn.executemany(
                    "INSERT OR IGNORE INTO blacklisted_entities (url) VALUES (?)", [(url,) for url in urls]
                )
        except sqlite3.Error as e:
            logger.error(f"Error inserting blacklisted URLs: {e}")
            raise

    def clear_blacklist(self) -> None:
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            with self.conn:
                self.conn.execute("DELETE FROM blacklisted_entities;")
            logger.info("Cleared all blacklisted URLs.")
        except sqlite3.Error as e:
            logger.error(f"Failed to clear blacklist: {e}")
            raise

    def delete_articles_by_description(self, description_substring: str):
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            with self.conn:
                cursor = self.conn.execute(
                    "DELETE FROM articles WHERE description LIKE ?", ("%" + description_substring + "%",)
                )
                deleted_count = cursor.rowcount
            logger.info(f"Deleted {deleted_count} articles matching description pattern: {description_substring}")
        except sqlite3.Error as e:
            logger.error(f"Failed to delete articles by description pattern '{description_substring}': {e}")
            raise

    def export_articles_to_json(self, n: int, file_path: str | Path = "exported_articles.json") -> str:
        if self.conn is None:
            raise RuntimeError("No DB connection.")

        try:
            cursor = self.conn.execute(
                "SELECT uuid, title, description, keywords, url, published_at, fetched_on, entities_json FROM articles ORDER BY published_at DESC LIMIT ?",  # noqa: E501
                (n,),
            )
            rows = cursor.fetchall()

            articles_list = []
            for row in rows:
                article_dict = {
                    "uuid": row[0],
                    "title": row[1],
                    "description": row[2],
                    "keywords": row[3],
                    "url": row[4],
                    "published_at": row[5],
                    "fetched_on": row[6],
                    "entities": json.loads(row[7]) if row[7] else [],
                }
                articles_list.append(article_dict)

            json_data = json.dumps(articles_list, indent=2)

            # Save to file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json_data)

            logger.info(f"Exported {len(articles_list)} articles to JSON file: {file_path}")

            return json_data

        except Exception as e:
            logger.error(f"Failed to export articles to JSON: {e}")
            raise

    def get_articles(self) -> list[Article]:
        if self.conn is None:
            raise RuntimeError("No DB connection")

        try:
            cursor = self.conn.execute(
                "SELECT uuid, title, description, keywords, url, published_at, fetched_on, entities_json FROM articles ORDER BY published_at DESC",  # noqa: E501
            )
            rows = cursor.fetchall()

            articles_list = []

            for row in rows:
                entities_list = []

                entities_json = json.loads(row[7] if row[7] else "[]")

                for entity in entities_json:
                    ent = Entity(
                        symbol=entity["symbol"],
                        name=entity["name"],
                        sentiment=entity["sentiment"],
                        industry=entity["industry"],
                    )
                    entities_list.append(ent)

                article = Article(
                    uuid=row[0],
                    title=row[1],
                    description=row[2],
                    keywords=row[3],
                    url=row[4],
                    published_at=row[5],
                    fetched_on=row[6],
                    entities=entities_list,
                )

                articles_list.append(article)

            return articles_list

        except Exception as e:
            logger.error(f"Failed to export articles to list: {e}")
            raise

    def delete_articles_by_url_pattern(self, pattern: str):
        if self.conn is None:
            raise RuntimeError("No DB connection.")
        try:
            with self.conn:
                cursor = self.conn.execute("DELETE FROM articles WHERE url LIKE ?", ("%" + pattern + "%",))
                deleted_count = cursor.rowcount
            logger.info(f"Deleted {deleted_count} articles with URL containing: {pattern}")

        except sqlite3.Error as e:
            logger.error(f"Failed to delete articles by URL pattern '{pattern}': {e}")
            raise
