import json
import logging
import os
import random
import time
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from newspaper import Article as NewsPaperArticle
from playwright.sync_api import BrowserContext, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from requests.exceptions import RequestException

from .summarizer import ArticleSummarizer

logger = logging.getLogger(__name__)

# If newspaper3k extracts at least this many characters we trust it; below this
# (e.g. CNBC, where it only grabs a blurb) we also try the domain-specific
# BeautifulSoup extraction and keep whichever is longer.
_MIN_NEWSPAPER_LEN = 500

_BOT_PAGE_STRONG_MARKERS = [
    "misidentified as bots",
    "misidentified as a bot",
    "detected unusual activity",
    "verify you are human",
    "verifying you are human",
    "are you a robot",
    "pardon our interruption",
    "access to this page has been denied",
    "checking your browser before",
    "performance & security by cloudflare",
    "press & hold to confirm you are",
]
_BOT_PAGE_WEAK_MARKERS = [
    "enable javascript and cookies",
    "enable cookies and javascript",
    "please enable javascript",
    "complete the captcha",
]
_BOT_PAGE_WEAK_MAX_LEN = 3000


def looks_like_bot_page(text: str | None) -> bool:
    """True when extracted 'article text' is actually a bot-detection or
    consent-challenge page rather than editorial content."""
    if not text:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _BOT_PAGE_STRONG_MARKERS):
        return True
    if len(text) <= _BOT_PAGE_WEAK_MAX_LEN and any(marker in lowered for marker in _BOT_PAGE_WEAK_MARKERS):
        return True
    return False


