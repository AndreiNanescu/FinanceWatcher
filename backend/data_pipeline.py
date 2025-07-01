import argparse

from dotenv import load_dotenv
from typing import List, Optional

from backend.data import MarketNewsDB
from backend.data.gatherers import MarketAuxGatherer
from .utils import setup_logger

logger = setup_logger(__name__)
load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(description="Run data pipeline")
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


class DataPipeline:
    def __init__(self, days: int = 1, max_pages: int = 1,
                 published_after: Optional[str] = None, published_before: Optional[str] = None, start_page: int = 1,
                 gatherer: Optional[MarketAuxGatherer] = None, db: Optional[MarketNewsDB] = None):

        self.days = days
        self.published_after = published_after
        self.published_before = published_before
        self.start_page = start_page
        self.days = days
        self.max_pages = max_pages

        self.gatherer = gatherer
        self.db = db

        self._sync_gatherer_to_db()

    def _get_data(self):
        return self.gatherer.get_data(days=self.days, max_pages=self.max_pages, start_page=self.start_page,
                                      published_after=self.published_after, published_before=self.published_before)

    def _sync_gatherer_to_db(self):
        blacklist = self.db.get_blacklist()
        uuids = self.db.get_uuids()

        self.gatherer.set_blacklist(blacklist)
        self.gatherer.set_uuid(uuids)


    def process(self) -> None:
        articles, blacklist = self._get_data()
        
        self.db.add(articles)
        self.db.add_to_blacklist(blacklist)

        self.db.close()


def main(symbols: List[str], days: int = 1, save_data: bool = False, max_pages: int = 1,
         published_after: Optional[str] = None, published_before: Optional[str] = None, start_page: int = 1,
         gatherer: Optional[MarketAuxGatherer] = None, db: Optional[MarketNewsDB] = None):

    logger.info(f"Starting processing for symbols: {symbols} over {days} days, with {max_pages} pages per day,"
                f"starting from page {start_page}")

    try:
        gatherer = gatherer if gatherer is not None else MarketAuxGatherer(symbols=symbols, save_data=save_data)
        db = db if db is not None else MarketNewsDB()

        pipeline = DataPipeline(gatherer=gatherer, db=db, days=days, max_pages=max_pages, published_after=published_after,
                                published_before=published_before)
        pipeline.process()

    except Exception as e:
        logger.error(f"Pipeline failed: {e} (type: {type(e)})")
        raise


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