"""Pins that modules actually consume the config seam correctly.

These are the acceptance criteria for the config-wiring changes: Querier's
defaults must mirror config.retrieval (the eval-parity precondition), and the
tool-facing top_n clamp must stay a small answer-size cap, not the rerank-pool
cap (returning 120 articles to a 7B model is a context explosion).
"""

from backend.config import config


def test_querier_defaults_mirror_retrieval_config():
    # Import inside the test: a wiring mistake in default-arg evaluation makes
    # the import itself fail, and we want that reported as THIS test failing.
    from backend.data.chroma.query_service import Querier

    querier = Querier.__new__(Querier)  # no chroma/reranker needed for defaults
    defaults = Querier.__init__.__defaults__
    # (recency_weight, recency_tau_days, max_rerank_candidates, use_reranker)
    assert defaults[0] == config.retrieval.recency_weight
    assert defaults[1] == config.retrieval.recency_tau_days
    assert defaults[2] == config.retrieval.max_rerank_candidates
    del querier


def test_agent_consumes_both_model_roles():
    # Planner and synthesis are independently configurable models; both YAML
    # keys must actually reach their ChatOllama instances (a config key that
    # does nothing is a dead flag).
    from backend.mcp_server.agent import Agent

    agent = Agent()
    assert agent.llm_planner.model == config.models.planner
    assert agent.llm_synthesis.model == config.models.synthesis


def test_top_n_cap_is_answer_sized_not_pool_sized():
    # The MCP tool's top_n clamps how many articles reach the LLM's context —
    # it must exist as its own small config value, distinct from the 120-wide
    # rerank-candidate pool.
    assert hasattr(config.retrieval, "max_top_n"), "add retrieval.max_top_n to config (was _MAX_TOP_N = 15)"
    assert config.retrieval.max_top_n <= 20
    assert config.retrieval.max_top_n < config.retrieval.max_rerank_candidates
