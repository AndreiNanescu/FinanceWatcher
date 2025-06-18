import argparse
import os
import requests

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import Dict, List, Optional
from utils import setup_logger, save_dict_as_json
from pathlib import Path

logger = setup_logger(__name__)
load_dotenv()

MARKETAUX_API_KEY_ENV = "MARKETAUX_API_KEY"
MARKETAUX_BASE_URL_ENV = "MARKETAUX_BASE_URL"


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
        "--save_data",
        type=bool,
        default=False,
        help="Wherever to save the raw data or not."
    )
    return parser.parse_args()


class DataGatherer(ABC):
    def __init__(self, symbols: List[str], save_data: bool = False):
        if not symbols or not all(isinstance(s, str) for s in symbols):
            raise ValueError("Symbols must be a non-empty list of strings.")
        self.symbols = symbols
        self.save_data = save_data

    @abstractmethod
    def _save_raw_json(self, data: dict, base_dir: str = "./raw") -> str:
        pass

    @abstractmethod
    def get_data(self) -> Optional[dict]:
        pass


class MarketAuxGatherer(DataGatherer):
    def __init__(self, symbols: List[str], save_data: bool = False, language: str = "en", filter_entities: bool = True, limit: int = 3):
        super().__init__(symbols, save_data)
        self.language = language
        self.filter_entities = filter_entities
        self.limit = limit

    def _save_raw_json(self, data: dict, base_dir: Optional[str] = None, published_on: Optional[str] = None) -> str:
        if published_on:
            timestamp = published_on.replace("-", "") + "T000000Z"
        else:
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

        symbol_str = "_".join(s.replace("/", "-") for s in self.symbols)[:50]
        filename = f"marketaux_{symbol_str}_{timestamp}.json"

        base_dir = base_dir or "data/raw"
        filepath = Path(base_dir) / filename

        save_dict_as_json(data, filepath)
        return str(filepath)

    def _request_data(self, published_on: Optional[str] = None) -> Optional[dict]:
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
                path = self._save_raw_json(data, published_on=published_on)
                logger.debug(f"Saved raw data to {path}")
            else:
                logger.debug(f"No articles found for {self.symbols} on {published_on or 'today'}, skipping save.")

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

    def get_data(self) -> Optional[Dict]:
        return self._request_data()

    def get_historical_data(self, days: int) -> List[Dict]:
        all_data = []
        for day_delta in range(days):
            date_str = (datetime.utcnow() - timedelta(days=day_delta)).strftime("%Y-%m-%d")
            data = self._request_data(published_on=date_str)
            if data:
                all_data.append(data)
        return all_data

def main(symbols: List[str], days: int = 1, save_data: bool = False):
    gatherer = MarketAuxGatherer(symbols=symbols, save_data=save_data)

    if days == 1:
        data = gatherer.get_data()
        count = len(data.get('data', [])) if data else 0
        logger.info(f"Fetched {count} articles for symbols {symbols}")
    else:
        all_data = gatherer.get_historical_data(days=days)
        total_articles = sum(len(batch.get('data', [])) for batch in all_data if batch)
        logger.info(
            f"Fetched historical data for {days} days, total batches: {len(all_data)}, total articles: {total_articles}")


if __name__ == "__main__":
    args = parse_args()
    main(symbols=args.symbols,
         days=args.days,
         save_data=args.save_data)