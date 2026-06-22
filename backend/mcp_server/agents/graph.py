import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Annotated, TypedDict

import yfinance as yf
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

from backend.utils import logger, normalize_name

from .prompts import PLANNER_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT

_MAX_COMPANIES = 4
_PRICE_LOOKBACK_DAYS = 30
_HISTORY_TURNS = 6

_NEWS_TIMEOUT = 60
_PRICE_TIMEOUT = 20
_VALIDATE_TIMEOUT = 10

_TICKER_NAME_MATCH_MIN = 60


class Company(BaseModel):
    name: str = Field(description="Official company name, e.g. 'Apple'")
    ticker: str = Field(description="Primary US-listed ticker, e.g. 'AAPL'")


class Plan(BaseModel):
    companies: list[Company] = Field(default_factory=list)
    needs_news: bool = True
    needs_price: bool = False


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    plan: Plan | None
    news_blocks: list[str]
    price_blocks: list[str]


def _latest_user_question(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
            return msg.content
    return messages[-1].content if messages else ""


def _recent_history(messages: list, max_turns: int = _HISTORY_TURNS) -> str:
    """Render the prior turns (excluding the current question) as plain text so
    the planner can resolve follow-ups like "and its price?"."""
    prior = list(messages)
    while prior and (isinstance(prior[-1], HumanMessage) or getattr(prior[-1], "type", "") == "human"):
        prior.pop()

    rendered = []
    for msg in prior[-max_turns:]:
        content = getattr(msg, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        role = "User" if (isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human") else "Assistant"
        rendered.append(f"{role}: {content.strip()}")
    return "\n".join(rendered)


async def _ticker_matches_company(name: str, ticker: str) -> bool:
    """Best-effort check that `ticker` actually belongs to `name`.

    Returns True if we cannot determine otherwise (fail open on network errors,
    so a flaky yfinance lookup doesn't block well-known tickers), but False when
    yfinance reports a clearly different company — which is the case we must
    never surface as "the price of X".
    """

    def _lookup() -> str | None:
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception:
            return None
        return info.get("longName") or info.get("shortName") or None

    try:
        reported = await asyncio.wait_for(asyncio.to_thread(_lookup), timeout=_VALIDATE_TIMEOUT)
    except Exception:
        return True

    if not reported:
        return True

    score = fuzz.token_set_ratio(normalize_name(name), normalize_name(reported))
    if score < _TICKER_NAME_MATCH_MIN:
        logger.info(
            f"Ticker validation: '{ticker}' resolves to '{reported}', which does "
            f"not match requested company '{name}' (score {score}); skipping price."
        )
        return False
    return True


def build_graph(
    llm: ChatOllama,
    chroma_tools: list,
    yfinance_tools: list,
) -> "CompiledStateGraph":
    """
    Deterministic financial-analysis graph.

    Topology
    --------
    START → planner → gather → synthesis → END

    The planner resolves which companies/tickers are involved and whether news
    and/or price data is required (autonomous, multi-tool by default). The gather
    node calls the MCP tools directly with validated tickers — concurrently, with
    per-tool timeouts — so there is no routing recursion and the price tool can
    never be run against a company the planner did not resolve (or that fails
    ticker validation). The synthesis node turns the gathered data into a single
    natural-language answer. A checkpointer keeps per-thread conversation memory.
    """

    chroma_tool = chroma_tools[0] if chroma_tools else None
    yfinance_tool = yfinance_tools[0] if yfinance_tools else None
    planner_llm = llm.with_structured_output(Plan)

    # -- Planner -------------------------------------------------------------

    async def planner_node(state: AgentState) -> dict:
        question = _latest_user_question(state["messages"])
        history = _recent_history(state["messages"])
        user_content = f"Conversation so far:\n{history}\n\nCurrent question: {question}" if history else question
        try:
            plan = await planner_llm.ainvoke(
                [
                    SystemMessage(content=PLANNER_SYSTEM_PROMPT),
                    HumanMessage(content=user_content),
                ]
            )
        except Exception:
            plan = Plan(companies=[], needs_news=True, needs_price=False)

        plan.companies = plan.companies[:_MAX_COMPANIES]
        return {"plan": plan}

    async def gather_node(state: AgentState) -> dict:
        plan = state["plan"] or Plan()
        question = _latest_user_question(state["messages"])

        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=_PRICE_LOOKBACK_DAYS)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")

        targets = plan.companies or ([] if not plan.needs_news else [None])

        async def fetch_news(company) -> tuple[str, str]:
            label = f"{company.name} ({company.ticker})" if company else question
            query = f"{company.name} ({company.ticker})" if company else question
            symbols = company.ticker if company else ""
            try:
                result = await asyncio.wait_for(
                    chroma_tool.ainvoke({"query": query, "symbols": symbols}),
                    timeout=_NEWS_TIMEOUT,
                )
                return "news", f"News for {label}:\n{result}"
            except TimeoutError:
                return "news", f"News retrieval timed out for {label}."
            except Exception as exc:
                return "news", f"News retrieval failed for {label}: {exc}"

        async def fetch_price(company) -> tuple[str, str]:
            label = f"{company.name} ({company.ticker})"
            if not await _ticker_matches_company(company.name, company.ticker):
                return "price", (
                    f"Price data for {label} was not retrieved: the ticker "
                    f"'{company.ticker}' does not appear to belong to {company.name}, "
                    f"so potentially incorrect price data was withheld."
                )
            try:
                result = await asyncio.wait_for(
                    yfinance_tool.ainvoke(
                        {
                            "symbol": company.ticker,
                            "start_date": start_date,
                            "end_date": end_date,
                        }
                    ),
                    timeout=_PRICE_TIMEOUT,
                )
                return "price", f"Price data for {label} ({start_date} → {end_date}):\n{result}"
            except TimeoutError:
                return "price", f"Price retrieval timed out for {label}."
            except Exception as exc:
                return "price", f"Price retrieval failed for {label}: {exc}"

        tasks = []
        for company in targets:
            if plan.needs_news and chroma_tool is not None:
                tasks.append(fetch_news(company))
            if plan.needs_price and yfinance_tool is not None and company is not None:
                tasks.append(fetch_price(company))

        results = await asyncio.gather(*tasks) if tasks else []

        news_blocks = [block for kind, block in results if kind == "news"]
        price_blocks = [block for kind, block in results if kind == "price"]
        return {"news_blocks": news_blocks, "price_blocks": price_blocks}

    async def synthesis_node(state: AgentState) -> dict:
        question = _latest_user_question(state["messages"])
        history = _recent_history(state["messages"])
        news_blocks = state.get("news_blocks") or []
        price_blocks = state.get("price_blocks") or []

        context_parts = []
        if news_blocks:
            context_parts.append("=== RECENT NEWS ===\n" + "\n\n".join(news_blocks))
        if price_blocks:
            context_parts.append("=== PRICE DATA ===\n" + "\n\n".join(price_blocks))
        context = "\n\n".join(context_parts) if context_parts else "No data was retrieved."

        prompt = ""
        if history:
            prompt += f"Conversation so far:\n{history}\n\n"
        prompt += f"User question:\n{question}\n\nRetrieved data:\n{context}\n\nWrite the analysis:"

        response = await llm.ainvoke(
            [
                SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )

        content = (response.content or "").strip()
        if not content:
            content = (
                "I couldn't find enough information to answer that confidently. "
                "Try asking about a specific company or ticker."
            )
        return {"messages": [AIMessage(content=content)]}

    builder = StateGraph(AgentState)
    builder.add_node("planner", planner_node)
    builder.add_node("gather", gather_node)
    builder.add_node("synthesis", synthesis_node)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "gather")
    builder.add_edge("gather", "synthesis")
    builder.add_edge("synthesis", END)

    return builder.compile(checkpointer=MemorySaver())
