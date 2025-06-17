import os
import requests

from abc import ABC, abstractmethod
from datetime import datetime
from dotenv import load_dotenv
from typing import List, Optional
from utils import setup_logger, save_dict_as_json
from pathlib import Path

logger = setup_logger(__name__)
load_dotenv()

MARKETAUX_API_KEY_ENV = "MARKETAUX_API_KEY"
MARKETAUX_BASE_URL_ENV = "MARKETAUX_BASE_URL"


class DataGatherer(ABC):
    def __init__(self, symbols: List[str]):
        if not symbols or not all(isinstance(s, str) for s in symbols):
            raise ValueError("Symbols must be a non-empty list of strings.")
        self.symbols = symbols

    @abstractmethod
    def _save_raw_json(self, data: dict, base_dir: str = "./raw") -> str:
        pass

    @abstractmethod
    def get_data(self) -> Optional[dict]:
        pass


class MarketAuxGatherer(DataGatherer):
    def __init__(self, symbols: List[str], language: str = "en", filter_entities: bool = True, limit: int = 5,):
        super().__init__(symbols)
        self.language = language
        self.filter_entities = filter_entities
        self.limit = limit

    def _save_raw_json(self, data: dict, base_dir="./raw") -> str:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        symbol_str = "_".join(s.replace("/", "-") for s in self.symbols)[:50]
        filename = f"marketaux_{symbol_str}_{timestamp}.json"
        filepath = Path(base_dir) / filename

        save_dict_as_json(data, filepath)
        return str(filepath)

    def get_data(self) -> Optional[dict]:
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
            "limit": self.limit
        }

        try:
            response = requests.get(url=url, params=params)
            response.raise_for_status()
            data = response.json()
            path = self._save_raw_json(data)
            logger.info(f"Saved raw data to {path}")
            logger.info(f"Fetched {len(data.get('data', []))} articles for {self.symbols}")
            return data
        except requests.Timeout:
            logger.error("Request timed out")
            return None
        except requests.HTTPError as e:
            logger.error(f"API error: {e.response.status_code}")
            return None
        except requests.RequestException as e:
            logger.error(f"Unexpected request error: {e}")
            return None
