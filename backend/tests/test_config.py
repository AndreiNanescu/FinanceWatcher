"""Guards for the committed config: the schema must load, hold sane values,
and reject unknown keys loudly. Every assertion here corresponds to a bug that
actually shipped during the config PR (swapped types, corrupted URL, schema/
YAML drift) — this file is what makes those one-time fixes permanent."""

import pytest
from backend.config import load_config
from pydantic import ValidationError

VALID_YAML = """\
models:
  planner: m
  synthesis: m
  summarizer: m
  embedder: m
  reranker: m
ingestion:
  symbols: [AAPL]
server:
  api_port: 1234
  mcp_url: http://localhost:8000/sse
marketaux:
  base_url: https://api.marketaux.com/v1/news/all
"""


def test_committed_config_loads():
    cfg = load_config()
    # Non-secret assertions only: CI has no .env, so never assert on the API key.
    assert cfg.marketaux.base_url.startswith("https://api.marketaux.com")
    assert isinstance(cfg.server.api_port, int)
    assert cfg.server.mcp_url.startswith("http")
    assert len(cfg.ingestion.symbols) > 0
    assert all(s.strip() for s in cfg.ingestion.symbols)
    assert 0.0 <= cfg.retrieval.min_floor <= cfg.retrieval.rerank_threshold <= 1.0
    assert cfg.retrieval.max_rerank_candidates > 0
    for role in ("planner", "synthesis", "summarizer", "embedder", "reranker"):
        assert getattr(cfg.models, role).strip()


def test_unknown_key_rejected(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text(VALID_YAML.replace("api_port: 1234", "api_port: 1234\n  typo_key: oops"), encoding="utf-8")
    with pytest.raises(ValidationError, match="typo_key"):
        load_config(bad)


def test_missing_section_rejected(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text(VALID_YAML.replace("marketaux:\n  base_url: https://api.marketaux.com/v1/news/all\n", ""), encoding="utf-8")
    with pytest.raises(ValidationError, match="marketaux"):
        load_config(bad)


def test_wrong_type_rejected(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text(VALID_YAML.replace("api_port: 1234", "api_port: not_a_port"), encoding="utf-8")
    with pytest.raises(ValidationError, match="api_port"):
        load_config(bad)


def test_valid_minimal_config_accepted(tmp_path):
    good = tmp_path / "config.yaml"
    good.write_text(VALID_YAML, encoding="utf-8")
    cfg = load_config(good)
    assert cfg.server.api_port == 1234
    # Retrieval section omitted -> typed defaults apply.
    assert cfg.retrieval.rerank_threshold == 0.3
