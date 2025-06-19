from dataclasses import dataclass
from typing import Optional, List, Dict

@dataclass
class Article:
    uuid: str
    title: Optional[str]
    description: Optional[str]
    url: Optional[str]
    published_at: Optional[str]
    source: Optional[str]
    entities: Optional[List[Dict]] = None

@dataclass
class Entity:
    article_uuid: str
    symbol: Optional[str] = None
    name: Optional[str] = None
    sentiment: Optional[str] = None
    industry: Optional[str] = None

    @classmethod
    def from_raw_score(cls, article_uuid: str, symbol: str, score: float, **kwargs):
        sentiment_label = cls._format_sentiment(score)
        return cls(
            article_uuid=article_uuid,
            symbol=symbol,
            sentiment=sentiment_label,
            **kwargs
        )

    @staticmethod
    def _format_sentiment(score: float) -> str:
        if score > 0.2:
            return f"Positive ({score:.2f})"
        elif score < -0.2:
            return f"Negative ({score:.2f})"
        else:
            return f"Neutral ({score:.2f})"