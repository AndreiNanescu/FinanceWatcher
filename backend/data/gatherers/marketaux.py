import argparse
import os
import requests

from .base import DataGatherer

from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
from tqdm import tqdm
from urllib.parse import urlparse

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
    parser.add_argument(
        "--published-after",
        type=str,
        help="Fetch articles published after this date (YYYY-MM-DD)."
    )
    parser.add_argument(
        "--published-before",
        type=str,
        help="Fetch articles published before this date (YYYY-MM-DD)."
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Page number to start fetching from."
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

    def _request_data(self, published_on: Optional[str] = None, published_before: Optional[str] = None,
                      published_after: Optional[str] = None, page: int = 1) -> Optional[dict]:

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

        if published_before:
            try:
                datetime.strptime(published_before, "%Y-%m-%d")
                params['published_before'] = published_before
            except ValueError:
                logger.warning(f"Invalid published_on date format: {published_before}. Expected YYYY-MM-DD.")

        if published_on:
            try:
                datetime.strptime(published_after, "%Y-%m-%d")
                params['published_after'] = published_after
            except ValueError:
                logger.warning(f"Invalid published_on date format: {published_after}. Expected YYYY-MM-DD.")

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

    def _fetch_by_days(self, days: int, max_pages: int, start_page: int) -> List[dict]:
        all_data = []
        for day_delta in range(days):
            date_str = (datetime.utcnow() - timedelta(days=day_delta)).strftime("%Y-%m-%d") if days > 1 else None
            for page in range(start_page, start_page + max_pages):
                try:
                    data = self._request_data(published_on=date_str, page=page) if date_str else self._request_data(
                        page=page)
                except StopFetching as e:
                    logger.info(f"Stopped fetching data early due to API error: {e}")
                    return all_data

                if not data or not data.get("data"):
                    return all_data

                all_data.append(data)
                if len(data.get("data", [])) < self.limit:
                    return all_data

            if days == 1:
                break
        return all_data

    def _fetch_by_date_range(self, published_after: Optional[str], published_before: Optional[str], max_pages: int,
                             start_page: int) -> List[dict]:
        all_data = []
        for page in range(start_page, start_page + max_pages):
            try:
                data = self._request_data(
                    published_after=published_after,
                    published_before=published_before,
                    page=page
                )
            except StopFetching as e:
                logger.info(f"Stopped fetching data early due to API error: {e}")
                return all_data

            if not data or not data.get("data"):
                return all_data

            all_data.append(data)
            if len(data.get("data", [])) < self.limit:
                return all_data
        return all_data

    def get_data(self,days: int = 1,max_pages: int = 1,published_after: Optional[str] = None,
                 published_before: Optional[str] = None, start_page: int = 1) -> Tuple[Optional[List[MyArticle]], Optional[List[str]]]:

        logger.info(
            f"Fetching data with parameters - days: {days}, max_pages: {max_pages}, "
            f"published_after: {published_after}, published_before: {published_before}, start_page: {start_page}"
        )

        if published_after is None and published_before is None:
            raw_data = self._fetch_by_days(days, max_pages, start_page)
        else:
            raw_data = self._fetch_by_date_range(published_after, published_before, max_pages, start_page)

        if not raw_data:
            return None, None

        cleaned_data = self._clean_data(raw_data)
        expanded_data = self._expand_description(cleaned_data)

        blacklist = self.article_scraper.get_blacklisted_domains()
        blacklist_domains = list({urlparse(url).netloc for url in blacklist if urlparse(url).netloc})

        return expanded_data, blacklist_domains

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

def main(symbols: List[str], days: int = 1, save_data: bool = False, max_pages: int = 1,
         published_after: Optional[str] = None, published_before: Optional[str] = None, start_page: int = 1):
    gatherer = MarketAuxGatherer(symbols=symbols, save_data=save_data)

    data, blocked = gatherer.get_data(
        days=days, max_pages=max_pages, published_after=published_after,published_before=published_before, start_page=start_page
    )

    return data, blocked


if __name__ == "__main__":
    args = parse_args()
    main(symbols=args.symbols,
         days=args.days,
         save_data=args.save_data,
         max_pages=args.max_pages,
         published_after=args.published_after,
         published_before=args.published_before,
         start_page=args.start_page,
         )
