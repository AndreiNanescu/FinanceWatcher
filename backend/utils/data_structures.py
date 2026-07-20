import json
import re
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, TypedDict

from .constants import KEYWORDS_LINE_PREFIX
from .io_utils import normalize_name


def symbol_flag_key(symbol: str) -> str:
    """Chroma metadata key for a per-symbol boolean flag.

    Chroma metadata values must be scalars, so a comma-joined `entity_symbols`
    string can't be filtered with `$in`. Instead each article stores one boolean
    flag per symbol (e.g. {"sym_AAPL": True}) so retrieval can filter by ticker
    at the DB level. Symbols are upper-cased and non-alphanumerics replaced so the
    key is stable for tickers like "^NSEI" or "HDB.BA".
    """
    return "sym_" + re.sub(r"[^A-Z0-9]", "_", symbol.strip().upper())


@dataclass
class Article:
    uuid: str
    title: str
    description: str
    keywords: str
    url: str
    published_at: str
    fetched_on: str
    entities: list["Entity"]
    full_text: str | None = None


@dataclass
class Entity:
    symbol: str
    name: str
    sentiment: str
    industry: str | None = None


def format_sentiment(score: float) -> str:
    if score > 0.2:
        return f"Positive ({score:.2f})"
    elif score < -0.2:
        return f"Negative ({score:.2f})"
    else:
        return f"Neutral ({score:.2f})"


@dataclass
class NewsDocument:
    id: str
    content: str
    metadata: dict[str, Any]

    @classmethod
    def from_article(cls, article: Article) -> "NewsDocument":
        content = cls._build_content(article)
        metadata = cls._build_metadata(article)
        return cls(id=article.uuid, content=content, metadata=metadata)

    @staticmethod
    def _build_content(article: "Article") -> str:
        return dedent(f"""\
            Title: {article.title}
            {KEYWORDS_LINE_PREFIX} {article.keywords}
            Description: {article.description}
        """).strip()

    @staticmethod
    def _build_metadata(article: Article) -> dict[str, Any]:
        entities: list[dict[str, str | None]] = [
            {
                "name": e.name,
                "symbol": e.symbol,
                "sentiment": e.sentiment,
                "industry": e.industry,
            }
            for e in article.entities
        ]

        metadata: dict[str, Any] = {
            "published_at": article.published_at,
            "url": article.url,
            "entities": json.dumps(entities),
            "entity_names": ", ".join(normalize_name(e["name"] or "") for e in entities),
            "entity_symbols": ", ".join(e["symbol"] or "" for e in entities),
        }

        # Per-symbol boolean flags so retrieval can filter by ticker at the DB
        # level (see symbol_flag_key).
        for e in entities:
            sym = (e["symbol"] or "").strip()
            if sym and sym.upper() != "NO SYMBOL":
                metadata[symbol_flag_key(sym)] = True

        return metadata


class Candidate(TypedDict):
    document: str
    metadata: dict
    score: float
