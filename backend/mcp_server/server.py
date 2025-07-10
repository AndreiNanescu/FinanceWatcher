import os
import sys

from mcp.server.fastmcp import FastMCP

from backend.data import ChromaClient, Querier
from backend.rag import BGEReranker, EntityAndTickerExtractor
from backend.utils import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

mcp = FastMCP('FinanceWatcherServer')

chroma_client = ChromaClient()
reranker = BGEReranker()
extractor = EntityAndTickerExtractor()
query_service = Querier(chroma_client=chroma_client, reranker=reranker, extractor=extractor)

@mcp.tool(name="get_news_for_company_or_symbol", description="Queries the chroma db for news related to the input")
def query_chroma(query: str) -> str:
    """
    Queries the Chroma database for news articles matching the provided query string.

    Args:
        query (str): The search term, which can be a company name or stock symbol.

    Returns:
        str: A string containing the concatenated news articles. If no relevant news is found, returns a default message.
    """
    docs = query_service.search(query)
    return "\n\n".join(item["document"] for item in docs) or "No relevant news found."

if __name__ == "__main__":
    logger.info("Starting MCP server")
    mcp.run(transport='sse')