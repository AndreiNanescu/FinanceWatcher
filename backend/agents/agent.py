from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama

from backend.config import config

from .graph import build_graph


class Agent:
    """
    Multi-agent orchestrator backed.
    """

    def __init__(self) -> None:
        self.llm_planner = ChatOllama(model=config.models.planner, num_predict=4096, temperature=0.0)
        self.llm_synthesis = ChatOllama(model=config.models.synthesis, num_predict=4096, temperature=0.0)
        self._mcp_client: MultiServerMCPClient | None = None
        self.graph = None

    async def initialize_tools(self) -> None:
        """Connect to the MCP server, load tools, and compile the graph."""
        self._mcp_client = MultiServerMCPClient({"finance": {"url": config.server.mcp_url, "transport": "sse"}})

        tools = await self._mcp_client.get_tools()
        chroma_tools = [t for t in tools if t.name == "get_news_for_company_or_symbol"]
        yfinance_tools = [t for t in tools if t.name == "fetch_price"]

        self.graph = build_graph(self.llm_planner, self.llm_synthesis, chroma_tools, yfinance_tools)

    async def ask(self, message: str, thread_id: str = "default") -> str:

        result = await self.graph.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config={"configurable": {"thread_id": thread_id}},
        )

        for msg in reversed(result["messages"]):
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                return content
        return "I couldn't generate a response."

    async def close(self) -> None:
        self._mcp_client = None

    async def __call__(self, message: str, thread_id: str = "default") -> str:
        return await self.ask(message=message, thread_id=thread_id)
