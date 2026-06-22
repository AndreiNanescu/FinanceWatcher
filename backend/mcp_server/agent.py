from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama

from .agents import build_graph

_MCP_URL = "http://127.0.0.1:8000/sse"
_MODEL = "llama3.1:8b"


class Agent:
    """
    Multi-agent orchestrator backed by LangGraph.

    Graph topology
    --------------
    START → supervisor → chroma_agent ──┐
                      ↘ yfinance_agent ─┴→ supervisor → … → END

    The supervisor routes each turn to the appropriate specialist and
    synthesises the final analyst report once all data is gathered.
    """

    def __init__(self) -> None:
        self.llm = ChatOllama(model=_MODEL, num_predict=4096, temperature=0.0)
        self._mcp_client: MultiServerMCPClient | None = None
        self.graph = None

    async def initialize_tools(self) -> None:
        """Connect to the MCP server, load tools, and compile the graph."""
        self._mcp_client = MultiServerMCPClient(
            {"finance": {"url": _MCP_URL, "transport": "sse"}}
        )
        await self._mcp_client.__aenter__()

        tools = self._mcp_client.get_tools()
        chroma_tools = [t for t in tools if t.name == "get_news_for_company_or_symbol"]
        yfinance_tools = [t for t in tools if t.name == "fetch_price"]

        self.graph = build_graph(self.llm, chroma_tools, yfinance_tools)

    async def ask(self, message: str) -> str:
        result = await self.graph.ainvoke(
            {"messages": [HumanMessage(content=message)]}
        )
        return result["messages"][-1].content

    async def close(self) -> None:
        """Gracefully close the MCP connection."""
        if self._mcp_client is not None:
            await self._mcp_client.__aexit__(None, None, None)

    async def __call__(self, message: str) -> str:
        return await self.ask(message=message)
