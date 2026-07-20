import asyncio
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import cast

import yfinance as yf
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from backend.config import config
from backend.data import ChromaClient, Querier
from backend.rag import BGEReranker
from backend.utils import NO_RELEVANT_NEWS_MESSAGE, format_metadata, logger, strip_keywords_line

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

def _run_news_query(query: str, symbols: str | None, rerank_query: str | None, top_n: int) -> str:
    tickers = _parse_symbols(symbols)
    try:
        top_n = max(1, min(int(top_n), config.retrieval.max_rerank_candidates))
    except (TypeError, ValueError):
        top_n = 5
    logger.info(
        f"Called query_chroma with query: {query!r}, rerank_query: {rerank_query!r}, symbols: {tickers}, top_n: {top_n}"
    )
    docs = cast(
        list[dict], query_service.search(query, tickers=tickers, rerank_query=rerank_query or None, top_n_rerank=top_n)
    )

    logger.info(f"query_chroma returning {len(docs)} article(s) to the model for query={query!r} symbols={tickers}")

    if not docs:
        return NO_RELEVANT_NEWS_MESSAGE

    formatted_docs = []
    for item in docs:
        raw_doc = item.get("document", "").strip()
        cleaned_doc = strip_keywords_line(raw_doc)

        metadata = item.get("metadata", {})
        metadata_str = format_metadata(metadata)

        formatted_docs.append(f"{cleaned_doc}\n{metadata_str}")

    return "\n\n".join(formatted_docs)


@mcp.tool(
    name="get_news_for_company_or_symbol",
    description=(
        "Retrieves curated news articles (documents + metadata) from Chroma DB for the specified "
        "company or stock symbol. Pass the resolved ticker(s) in `symbols` (comma separated) so "
        "results can be filtered to the right company; `query` is the descriptive free-text search "
        "used for retrieval, and `rerank_query` is an optional short focused query (e.g. the "
        "company name and ticker) used to re-rank the retrieved candidates. `top_n` is how many "
        "articles to return (more for broad questions, fewer for narrow ones; default 5, max 15)."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    ),
)
async def query_chroma(query: str, symbols: str = "", rerank_query: str = "", top_n: int = 5) -> str:
    """
    Queries the Chroma database for news articles matching the provided query string.

    Args:
        query (str): Descriptive free-text search used for embedding retrieval.
        symbols (str): Optional comma-separated ticker(s) (e.g. "AAPL" or "AAPL, MSFT")
            used to filter results to the intended company.
        rerank_query (str): Optional short, focused query used to re-rank the
            retrieved candidates. Falls back to `query` when empty.
        top_n (int): How many top articles to return (clamped to 1..15).

    Returns:
        str: A string containing the concatenated news articles. If no relevant
            news is found, returns a default message.
    """
    return await asyncio.to_thread(_run_news_query, query, symbols, rerank_query, top_n)


def _fetch_price_sync(symbol: str, days: int) -> dict:
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, config.retrieval.max_top_n))

    end_dt = datetime.now(UTC).replace(tzinfo=None)
    start_dt = end_dt - timedelta(days=days)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")
    logger.info(f"Called fetch_price with symbol: {symbol}, days: {days} ({start_date} → {end_date})")

    interval = "1d" if days <= 90 else "1wk"

    ticker = yf.Ticker(symbol)
    df = ticker.history(interval=interval, start=start_date, end=end_date)

    if df.empty:
        raise ValueError(f"No data found for {symbol} in the last {days} days.")

    df.index = df.index.strftime("%Y-%m-%d")
    df = df[["Open", "High", "Low", "Close", "Volume"]]

    return cast(dict, df.to_dict(orient="index"))


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
