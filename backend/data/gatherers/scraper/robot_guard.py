import requests

import urllib.robotparser
from urllib.parse import urlparse
from backend.utils import logger


class RobotGuard:
    def __init__(self, user_agent: str = "*"):
        self.user_agent = user_agent
        self.parsers = {}
        self.blocked_sites = set()

    def _get_parser(self, base_url: str):
        if base_url in self.parsers:
            return self.parsers[base_url]

        robots_url = f"{base_url}/robots.txt"
        try:
            response = requests.get(robots_url, timeout=5)
            response.raise_for_status()
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(response.text.splitlines())
            self.parsers[base_url] = rp
            return rp
        except Exception as e:
            logger.warning(f"Failed to fetch robots.txt from {robots_url}: {e}")
            return None

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._get_parser(base_url)

        if rp is None:
            return True

        allowed = rp.can_fetch(self.user_agent, url)
        if not allowed:
            self.blocked_sites.add(parsed.netloc)
            logger.info(f"Scraping blocked for {url}")
        return allowed

    def get_blocked_sites(self):
        return list(self.blocked_sites)