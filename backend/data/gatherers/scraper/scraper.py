import time
import random
import logging
import requests

from typing import List
from newspaper import Article as NewsPaperArticle
from requests.exceptions import RequestException
from urllib.parse import urlparse

from .summarizer import ArticleSummarizer
from .robot_guard import RobotGuard

logger = logging.getLogger(__name__)

"""
ArticleScraper class performs web scraping with respect for website rules and ethical considerations.

It uses the RobotGuard class to check robots.txt files and ensures scraping only occurs on allowed URLs.
Additionally, it implements delays between requests and limits retries to avoid overloading target servers.

This design helps maintain compliance with site policies and promotes responsible data collection.
"""


class ArticleScraper(ArticleSummarizer):
    def __init__(
        self,
        max_retries: int = 3,
        delay_range: tuple = (2, 5),
    ):
        super().__init__()
        self.max_retries = max_retries
        self.delay_range = delay_range
        self.last_request_time = {}
        self.blacklisted_domains = set()
        self.guard = RobotGuard()

    def _respect_delay(self, domain: str):
        min_delay, max_delay = self.delay_range
        last_time = self.last_request_time.get(domain, 0)
        elapsed = time.time() - last_time
        wait_time = max(0, random.uniform(min_delay, max_delay) - elapsed)
        if wait_time > 0:
            time.sleep(wait_time)

    def _download_article(self, url: str) -> NewsPaperArticle | None:
        domain = urlparse(url).netloc
        self._respect_delay(domain)

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    timeout=10,
                    allow_redirects=True
                )

                if response.status_code == 403:
                    logger.info(f"Access denied (403) for {url}, skipping.")
                    return None

                response.raise_for_status()

                article = NewsPaperArticle(url)
                article.set_html(response.text)
                article.parse()
                article.nlp()

                self.last_request_time[domain] = time.time()
                return article

            except RequestException as e:
                if attempt == self.max_retries:
                    raise
                time.sleep(random.uniform(*self.delay_range))

    def scrape_article(self, url: str) -> dict:
        domain = urlparse(url).netloc
        if domain in self.blacklisted_domains:
            return {}

        if not self.guard.can_fetch(url):
            logger.info(f"Skipping {url}: Disallowed by robots.txt")
            return {}

        try:
            article = self._download_article(url)
            return self.summarize(article.text)
        except Exception as e:
            self.blacklisted_domains.add(domain)
            logger.warning(f"Scrape failed for {url}: {e}")
            return {}

    def get_blacklisted_domains(self) -> List[str]:
        return list(self.blacklisted_domains)
