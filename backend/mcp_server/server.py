import os
import re
import sys

from mcp.server.fastmcp import FastMCP

from backend.data import ChromaClient, Querier
from backend.rag import BGEReranker
from backend.utils import logger, format_metadata

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

mcp = FastMCP('FinanceWatcherServer')

chroma_client = ChromaClient()
reranker = BGEReranker()
query_service = Querier(chroma_client=chroma_client, reranker=reranker)

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

if __name__ == "__main__":
    logger.info("Starting MCP server")
    mcp.run(transport='sse')