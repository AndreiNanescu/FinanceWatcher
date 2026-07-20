import asyncio
import json
import re
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

from backend.config import config
from backend.utils import NO_NEWS_AVAILABLE_SENTINEL, NO_RELEVANT_NEWS_MESSAGE, logger, normalize_name

from .prompts import SYNTHESIS_SYSTEM_PROMPT, build_planner_system_prompt


class Company(BaseModel):
    name: str = Field(description="Official company name, e.g. 'Apple'")
    ticker: str = Field(description="Primary US-listed ticker, e.g. 'AAPL'")
    needs_news: bool = Field(
        default=True,
        description=(
            "Whether to fetch recent NEWS for THIS company. True for a general "
            "status question or when the user asks about its news/events/sentiment; "
            "set False if the user only asks about this company's price."
        ),
    )
    needs_price: bool = Field(
        default=True,
        description=(
            "Whether to fetch PRICE data for THIS company. True for a general "
            "status question or when the user asks about its price/returns/"
            "performance; set False if the user only asks about this company's news."
        ),
    )
    news_focus: str = Field(
        default="",
        description=(
            "A SHORT topical focus (2-5 words) ONLY when the question targets a "
            "specific aspect of the company — e.g. 'China market risks', 'AI "
            "strategy', 'legal issues', 'earnings', 'iPhone sales'. Used to rank "
            "news toward that topic. Leave EMPTY for a broad/general 'how is it "
            "doing' question. Pick the single focus of the question; never list "
            "multiple topics and do not include the company name."
        ),
    )


class Plan(BaseModel):
    companies: list[Company] = Field(default_factory=list)
    # Fallback news flag for questions where no specific company is identified;
    # per-company news/price selection lives on each Company.
    needs_news: bool = True
    price_days: int = Field(
        default=config.agent.price_lookback_days,
        description=(
            "Days of recent daily price history to fetch, chosen from the "
            "question's time horizon (7=week, 30=month, 90=quarter, up to 365=year)."
        ),
    )
    news_count: int = Field(
        default=config.agent.default_news_count,
        description=(
            "How many news articles to retrieve per company, based on how broad "
            "the question is: ~3-4 for a narrow/specific question, ~5 for a typical "
            "status question, up to ~8 for a broad 'tell me everything' question."
        ),
    )


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    plan: Plan | None
    sections: list[str]


def _is_no_news(result: str) -> bool:
    return NO_RELEVANT_NEWS_MESSAGE.lower() in result.strip().lower()


def _summarize_prices(label: str, days: int, raw) -> str:
    """
    Turn raw OHLCV (dict or JSON string) into a compact, pre-computed summary.
    """
    try:
        data = raw if isinstance(raw, dict) else json.loads(str(raw))
        if not isinstance(data, dict) or not data:
            raise ValueError("empty or non-dict price data")
    except Exception:
        return f"Price for {label} (last {days} days): {raw}"

    rows = sorted(data.items())
    first_date, first = rows[0]
    last_date, last = rows[-1]

    closes = [v["Close"] for _, v in rows if v.get("Close") is not None]
    highs = [v["High"] for _, v in rows if v.get("High") is not None]
    lows = [v["Low"] for _, v in rows if v.get("Low") is not None]
    vols = [v["Volume"] for _, v in rows if v.get("Volume") is not None]

    if not closes:
        return f"Price for {label} (last {days} days): {raw}"

    first_close, last_close = closes[0], closes[-1]
    pct = ((last_close - first_close) / first_close * 100) if first_close else 0.0
    direction = "up" if pct > 0 else "down" if pct < 0 else "flat"
    period_high = max(highs) if highs else max(closes)
    period_low = min(lows) if lows else min(closes)
    avg_vol = sum(vols) / len(vols) if vols else 0

    return (
        f"Price summary for {label} over the last {days} days "
        f"({len(rows)} trading days, {first_date} to {last_date}): "
        f"closed at {last_close:.2f} on {last_date} versus {first_close:.2f} on {first_date}, "
        f"{direction} {abs(pct):.1f}% over the window. "
        f"Intraday range over the period was {period_low:.2f} to {period_high:.2f}. "
        f"Average daily volume was about {avg_vol:,.0f} shares. "
        f"(These are the only price facts available — there is no year-to-date, "
        f"52-week, or market-cap data.)"
    )


