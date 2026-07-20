import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

# Filesystem anchors. config.py lives at the backend package root and does not
# move, so every data location is derived from here
BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"
DB_DIR = BACKEND_DIR / "db"
CHROMA_DATA_DIR = BACKEND_DIR / "data" / "db"
RAW_HTML_DIR = BACKEND_DIR / "data" / "raw_html"
LOGS_DIR = BACKEND_DIR / "logs"


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planner: str
    synthesis: str
    summarizer: str
    embedder: str
    reranker: str


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rerank_threshold: float = 0.3
    min_floor: float = 0.1
    recency_weight: float = 0.3
    recency_tau_days: float = 30.0
    max_rerank_candidates: int = 120
    max_top_n: int = 15
    max_price_days: int = 365

class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_companies: int = 4
    price_lookback_days: int = 30
    default_news_count: int = 5
    max_news_count: int = 15
    history_turns: int = 6
    news_timeout: int = 60
    price_timeout: int = 20
    validate_timeout: int = 10
    ticker_name_match_min: int = 60

class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str]

class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_port: int
    mcp_url: str

class MarketAuxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str

class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: ModelsConfig
    retrieval: RetrievalConfig = RetrievalConfig()
    agent: AgentConfig = AgentConfig()
    ingestion: IngestionConfig
    server: ServerConfig
    marketaux: MarketAuxConfig
    marketaux_api_key: str =""


def load_config(path: Path | None = None) -> Config:
    path = path or BACKEND_DIR / "config.yaml"
    load_dotenv(ENV_FILE)

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config(**raw, marketaux_api_key=os.getenv("MARKETAUX_API_KEY", ""))


config = load_config()