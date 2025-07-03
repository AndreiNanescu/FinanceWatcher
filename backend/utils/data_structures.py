import json

from dataclasses import dataclass
from typing import Optional, Dict, Any, TypedDict
from textwrap import dedent

@dataclass
class Article:
    uuid: str
    title: str
    description: str
    keywords: str
    url: str
    published_at: str
    fetched_on: str
    entities: list['Entity']


@dataclass
class Entity:
    symbol: str
    name: str
    sentiment: str
    industry: Optional[str] = None

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
    metadata: Dict[str, Any]

    @classmethod
    def from_article(cls, article: Article) -> 'NewsDocument':
        content = cls._build_content(article)
        metadata = cls._build_metadata(article)
        return cls(id=article.uuid, content=content, metadata=metadata)

    @staticmethod
    def _build_content(article: 'Article') -> str:
        description = article.description or ""
        companies = ", ".join(
            f"{entity.name} ({entity.symbol})"
            for entity in article.entities
        )
        return dedent(f"""\
            Mentioned companies: {companies}
            Keywords present: {article.keywords}
            Title: {article.title}
            Description: {description}
        """).strip()

    @staticmethod
    def _build_metadata(article: Article) -> Dict[str, Any]:
        return {
            "article_id": article.uuid,
            "published_at": article.published_at,
            "url": article.url,
            "entities": json.dumps([
                {
                    "name": e.name,
                    "symbol": e.symbol,
                    "sentiment": e.sentiment,
                    "industry": e.industry,
                }
                for e in article.entities
            ]),
        }

class Candidate(TypedDict):
    document: str
    metadata: Dict
    score: float