def _strip_markdown(text: str) -> str:
    """Safety net: enforce the prose style the prompt asks for even when the
    model slips into headings/bullets/bold despite the instructions."""
    cleaned_lines = []

    for line in text.split("\n"):
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*[\*\-•]\s+", "", line)
        cleaned_lines.append(line)

    out = "\n".join(cleaned_lines)
    out = out.replace("**", "").replace("__", "")
    out = re.sub(r"\n{3,}", "\n\n", out)

    return out.strip()


def _latest_user_question(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
            return msg.content
    return messages[-1].content if messages else ""


def _recent_history(messages: list, max_turns: int = config.agent.history_turns) -> str:
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


# Common-name <-> legal-name pairs that fuzzy matching can't catch because they
# share no tokens (e.g. Google ↔ Alphabet). Maps ticker -> accepted name tokens
# (already normalized via normalize_name). Extend as needed.
_TICKER_NAME_ALIASES = {
    "GOOGL": {"google", "alphabet"},
    "GOOG": {"google", "alphabet"},
    "META": {"meta", "facebook"},
    "BRK.B": {"berkshire", "berkshire hathaway"},
    "BRK.A": {"berkshire", "berkshire hathaway"},
}


async def _ticker_matches_company(name: str, ticker: str) -> bool:
    """Best-effort check that `ticker` actually belongs to `name`.

    Returns True if we cannot determine otherwise (fail open on network errors,
    so a flaky yfinance lookup doesn't block well-known tickers), but False when
    yfinance reports a clearly different company — which is the case we must
    never surface as "the price of X".
    """

    def _lookup() -> list[str]:
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception:
            return []
        return [n for n in (info.get("longName"), info.get("shortName"), info.get("displayName")) if n]

    try:
        reported = await asyncio.wait_for(asyncio.to_thread(_lookup), timeout=config.agent.validate_timeout)
    except Exception:
        return True

    if not reported:
        return True

    norm_name = normalize_name(name)

    # Known common/legal-name aliases (Google↔Alphabet, Facebook↔Meta, …) that
    # the fuzzy check would wrongly reject.
    aliases = _TICKER_NAME_ALIASES.get(ticker.strip().upper())
    if aliases and norm_name in aliases:
        return True

    # Otherwise fuzzy-match against every name yfinance reports, taking the best.
    score = max(fuzz.token_set_ratio(norm_name, normalize_name(r)) for r in reported)
    if score < config.agent.ticker_name_match_min:
        logger.info(
            f"Ticker validation: '{ticker}' resolves to {reported}, which does "
            f"not match requested company '{name}' (score {score}); skipping price."
        )
        return False
    return True


def build_graph(planner_llm: ChatOllama, synthesis_llm: ChatOllama, chroma_tools: list, yfinance_tools: list) -> "CompiledStateGraph":
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
    planner_llm_obj = planner_llm.with_structured_output(Plan)


    async def planner_node(state: AgentState) -> dict:
        question = _latest_user_question(state["messages"])
        history = _recent_history(state["messages"])
        user_content = f"Conversation so far:\n{history}\n\nCurrent question: {question}" if history else question
        try:
            plan = await planner_llm_obj.ainvoke(
                [
                    SystemMessage(content=build_planner_system_prompt()),
                    HumanMessage(content=user_content),
                ]
            )
        except Exception:
            plan = Plan(companies=[], needs_news=True)

        plan.companies = plan.companies[:config.agent.max_companies]
        return {"plan": plan}

    async def gather_node(state: AgentState) -> dict:
        plan = state["plan"] or Plan()
        question = _latest_user_question(state["messages"])

        price_days = max(1, min(plan.price_days or config.agent.price_lookback_days, config.retrieval.max_price_days))
        news_count = max(1, min(plan.news_count or config.agent.default_news_count, config.agent.max_news_count))

        targets = plan.companies or ([] if not plan.needs_news else [None])

        async def get_news(company, label: str) -> str:
            if company:
                entity = f"{company.name} ({company.ticker})"
                focus = company.news_focus.strip()
                # Entity alone ranks by company-centrality (good for broad
                # questions); appending a short topic tilts ranking toward that
                # aspect for specific questions. Kept short on purpose — the
                # cross-encoder reranker degrades on verbose queries.
                rerank_query = f"{entity} {focus}" if focus else entity
                query = rerank_query
                symbols = company.ticker
            else:
                query = question
                rerank_query = question
                symbols = ""
            try:
                result = await asyncio.wait_for(
                    chroma_tool.ainvoke(
                        {"query": query, "symbols": symbols, "rerank_query": rerank_query, "top_n": news_count}
                    ),
                    timeout=config.agent.news_timeout,
                )
            except TimeoutError:
                return f"News: retrieval timed out for {label}."
            except Exception as exc:
                return f"News: retrieval failed for {label}: {exc}"

            if not result or not str(result).strip() or _is_no_news(str(result)):
                return (
                    f"News: {NO_NEWS_AVAILABLE_SENTINEL} for {label}. No recent news articles were found. "
                    f"Do not invent, infer, or speculate about any news for this company — "
                    f"state plainly that no recent news was available and rely on its price data."
                )
            return f"News for {label}:\n{result}"

        async def get_price(company, label: str) -> str:
            if not await _ticker_matches_company(company.name, company.ticker):
                return (
                    f"Price: not retrieved — the ticker '{company.ticker}' does not appear to "
                    f"belong to {company.name}, so potentially incorrect price data was withheld."
                )
            try:
                result = await asyncio.wait_for(
                    yfinance_tool.ainvoke({"symbol": company.ticker, "days": price_days}),
                    timeout=config.agent.price_timeout,
                )
            except TimeoutError:
                return f"Price: retrieval timed out for {label}."
            except Exception as exc:
                return f"Price: retrieval failed for {label}: {exc}"
            return _summarize_prices(label, price_days, result)

        async def gather_company(company) -> str:
            label = f"{company.name} ({company.ticker})" if company else question
            # Per-company tool selection: a company is fetched news/price based on
            # its own flags (no-company fallback uses the plan-level news flag).
            want_news = company.needs_news if company else plan.needs_news
            want_price = company.needs_price if company else False

            subtasks = []
            if want_news and chroma_tool is not None:
                subtasks.append(get_news(company, label))
            if want_price and yfinance_tool is not None and company is not None:
                subtasks.append(get_price(company, label))

            parts = await asyncio.gather(*subtasks) if subtasks else []
            header = f"Company: {label}" if company else f"Topic: {question}"
            return header + "\n" + "\n\n".join(parts)

        sections = await asyncio.gather(*[gather_company(c) for c in targets]) if targets else []

        return {"sections": list(sections)}

    async def synthesis_node(state: AgentState) -> dict:
        question = _latest_user_question(state["messages"])
        history = _recent_history(state["messages"])
        sections = state.get("sections") or []

        context = "\n\n".join(sections) if sections else "No data was retrieved."

        prompt = ""
        if history:
            prompt += f"Conversation so far:\n{history}\n\n"
        prompt += (
            f"User question:\n{question}\n\n"
            f"Retrieved data (one block per company — weave each company's news and "
            f"price together):\n{context}\n\nWrite the analysis:"
        )

        response = await synthesis_llm.ainvoke(
            [
                SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )

        content = _strip_markdown((response.content or "").strip())
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
