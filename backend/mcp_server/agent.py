from llama_index.tools.mcp import BasicMCPClient, McpToolSpec
from llama_index.core.agent.workflow import FunctionAgent, ToolCall, ToolCallResult
from llama_index.core.workflow import Context
from llama_index.llms.ollama import Ollama

from backend.utils import SYSTEM_PROMPT


class Agent:
    def __init__(self):
        self.mcp_client = BasicMCPClient("http://127.0.0.1:8000/sse", timeout=60)
        self.llm = Ollama(model='llama3.1:8b', request_timeout=300.0)

        self.agent = None
        self.context = None

    async def initialize_tools(self):
        mcp_tools = await McpToolSpec(client=self.mcp_client).to_tool_list_async()
        self.agent = FunctionAgent(
            name='FinanceWatcher Agent',
            description='An agent that can work with the financial data',
            tools=mcp_tools,
            llm=self.llm,
            system_prompt=SYSTEM_PROMPT,
        )
        self.context = Context(self.agent)

    async def ask(self, message: str, verbose: bool = True):
        handler = self.agent.run(message, ctx=self.context)

        async for event in handler.stream_events():
            if verbose and type(event) == ToolCall:
                print(f"Calling tool {event.tool_name} with kwargs {event.tool_kwargs}")
            if verbose and type(event) == ToolCallResult:
                print(f'Tool {event.tool_name} returned {event.tool_output}')

        response = await handler
        return str(response)

    async def __call__(self, message: str, verbose: bool = True):
        return await self.ask(message=message, verbose=verbose)
