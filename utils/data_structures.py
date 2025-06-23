from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class Article:
    uuid: str
    title: str
    description: str
    url: str
    published_at: str
    source: str
    entities: list['Entity']


@dataclass
class Entity:
    article_uuid: str
    symbol: str
    name: str
    raw_sentiment: float | str
    industry: Optional[str] = None
    normalized_name: str = field(init=False)

    def __post_init__(self):
        from utils import normalize_name
        self.normalized_name = normalize_name(self.name)

    @property
    def formatted_sentiment(self) -> str:
        if isinstance(self.raw_sentiment, str):
            return self.raw_sentiment

        if self.raw_sentiment > 0.2:
            return f"Positive ({self.raw_sentiment:.2f})"
        elif self.raw_sentiment < -0.2:
            return f"Negative ({self.raw_sentiment:.2f})"
        return f"Neutral ({self.raw_sentiment:.2f})"


@dataclass
class NewsDocument:
    id: str
    content: str
    metadata: Dict[str, Any]

    @classmethod
    def from_article_entity(cls, article: Article, entity: Entity) -> 'NewsDocument':
        if entity.article_uuid != article.uuid:
            raise ValueError("Entity does not belong to this article")

        content = cls._build_content(article, entity)
        metadata = cls._build_metadata(article, entity)

        return cls(
            id=f"{article.uuid}_{entity.symbol}",
            content=content,
            metadata=metadata
        )

    @staticmethod
    def _build_content(article: Article, entity: Entity) -> str:
        return f"""
        Title: {article.title}
        Published on: {article.published_at}
        Source: {article.source}
        URL: {article.url}

        Description: {article.description}

        Mentioned Entity: {entity.name}
        Symbol: {entity.symbol}
        Sentiment: {entity.formatted_sentiment}
        Industry: {entity.industry or 'N/A'}
        """.strip()

    @staticmethod
    def _build_metadata(article: Article, entity: Entity) -> Dict[str, Any]:
        return {
            "article_id": article.uuid,
            "title": article.title,
            "source": article.source,
            "published_at": article.published_at,
            "url": article.url,
            "entity": entity.name,
            "symbol": entity.symbol,
            "sentiment_raw": entity.raw_sentiment,
            "sentiment_label": entity.formatted_sentiment,
            "industry": entity.industry,
            "entity_type": "specific"
        }