import argparse
import os
import requests

from .base import DataGatherer

from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
from tqdm import tqdm

from backend.utils import (setup_logger, save_dict_as_json, StopFetching, MARKETAUX_API_KEY_ENV, MARKETAUX_BASE_URL_ENV,
                           Entity, format_sentiment)
from backend.utils import Article as MyArticle

from .scraper import ArticleScraper

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

class MarketAuxGatherer(DataGatherer):
    def __init__(self, symbols: List[str], save_data: bool = False, language: str = "en", filter_entities: bool = True,
                 limit: int = 3):
        super().__init__(symbols, save_data)
        self.language = language
        self.filter_entities = filter_entities
        self.limit = limit
        self.article_scraper = ArticleScraper()


    def _save_raw_json(self, data: dict, base_dir: Optional[str] = None, published_on: Optional[str] = None) -> str:
        if published_on:
            timestamp = published_on.replace("-", "") + "T000000Z"
        else:
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

        symbol_str = "_".join(s.replace("/", "-") for s in self.symbols)[:50]
        filename = f"marketaux_{symbol_str}_{timestamp}.json"

        base_dir = base_dir or "raw"
        filepath = Path(base_dir) / filename

        save_dict_as_json(data, filepath)
        return str(filepath)

    def _request_data(self, published_on: Optional[str] = None, page: int = 1) -> Optional[dict]:
        api_key = os.getenv(MARKETAUX_API_KEY_ENV)
        url = os.getenv(MARKETAUX_BASE_URL_ENV)
        if not api_key or not url:
            logger.error(f"Missing environment variables {MARKETAUX_API_KEY_ENV} or {MARKETAUX_BASE_URL_ENV}")
            return None

        params = {
            "api_token": api_key,
            "symbols": ",".join(self.symbols),
            "language": self.language,
            "filter_entities": self.filter_entities,
            "limit": self.limit,
            "page": page,
        }

        if published_on:
            try:
                datetime.strptime(published_on, "%Y-%m-%d")
                params['published_on'] = published_on
            except ValueError:
                logger.warning(f"Invalid published_on date format: {published_on}. Expected YYYY-MM-DD.")

        try:
            response = requests.get(url=url, params=params)
            response.raise_for_status()
            data = response.json()

            articles = data.get("data", [])
            if articles and self.save_data:
                self._save_raw_json(data, published_on=published_on)

            return data

        except requests.Timeout:
            logger.error("Request timed out")
            raise StopFetching("Timeout occurred, stopping fetching.")

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 402:
                logger.error("API request limit reached (HTTP 402). Stopping further requests.")
            else:
                logger.error(f"API error: {e.response.status_code if e.response else 'unknown status'}")
            raise StopFetching("HTTP error occurred, stopping fetching.")

        except requests.RequestException as e:
            logger.error(f"Unexpected request error: {e}")
            raise StopFetching("Request error occurred, stopping fetching.")

    def _clean_data(self, data: Union[List[Dict], Dict]) -> List[MyArticle]:
        if isinstance(data, dict):
            data = [data]

        cleaned_articles = []

        for response in data:
            for article in response.get("data", []):
                entities = []
                for ent in article.get("entities", []):
                    entity = Entity(
                        symbol=ent.get("symbol", "no symbol"),
                        name=ent.get("name", "no name"),
                        sentiment=format_sentiment(ent.get("sentiment_score", 0.0)),
                        industry=ent.get("industry")
                    )
                    entities.append(entity)

                cleaned_article = MyArticle(
                    uuid=article.get("uuid", "no uuid"),
                    title=article.get("title", "no title"),
                    description=article.get("description", "no description"),
                    url=article.get("url", "no url"),
                    published_at=article.get("published_at", "no date"),
                    source=article.get("source", "no source"),
                    entities=self._deduplicate_entities(article.get("entities", []))
                )
                cleaned_articles.append(cleaned_article)

        return cleaned_articles

    @staticmethod
    def _deduplicate_entities(raw_entities: List[Dict]) -> List[Entity]:
        entity_map = {}

        for ent in raw_entities:
            name = ent.get("name", "").strip()
            symbol = ent.get("symbol", "")

            if not name:
                continue

            existing = entity_map.get(name)

            is_better = (
                    existing is None or
                    (symbol.isupper() and '.' not in symbol) or
                    ('.US' in symbol and '.US' not in existing.symbol)
            )

            if is_better:
                entity_map[name] = Entity(
                    symbol=symbol,
                    name=name,
                    sentiment=format_sentiment(ent.get("sentiment_score", 0.0)),
                    industry=ent.get("industry")
                )

        return list(entity_map.values())

    def get_data(self, days: int = 1, max_pages: int = 1) -> Tuple[Optional[List[MyArticle]], Optional[List[str]]]:
        all_data = []

        for day_delta in range(days):
            date_str = (datetime.utcnow() - timedelta(days=day_delta)).strftime("%Y-%m-%d") if days > 1 else None

            for page in range(1, max_pages + 1):
                try:
                    data = self._request_data(published_on=date_str, page=page) if date_str else self._request_data(
                        page=page)
                except StopFetching as e:
                    logger.info(f"Stopped fetching data early due to API error: {e}")
                    break
                if not data:
                    break

                articles = data.get("data", [])
                if not articles:
                    break

                all_data.append(data)

                if len(articles) < self.limit:
                    break

            if days == 1:
                break

        if not all_data:
            return None, None

        cleaned_data = self._clean_data(all_data)
        expanded_data = self._expand_description(cleaned_data)

        blacklist = self.article_scraper.get_blacklisted_domains()

        return expanded_data, blacklist

    def _expand_description(self, news_articles: Union[MyArticle, List[MyArticle]]):
        if isinstance(news_articles, MyArticle):
            news_articles = [news_articles]

        expanded_articles = []
        for news_article in tqdm(news_articles, desc="Scraping articles"):
            scraped_data = self.article_scraper.scrape_article(news_article.url)

            summary = scraped_data.get('summary', '').strip()
            if not summary:
                continue

            keywords = ", ".join(scraped_data.get('keywords', []))
            news_article.description = f"{summary}\nKeywords: {keywords}"

            expanded_articles.append(news_article)

        return expanded_articles

def main(symbols: List[str], days: int = 1, save_data: bool = False, max_pages: int = 1):
    gatherer = MarketAuxGatherer(symbols=symbols, save_data=save_data)

    data, blocked = gatherer.get_data(days=days, max_pages=max_pages)

    return data, blocked


if __name__ == "__main__":
    args = parse_args()
    main(symbols=args.symbols,
         days=args.days,
         save_data=args.save_data,
         max_pages=args.max_pages)
