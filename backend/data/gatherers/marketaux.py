import os
import requests

from .base import DataGatherer

from datetime import datetime, timedelta
from pathlib import Path
from rapidfuzz import fuzz
from typing import Dict, List, Optional, Union, Tuple
from tqdm import tqdm
from urllib.parse import urlparse

from backend.utils import (logger, save_dict_as_json, StopFetching, MARKETAUX_API_KEY_ENV, MARKETAUX_BASE_URL_ENV,
                           Entity, format_sentiment, normalize_name, Article)

from .scraper import ArticleScraper


class MarketAuxGatherer(DataGatherer):
    def __init__(self, symbols: List[str], save_data: bool = False, language: str = "en", filter_entities: bool = True,
                 limit: int = 3):
        super().__init__(symbols, save_data)
        self.language = language
        self.filter_entities = filter_entities
        self.limit = limit
        self.article_scraper = ArticleScraper()

        self.blacklist = []
        self.uuids = []

        self.stats = {
            'duplicates': 0,
            'blacklisted': 0,
        }

    def set_blacklist(self,  blacklist: List[str]) -> None:
        self.blacklist.extend(blacklist)

    def set_uuid(self, uuids: List[str]) -> None:
        self.uuids.extend(uuids)

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

        if published_after:
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

    def _clean_data(self, data: Union[List[Dict], Dict]) -> List[Article]:
        if isinstance(data, dict):
            data = [data]

        cleaned_articles = []

        for response in data:
            for article in response.get("data", []):
                entities = []

                if article['uuid'] in self.uuids:
                    self.stats['duplicates'] += 1
                    continue

                if (article['url'] in self.blacklist) or (urlparse(article['url']).netloc in self.blacklist):
                    self.stats['blacklisted'] += 1
                    continue

                for ent in article.get("entities", []):
                    entity = Entity(
                        symbol=ent.get("symbol", "no symbol"),
                        name=ent.get("name", "no name"),
                        sentiment=format_sentiment(ent.get("sentiment_score", 0.0)),
                        industry=ent.get("industry")
                    )
                    entities.append(entity)

                cleaned_article = Article(
                    uuid=article.get("uuid", "no uuid"),
                    title=article.get("title", "no title"),
                    description=article.get("description", "no description"),
                    url=article.get("url", "no url"),
                    published_at=article.get("published_at", "no date"),
                    fetched_on=datetime.now().strftime("%B %d, %Y at %I:%M %p"),
                    entities=self._deduplicate_entities(entities),
                    keywords = "No keywords extracted"
                )
                cleaned_articles.append(cleaned_article)

        return cleaned_articles

    @staticmethod
    def _deduplicate_entities(raw_entities: List[Entity], threshold: int = 60) -> List[Entity]:
        clusters: List[List[Entity]] = []

        for ent in raw_entities:
            matched_cluster = None
            for cluster in clusters:
                if any(fuzz.token_sort_ratio(normalize_name(ent.name), normalize_name(c_ent.name)) >= threshold for c_ent in
                       cluster):
                    matched_cluster = cluster
                    break
            if matched_cluster is not None:
                matched_cluster.append(ent)
            else:
                clusters.append([ent])

        deduped = []
        for cluster in clusters:
            simple_symbols = [e for e in cluster if '.' not in e.symbol]
            chosen = simple_symbols[0] if simple_symbols else cluster[0]
            deduped.append(Entity(
                symbol=chosen.symbol,
                name=chosen.name,
                sentiment=chosen.sentiment,
                industry=chosen.industry
            ))

        return deduped

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
                 published_before: Optional[str] = None, start_page: int = 1) -> Tuple[Optional[List[Article]], Optional[List[str]]]:

        if published_after is None and published_before is None:
            raw_data = self._fetch_by_days(days, max_pages, start_page)
        else:
            raw_data = self._fetch_by_date_range(published_after, published_before, max_pages, start_page)

        if not raw_data:
            return None, None

        cleaned_data = self._clean_data(raw_data)
        expanded_data = self._expand_description(cleaned_data)

        blacklist_url_list = self.article_scraper.get_blacklisted_urls()

        logger.info(f"Fetched articles: {len(expanded_data)} new | {self.stats['duplicates']} duplicates, "
                    f"blacklisted: {len(blacklist_url_list)} new | {self.stats['blacklisted']} duplicates")

        return expanded_data, blacklist_url_list

    def _expand_description(self, news_articles: Union[Article, List[Article]]):
        if isinstance(news_articles, Article):
            news_articles = [news_articles]

        expanded_articles = []
        for news_article in tqdm(news_articles, desc="Scraping articles description"):
            scraped_data = self.article_scraper.scrape_article(news_article.url)

            summary = scraped_data.get('summary', '').strip()
            if not summary:
                continue

            news_article.description = scraped_data['summary']
            news_article.keywords = ", ".join(scraped_data['keywords'])

            expanded_articles.append(news_article)

        return expanded_articles