class ArticleScraper(ArticleSummarizer):
    def __init__(
        self,
        max_retries: int = 3,
        delay_range: tuple = (2, 5),
        storage_state_path: str = "cookies.json",
        headless: bool = True,
    ):
        super().__init__()
        self.max_retries = max_retries
        self.delay_range = delay_range
        self.last_request_time: dict[str, float] = {}
        self.blacklisted_urls: list[str] = []
        self.ua = UserAgent()
        self.storage_state_path = storage_state_path
        self.headless = headless

        # Initialize storage state file if it doesn't exist
        if not os.path.exists(self.storage_state_path):
            with open(self.storage_state_path, "w") as f:
                json.dump({"cookies": [], "origins": []}, f)

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self._create_context()

    def _create_context(self, use_storage: bool = True) -> BrowserContext:
        """Create a new browser context with random settings"""
        # Randomize viewport size for each context
        viewport_width = random.randint(1200, 1920)
        viewport_height = random.randint(800, 1080)

        # Random chance to use fresh session vs persisted cookies
        use_storage_state = use_storage and random.random() > 0.3

        context = self.browser.new_context(
            user_agent=self.ua.random,
            java_script_enabled=True,
            viewport={"width": viewport_width, "height": viewport_height},
            locale="en-US",
            storage_state=self.storage_state_path if use_storage_state else None,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        return context

    def _get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://www.google.com/",
            "DNT": "1",
        }

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
                response = requests.get(url, headers=self._get_headers(), timeout=10, allow_redirects=True)

                if response.status_code == 403:
                    raise RequestException("Access denied")

                response.raise_for_status()

                article = NewsPaperArticle(url)
                article.set_html(response.text)
                article.parse()

                self.last_request_time[domain] = time.time()
                return article

            except RequestException:
                if attempt == self.max_retries:
                    raise
                time.sleep(random.uniform(*self.delay_range))

        return None

    def _stealth_scrape(self, url: str) -> tuple[str | None, str | None]:
        """Scrape a webpage using Playwright with stealth techniques.

        Returns (text, raw_html). raw_html may be present even when text
        extraction failed — the archived HTML lets extraction be re-run later
        without the link still being alive.
        """
        context = None
        page = None

        try:
            # Create fresh context with random settings
            context = self._create_context(use_storage=True)
            page = context.new_page()

            # Add random delays between actions
            def random_delay(min_ms=1000, max_ms=3000):
                page.wait_for_timeout(random.randint(min_ms, max_ms))

            # Randomize initial mouse position and movement
            start_x, start_y = random.randint(100, 300), random.randint(100, 300)
            page.mouse.move(start_x, start_y)

            # Ad/tracker/live-quote-heavy sites like Yahoo Finance never reach
            # "networkidle", which caused 30s goto timeouts that aborted the whole
            # scrape. Wait only for the DOM and rely on the selector waits below
            # for the real content. If goto still times out, keep going — the DOM
            # is usually already usable.
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                logger.debug(f"goto timed out for {url}; continuing with partial DOM")

            # Initial random delay after page load
            random_delay(1500, 4000)

            # Human-like scrolling pattern
            def human_scroll():
                scroll_pixels = random.randint(300, 1000)
                scroll_direction = 1 if random.random() > 0.2 else -1  # 80% chance to scroll down
                page.mouse.wheel(0, scroll_pixels * scroll_direction)
                random_delay(500, 2500)

            # Enhanced consent frameworks handling
            CONSENT_SELECTORS = [
                # Yahoo / guce.yahoo.com EU consent ("Accept all") — Yahoo Finance
                # redirects here before serving article content.
                ("button[name='agree']", "click"),
                ("button.btn.primary.agree", "click"),
                ("form[action*='consent'] button[type='submit']", "click"),
                ("button:has-text('Accept')", "click"),
                ("button:has-text('I Accept')", "click"),
                ("button:has-text('Agree')", "click"),
                ("button:has-text('Consent')", "click"),
                ("button:has-text('Continue')", "click"),
                ("button:has-text('Accept All')", "click"),
                ("button:has-text('Allow All')", "click"),
                ("#onetrust-accept-btn-handler", "click"),
                ("#onetrust-consent-sdk .onetrust-close-btn-handler", "click"),
                ("#cmpbntyestxt", "click"),  # Cookiebot accept
                ("#didomi-notice-agree-button", "click"),
                ("#truste-consent-button", "click"),
                ("#gdpr-consent-notice .accept", "click"),
                ("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", "click"),
                ("#consent-page .accept", "click"),
                ("button.js-cookie-notice-accept", "click"),
                ("button.cookie-accept", "click"),
                ("a.cookie-policy-accept", "click"),
                (".cookie-consent .accept-btn", "click"),
                (".privacy-policy .agree", "click"),
                ("[data-testid='consent-accept']", "click"),
            ]

            # Handle consent popups
            for selector, action in CONSENT_SELECTORS:
                try:
                    element = page.locator(selector).first
                    if element.is_visible():
                        if action == "click":
                            element.click()
                        random_delay()
                        break
                except Exception:
                    continue

            # Accepting consent (e.g. Yahoo's guce redirect) often navigates back
            # to the real article — wait for that new DOM before extracting.
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass

            # Domain-specific handling with improved selectors
            domain_handlers: dict[str, dict[str, Any]] = {
                "finance.yahoo.com": {
                    "selectors": [
                        "div.caas-body",
                        "div.atoms-wrapper",
                        "article.caas-content",
                        "article",
                        "section[data-testid='article']",
                        "main",
                    ],
                    "pre_actions": [
                        lambda: (
                            page.locator('button:has-text("Show More")').click(timeout=2000)
                            if page.locator('button:has-text("Show More")').is_visible()
                            else None
                        ),
                        lambda: [human_scroll() for _ in range(3)],
                    ],
                },
                "zacks.com": {
                    "selectors": ["article", "div.caas-body", "section[data-testid='article']", "main"],
                    "pre_actions": [lambda: [human_scroll() for _ in range(2)]],
                },
                "gurufocus.com": {
                    "selectors": ["div.article-container", "main", "div[class*='content']", "body"],
                    "pre_actions": [lambda: [human_scroll() for _ in range(2)]],
                },
                "investing.com": {
                    "selectors": [
                        "div.articlePage",
                        "div#articleContent",
                        "div.textDiv",
                        "div.WYSIWYG",
                        "section.articleSection",
                        "main",
                        "body",
                    ],
                    "pre_actions": [
                        lambda: (
                            page.locator('button:has-text("Read More")').click(timeout=2000)
                            if page.locator('button:has-text("Read More")').is_visible()
                            else None
                        ),
                        lambda: [human_scroll() for _ in range(2)],
                    ],
                },
                "livemint.com": {
                    "selectors": ["div.article-wrap", "div.articleBody", "article", "main", "body"],
                    "pre_actions": [lambda: [human_scroll() for _ in range(2)]],
                },
                "marketwatch.com": {
                    "selectors": ["div.article__content", "article", "main", "body"],
                    "pre_actions": [lambda: [human_scroll() for _ in range(3)]],
                },
                "www.cnbc.com": {
                    "selectors": [
                        "div.ArticleBody-articleBody",
                        "[data-module='ArticleBody']",
                        "div.PageBuilder-article",
                        "div.RenderKeyPoints-list",
                        "article",
                        "main",
                    ],
                    "pre_actions": [lambda: [human_scroll() for _ in range(3)]],
                },
                "bloomberg.com": {
                    "selectors": ["article", "div.article-body__content", "main", "body"],
                    "pre_actions": [lambda: [human_scroll() for _ in range(3)]],
                },
                "reuters.com": {
                    "selectors": ["article", "div.article-body", "main", "body"],
                    "pre_actions": [lambda: [human_scroll() for _ in range(2)]],
                },
            }

            # Get domain-specific handler or use default
            domain = urlparse(url).netloc.lower()
            handler = domain_handlers.get(
                domain,
                {
                    "selectors": ["article", "main", "div[class*='post']", "div[class*='content']", "body"],
                    "pre_actions": [lambda: human_scroll()],
                },
            )

            # Execute pre-actions with error handling
            for action in handler.get("pre_actions", []):
                try:
                    action()
                    random_delay(500, 1500)
                except Exception:
                    continue

            # Try multiple selectors with Playwright's built-in waiting
            html = None
            for selector in handler.get("selectors", ["body"]):
                try:
                    # Use state="attached" first, then fallback to "visible"
                    page.wait_for_selector(selector, timeout=5000, state="attached")
                    html = page.content()
                    if html and len(html) > 1000:  # Ensure we got meaningful content
                        break
                except Exception:
                    try:
                        page.wait_for_selector(selector, timeout=3000, state="visible")
                        html = page.content()
                        if html and len(html) > 1000:
                            break
                    except Exception:
                        continue

            # Save cookies occasionally
            if random.random() > 0.5:  # 50% chance to save updated cookies
                try:
                    context.storage_state(path=self.storage_state_path)
                except Exception:
                    pass

            # Close the page and context
            if page:
                page.close()
            if context:
                context.close()

            if not html or len(html) < 500:
                logger.warning(f"Got minimal or no content from {url}")
                return None, None

            # Parse with newspaper3k
            article = NewsPaperArticle(url)
            article.set_html(html)
            try:
                article.parse()
                np_text = (article.text or "").strip()
            except Exception as e:
                logger.debug(f"Newspaper parsing failed: {e}")
                np_text = ""

            # Trust newspaper3k only when it found a substantial article; this
            # keeps behavior identical for sites it already handles well.
            if len(np_text) >= _MIN_NEWSPAPER_LEN:
                return np_text, html

            # Otherwise also try domain-specific BeautifulSoup extraction and keep
            # whichever result is longer (rescues sites like CNBC where
            # newspaper3k only returns a short blurb).
            bs_text = ""
            try:
                soup = BeautifulSoup(html, "html.parser")

                domain_selectors = {
                    "finance.yahoo.com": "div.caas-body, div.atoms-wrapper, article.caas-content, article",
                    "gurufocus.com": "div.article-container, div.gf-article-content, div.content-wrapper",
                    "investing.com": "div.articlePage, div#articleContent, div.textDiv, div.WYSIWYG, section.articleSection",  # noqa: E501
                    "livemint.com": "div.article-wrap, div.articleBody, article, main",
                    "zacks.com": "article, div.caas-body, section[data-testid='article'], main",
                    "marketwatch.com": "div.article__content, article, main",
                    "bloomberg.com": "article, div.article-body__content, main",
                    "reuters.com": "article, div.article-body, main",
                    "www.cnbc.com": (
                        "div.ArticleBody-articleBody, [data-module='ArticleBody'], "
                        "div.PageBuilder-article, article"
                    ),
                }

                selector = domain_selectors.get(domain, "article, main, div[class*='post'], div[class*='content']")
                tags = soup.select(selector)

                if not tags:
                    # Last resort: get all text from body
                    tags = soup.select("body")

                bs_text = "\n\n".join(tag.get_text(separator=" ", strip=True) for tag in tags).strip()

            except Exception as e:
                logger.warning(f"BeautifulSoup fallback failed for {url}: {e}")
                bs_text = ""

            candidates = [t for t in (np_text, bs_text) if t]
            if not candidates:
                return None, html
            return max(candidates, key=len), html

        except Exception as e:
            logger.warning(f"Stealth scrape failed for {url}: {str(e)}", exc_info=True)
            # Ensure cleanup happens even on error
            try:
                if page:
                    page.close()
                if context:
                    context.close()
            except Exception:
                pass
            return None, None

    def scrape_article(self, url: str) -> dict:
        """Scrape and summarize an article from the given URL"""
        if url in self.blacklisted_urls:
            logger.info(f"URL {url} is blacklisted, skipping")
            return {}

        try:
            # Try regular download first
            article = self._download_article(url)

            if article and article.text and looks_like_bot_page(article.text):
                logger.info(f"Regular download of {url} returned a bot-challenge page; escalating to stealth")
                article = None

            if article and article.text and article.text.strip():
                summary = self.summarize(article.text)
                if summary.get("summary", "").strip():
                    # full_text is the exact text the summary was derived from —
                    # stored as source data so chunking/summarization can be
                    # re-run after the link dies.
                    summary["full_text"] = article.text
                    summary["raw_html"] = article.html
                    return summary
                else:
                    logger.warning(f"For url: {url}, the summary was empty from regular scrape")

            # If regular download fails or returns empty content, use stealth scrape
            logger.info(f"Using stealth scrape for {url}")
            stealth_article, stealth_html = self._stealth_scrape(url)

            if not stealth_article or not stealth_article.strip():
                logger.warning(f"Couldn't scrape {url} with stealth mode")
                self.blacklisted_urls.append(url)
                return {}

            if looks_like_bot_page(stealth_article):
                # Deliberately NOT blacklisted: bot-blocks are transient (new
                # fingerprint next run may pass), and the article never reaches
                # the DB, so the next pipeline run retries it as new.
                logger.warning(f"Stealth scrape of {url} also returned a bot-challenge page; skipping article")
                return {}

            summary = self.summarize(stealth_article)

            if not summary.get("summary", "").strip():
                logger.warning(f"For url: {url}, the summary was empty from stealth scrape")
                self.blacklisted_urls.append(url)
                return {}

            summary["full_text"] = stealth_article
            summary["raw_html"] = stealth_html
            return summary

        except Exception as e:
            logger.warning(f"Scrape failed for {url}: {e}")
            self.blacklisted_urls.append(url)
            return {}

    def fetch_article_text(self, url: str) -> tuple[str | None, str | None]:
        """Fetch and extract an article's full text WITHOUT summarizing.

        Backfill entry point. Returns (text, raw_html); either may be None.
        Mirrors scrape_article's escalation (regular download, stealth
        fallback when the regular text looks like a blurb) but never touches
        the blacklist — a dead link during backfill is recorded in the DB
        status, not treated as a scraping ban.
        """
        try:
            article = self._download_article(url)
        except Exception as e:
            logger.debug(f"Regular download failed for {url}: {e}")
            article = None

        text = (article.text or "").strip() if article and article.text else ""
        html = article.html if article else None
        if looks_like_bot_page(text):
            logger.info(f"Regular download of {url} returned a bot-challenge page; trying stealth")
            text, html = "", None

        if len(text) >= _MIN_NEWSPAPER_LEN:
            return text, html

        stealth_text, stealth_html = self._stealth_scrape(url)
        stealth_text = (stealth_text or "").strip()
        if looks_like_bot_page(stealth_text):
            logger.warning(f"Stealth fetch of {url} also returned a bot-challenge page; treating as failed")
            stealth_text, stealth_html = "", None

        # Keep whichever extraction recovered more content.
        candidates = [t for t in (text, stealth_text) if t]
        if not candidates:
            return None, stealth_html or html
        best = max(candidates, key=len)
        best_html = stealth_html if best == stealth_text else html
        return best, best_html or stealth_html or html

    def get_blacklisted_urls(self) -> list[str]:
        """Get list of blacklisted URLs"""
        return self.blacklisted_urls

    def clear_blacklist(self):
        """Clear the blacklist"""
        self.blacklisted_urls = []

    def clear_cookies(self):
        """Clear the cookie storage file"""
        try:
            if os.path.exists(self.storage_state_path):
                os.remove(self.storage_state_path)
                # Recreate empty file
                with open(self.storage_state_path, "w") as f:
                    json.dump({"cookies": [], "origins": []}, f)
                logger.info(f"Cleared cookies from {self.storage_state_path}")
        except Exception as e:
            logger.warning(f"Failed to clear cookies: {e}")

    def close(self):
        """Clean up resources"""
        try:
            # Try to save final cookie state
            if hasattr(self, "context") and self.context:
                try:
                    self.context.storage_state(path=self.storage_state_path)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if hasattr(self, "context") and self.context:
                self.context.close()
        except Exception:
            pass

        try:
            if hasattr(self, "browser") and self.browser:
                self.browser.close()
        except Exception:
            pass

        try:
            if hasattr(self, "playwright") and self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
