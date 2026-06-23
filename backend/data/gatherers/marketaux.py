import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests
from rapidfuzz import fuzz
from tqdm import tqdm

from backend.utils import (
    MARKETAUX_API_KEY_ENV,
    MARKETAUX_BASE_URL_ENV,
    Article,
    Entity,
    StopFetching,
    format_sentiment,
    logger,
    normalize_name,
    save_dict_as_json,
)

from .base import DataGatherer
from .scraper import ArticleScraper


class MarketAuxGatherer(DataGatherer):
    def __init__(
        self,
        symbols: list[str],
        save_data: bool = False,
        language: str = "en",
        filter_entities: bool = True,
        limit: int = 3,
    ):
        super().__init__(symbols, save_data)
        self.language = language
        self.filter_entities = filter_entities
        self.limit = limit
        self.article_scraper = ArticleScraper()

        self.blacklist = []
        self.uuids = []
        self.urls = []

        self.stats = {
            "duplicates": 0,
            "blacklisted": 0,
        }

    def set_blacklist(self, blacklist: list[str]) -> None:
        self.blacklist.extend(blacklist)

    def set_uuid(self, uuids: list[str]) -> None:
        self.uuids.extend(uuids)

    def set_urls(self, urls: list[str]) -> None:
        self.urls.extend(urls)

    def _save_raw_json(self, data: dict, base_dir: str | None = None, published_on: str | None = None) -> str:
        if published_on:
            timestamp = published_on.replace("-", "") + "T000000Z"
        else:
            timestamp = datetime.now(UTC).replace(tzinfo=None).strftime("%Y%m%dT%H%M%SZ")

        symbol_str = "_".join(s.replace("/", "-") for s in self.symbols)[:50]
        filename = f"marketaux_{symbol_str}_{timestamp}.json"

        base_dir = base_dir or "raw"
        filepath = Path(base_dir) / filename

        save_dict_as_json(data, filepath)
        return str(filepath)

    def _request_data(
        self,
        published_on: str | None = None,
        published_before: str | None = None,
        published_after: str | None = None,
        page: int = 1,
    ) -> dict | None:

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
                params["published_on"] = published_on
            except ValueError:
                logger.warning(f"Invalid published_on date format: {published_on}. Expected YYYY-MM-DD.")

        if published_before:
            try:
                datetime.strptime(published_before, "%Y-%m-%d")
                params["published_before"] = published_before
            except ValueError:
                logger.warning(f"Invalid published_on date format: {published_before}. Expected YYYY-MM-DD.")

        if published_after:
            try:
                datetime.strptime(published_after, "%Y-%m-%d")
                params["published_after"] = published_after
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
            raise StopFetching("Timeout occurred, stopping fetching.") from None

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 402:
                logger.error("API request limit reached (HTTP 402). Stopping further requests.")
            else:
                logger.error(f"API error: {e.response.status_code if e.response else 'unknown status'}")
            raise StopFetching("HTTP error occurred, stopping fetching.") from e

        except requests.RequestException as e:
            logger.error(f"Unexpected request error: {e}")
            raise StopFetching("Request error occurred, stopping fetching.") from e

    def _clean_data(self, data: list[dict] | dict) -> list[Article]:
        if isinstance(data, dict):
            data = [data]

        cleaned_articles = []

        # Dedup on BOTH uuid and url, seeded from the DB and updated as we accept
        # articles this run. The articles table is unique on both uuid (PK) and
        # url, so a known url under a fresh uuid must be treated as a duplicate —
        # otherwise it gets needlessly re-scraped, silently dropped by SQL's
        # INSERT OR IGNORE, yet still indexed into Chroma (drifting the two stores).
        seen_uuids = set(self.uuids)
        seen_urls = set(self.urls)

        for response in data:
            for article in response.get("data", []):
                entities = []

                uuid = article.get("uuid")
                url = article.get("url")

                if uuid in seen_uuids or url in seen_urls:
                    self.stats["duplicates"] += 1
                    continue

                if (url in self.blacklist) or (urlparse(url).netloc in self.blacklist):
                    self.stats["blacklisted"] += 1
                    continue

                for ent in article.get("entities", []):
                    entity = Entity(
                        symbol=ent.get("symbol", "no symbol"),
                        name=ent.get("name", "no name"),
                        sentiment=format_sentiment(ent.get("sentiment_score", 0.0)),
                        industry=ent.get("industry"),
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
                    keywords="No keywords extracted",
                )
                cleaned_articles.append(cleaned_article)
                seen_uuids.add(uuid)
                seen_urls.add(url)

        return cleaned_articles

    @staticmethod
    def _deduplicate_entities(raw_entities: list[Entity], threshold: int = 60) -> list[Entity]:
        clusters: list[list[Entity]] = []

        for ent in raw_entities:
            matched_cluster = None
            for cluster in clusters:
                if any(
                    fuzz.token_sort_ratio(normalize_name(ent.name), normalize_name(c_ent.name)) >= threshold
                    for c_ent in cluster
                ):
                    matched_cluster = cluster
                    break
            if matched_cluster is not None:
                matched_cluster.append(ent)
            else:
                clusters.append([ent])

        deduped = []
        for cluster in clusters:
            simple_symbols = [e for e in cluster if "." not in e.symbol]
            chosen = simple_symbols[0] if simple_symbols else cluster[0]
            deduped.append(
                Entity(symbol=chosen.symbol, name=chosen.name, sentiment=chosen.sentiment, industry=chosen.industry)
            )

        return deduped

    def _fetch_day(self, date_str: str | None, max_pages: int, start_page: int) -> tuple[list[dict], bool]:
        """Fetch up to max_pages pages for a single day (or the latest articles
        when date_str is None).

        Returns (pages, stop_all) where stop_all signals an API-level stop
        (e.g. quota reached or a failed request) that should halt the whole run,
        not just this day.
        """
        pages: list[dict] = []
        for page in range(start_page, start_page + max_pages):
            try:
                data = (
                    self._request_data(published_on=date_str, page=page)
                    if date_str
                    else self._request_data(page=page)
                )
            except StopFetching as e:
                logger.info(f"Stopped fetching data early due to API error: {e}")
                return pages, True

            if not data:
                return pages, True

            if not data.get("data"):
                break

            pages.append(data)
            if len(data.get("data", [])) < self.limit:
                break

        return pages, False

    @staticmethod
    def _build_day_range(published_after: str | None, published_before: str | None, days: int) -> list[str]:
        """Build the list of YYYY-MM-DD days to fetch for a date-range request.

        - both bounds given  -> every day in [after, before] inclusive.
        - only `before` given -> `days` days ending at (and including) before
          (walking backward — used to enrich the DB with older articles).
        - only `after` given  -> `days` days starting at after (walking forward).
        """
        fmt = "%Y-%m-%d"
        try:
            after_dt = datetime.strptime(published_after, fmt) if published_after else None
            before_dt = datetime.strptime(published_before, fmt) if published_before else None
        except ValueError:
            logger.error("published_after/published_before must be in YYYY-MM-DD format")
            return []

        span = max(days, 1)
        if after_dt and before_dt:
            start, end = after_dt, before_dt
        elif before_dt:
            end = before_dt
            start = before_dt - timedelta(days=span - 1)
        elif after_dt:
            start = after_dt
            end = after_dt + timedelta(days=span - 1)
        else:
            return []

        if start > end:
            start, end = end, start

        out = []
        day = start
        while day <= end:
            out.append(day.strftime(fmt))
            day += timedelta(days=1)
        return out

    def _fetch_by_days(self, days: int, max_pages: int, start_page: int) -> list[dict]:
        all_data = []
        for day_delta in range(days):
            date_str = (
                (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=day_delta)).strftime("%Y-%m-%d")
                if days > 1
                else None
            )
            pages, stop_all = self._fetch_day(date_str, max_pages, start_page)
            all_data.extend(pages)
            if stop_all:
                return all_data
            if days == 1:
                break
        return all_data

    def _fetch_by_date_range(
        self, published_after: str | None, published_before: str | None, max_pages: int, start_page: int, days: int
    ) -> list[dict]:
        all_data = []
        for date_str in self._build_day_range(published_after, published_before, days):
            pages, stop_all = self._fetch_day(date_str, max_pages, start_page)
            all_data.extend(pages)
            if stop_all:
                return all_data
        return all_data

    def get_data(
        self,
        days: int = 1,
        max_pages: int = 1,
        published_after: str | None = None,
        published_before: str | None = None,
        start_page: int = 1,
    ) -> tuple[list[Article] | None, list[str] | None]:

        if published_after is None and published_before is None:
            raw_data = self._fetch_by_days(days, max_pages, start_page)
        else:
            raw_data = self._fetch_by_date_range(published_after, published_before, max_pages, start_page, days)

        if not raw_data:
            return None, None

        cleaned_data = self._clean_data(raw_data)
        expanded_data = self._expand_description(cleaned_data)

        blacklist_url_list = self.article_scraper.get_blacklisted_urls()

        logger.info(
            f"Fetched articles: {len(expanded_data)} new | {self.stats['duplicates']} duplicates, "
            f"blacklisted: {len(blacklist_url_list)} new | {self.stats['blacklisted']} duplicates"
        )

        return expanded_data, blacklist_url_list

    def _expand_description(self, news_articles: Article | list[Article]):
        if isinstance(news_articles, Article):
            news_articles = [news_articles]

        expanded_articles = []
        for news_article in tqdm(news_articles, desc="Scraping articles description"):
            scraped_data = self.article_scraper.scrape_article(news_article.url)

            summary = scraped_data.get("summary", "").strip()
            if not summary:
                continue

            news_article.description = scraped_data["summary"]
            news_article.keywords = ", ".join(scraped_data["keywords"])

            expanded_articles.append(news_article)

        return expanded_articles
