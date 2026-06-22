import asyncio
import os
import re
import sys
from datetime import datetime, timedelta

import yfinance as yf
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from backend.data import ChromaClient, Querier
from backend.rag import BGEReranker
from backend.utils import format_metadata, logger

os.environ["ANONYMIZED_TELEMETRY"] = "False"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

mcp = FastMCP("FinanceWatcherServer")

chroma_client = ChromaClient()
reranker = BGEReranker()
query_service = Querier(chroma_client=chroma_client, reranker=reranker)


def _parse_symbols(symbols: str | None) -> list[str] | None:
    """Accept a comma/space separated symbols string and return a clean list."""
    if not symbols:
        return None
    parts = re.split(r"[,\s]+", symbols.strip())
    cleaned = [p.strip().upper() for p in parts if p.strip()]
    return cleaned or None


def _run_news_query(query: str, symbols: str | None) -> str:
    tickers = _parse_symbols(symbols)
    logger.info(f"Called query_chroma with query: {query!r}, symbols: {tickers}")
    docs = query_service.search(query, tickers=tickers)

    logger.info(f"query_chroma returning {len(docs)} article(s) to the model for query={query!r} symbols={tickers}")

    if not docs:
        return "No relevant news found."

    formatted_docs = []
    for item in docs:
        raw_doc = item.get("document", "").strip()
        cleaned_doc = re.sub(r"^Keywords present:.*(?:\n|$)", "", raw_doc, flags=re.MULTILINE)

        metadata = item.get("metadata", {})
        metadata_str = format_metadata(metadata)

        formatted_docs.append(f"{cleaned_doc}\n{metadata_str}")

    return "\n\n".join(formatted_docs)


@mcp.tool(
    name="get_news_for_company_or_symbol",
    description=(
        "Retrieves curated news articles (documents + metadata) from Chroma DB for the specified "
        "company or stock symbol. Pass the resolved ticker(s) in `symbols` (comma separated) so "
        "results can be filtered to the right company; `query` is the free-text search."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    ),
)
async def query_chroma(query: str, symbols: str = "") -> str:
    """
    Queries the Chroma database for news articles matching the provided query string.

    Args:
        query (str): The search term, which can be a company name or stock symbol.
        symbols (str): Optional comma-separated ticker(s) (e.g. "AAPL" or "AAPL, MSFT")
            used to filter results to the intended company.

    Returns:
        str: A string containing the concatenated news articles. If no relevant
            news is found, returns a default message.
    """
    return await asyncio.to_thread(_run_news_query, query, symbols)


_MAX_PRICE_DAYS = 365


def _fetch_price_sync(symbol: str, days: int) -> dict:
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, _MAX_PRICE_DAYS))

    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")
    logger.info(f"Called fetch_price with symbol: {symbol}, days: {days} ({start_date} → {end_date})")

    # Daily bars for shorter windows keep full granularity; weekly bars for long
    # ranges keep the payload manageable without losing the overall trend.
    interval = "1d" if days <= 90 else "1wk"

    ticker = yf.Ticker(symbol)
    df = ticker.history(interval=interval, start=start_date, end=end_date)

    if df.empty:
        raise ValueError(f"No data found for {symbol} in the last {days} days.")

    df.index = df.index.strftime("%Y-%m-%d")
    df = df[["Open", "High", "Low", "Close", "Volume"]]

    return df.to_dict(orient="index")


@mcp.tool(
    name="fetch_price",
    description=(
        "Fetches historical OHLCV price data for a stock symbol over the most recent `days` days "
        "(from today backwards). Choose `days` from the question's time horizon: ~7 for a week, "
        "~30 for a month, ~90 for a quarter, up to 365 for a year (default 30). Returns a dict "
        "mapping each trading date to its open/high/low/close/volume. IMPORTANT: the data covers "
        "ONLY this recent window — it does not contain 52-week highs/lows, year-to-date returns, "
        "all-time highs, or market capitalization."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    ),
)
async def fetch_price(symbol: str, days: int = 30) -> dict:
    """
    Fetch recent historical price data for a stock.

    Args:
        symbol (str): Stock ticker (e.g., "AAPL").
        days (int): How many days of recent history to fetch, from today
            backwards. Clamped to 1..365. Daily bars up to 90 days, weekly beyond.

    Returns:
        dict:
            Mapping of "YYYY-MM-DD" →
            {"Open": float, "High": float, "Low": float,
             "Close": float, "Volume": int}

    Raises:
        ValueError: If no data is returned for the symbol.
    """
    return await asyncio.to_thread(_fetch_price_sync, symbol, days)


if __name__ == "__main__":
    logger.info("Starting MCP server")
    mcp.run(transport="sse")
