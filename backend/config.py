import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict


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
    ingestion: IngestionConfig
    server: ServerConfig
    marketaux: MarketAuxConfig
    marketaux_api_key: str =""


def load_config(path: Path | None = None) -> Config:
    path = path or Path(__file__).parent / "config.yaml"
    load_dotenv(Path(__file__).parent / ".env")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config(**raw, marketaux_api_key=os.getenv("MARKETAUX_API_KEY", ""))


config = load_config()