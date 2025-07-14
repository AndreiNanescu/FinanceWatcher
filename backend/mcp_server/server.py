import os
import re
import sys
import yfinance as yf
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from backend.data import ChromaClient, Querier
from backend.rag import BGEReranker
from backend.utils import logger, format_metadata

os.environ["ANONYMIZED_TELEMETRY"] = "False"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

mcp = FastMCP('FinanceWatcherServer')

chroma_client = ChromaClient()
reranker = BGEReranker()
query_service = Querier(chroma_client=chroma_client, reranker=reranker)

@mcp.tool(
    name="get_news_for_company_or_symbol",
    description="Retrieves curated news articles (documents + metadata) from Chroma DB for the specified company or stock symbol.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def query_chroma(query: str) -> str:
    """
    Queries the Chroma database for news articles matching the provided query string.

    Args:
        query (str): The search term, which can be a company name or stock symbol.

    Returns:
        str: A string containing the concatenated news articles. If no relevant news is found, returns a default message.
    """
    logger.info(f"Called query_chroma with query: {query}")
    docs = query_service.search(query)

    if not docs:
        return "No relevant news found."

    formatted_docs = []
    for item in docs:
        raw_doc = item.get("document", "").strip()
        cleaned_doc = re.sub(r'^Keywords present:.*(?:\n|$)', '', raw_doc, flags=re.MULTILINE)

        metadata = item.get("metadata", {})
        metadata_str = format_metadata(metadata)

        formatted_docs.append(f"{cleaned_doc}\n{metadata_str}")

    return "\n\n".join(formatted_docs)

@mcp.tool(
    name="fetch_price",
    description=(
        "Fetches historical OHLCV price data for a given stock symbol over a specified date range and interval. "
        "Returns a JSON-like dict mapping dates to price details. DO NOT exceed 90 days when specifying date ranges"
    ),
    annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        )
)
def fetch_price(symbol: str, start_date: str, end_date: str) -> dict:
    """
    Fetch historical price data for a stock.

    Args:
        symbol (str): Stock ticker (e.g., "AAPL").
        start_date (str): Inclusive start date in YYYY-MM-DD.
        end_date (str): Exclusive end date in YYYY-MM-DD.

    Returns:
        dict:
            Mapping of "YYYY-MM-DD" →
            {"Open": float, "High": float, "Low": float,
             "Close": float, "Volume": int}

    Raises:
        ValueError: If no data returned or invalid date range.
    """
    logger.info(f'Called fetch_price with symbol: {symbol}, start_date: {start_date}, end_date: {end_date}')
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("start_date and end_date must be in YYYY-MM-DD format")

    if (end_dt - start_dt).days > 90:
        logger.info("Date range exceeded 90 days; clipping to most recent 90 days.")
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(days=90)

        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")

    interval = "1d" if (end_dt - start_dt).days <= 30 else "1mo"

    ticker = yf.Ticker(symbol)
    df = ticker.history(interval=interval, start=start_date, end=end_date)

    if df.empty:
        raise ValueError(f"No data found for {symbol} between {start_date} and {end_date}.")

    df.index = df.index.strftime("%Y-%m-%d")
    df = df[["Open", "High", "Low", "Close", "Volume"]]

    return df.to_dict(orient="index")

if __name__ == "__main__":
    logger.info("Starting MCP server")
    mcp.run(transport='sse')