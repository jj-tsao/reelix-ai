"""Bootstrap factories for the recommendation stack.

Every transport (FastAPI app, MCP server) builds the same singletons through
these factories; only the transport wiring differs per app.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

import httpx

from reelix_core.config import (
    NLTK_PATH,
    QDRANT_MOVIE_COLLECTION_NAME,
    QDRANT_TV_COLLECTION_NAME,
)

# NLTK resolves its data path at import time; set it before any module that
# pulls nltk (tokenizer/stopwords) is imported below or by the factories.
os.environ.setdefault("NLTK_DATA", str(NLTK_PATH))

from reelix_logging.rec_logger import TelemetryLogger  # noqa: E402
from reelix_runtime.cache.redis_infra import make_redis_clients  # noqa: E402
from reelix_runtime.cache.state_store import StateStore  # noqa: E402
from reelix_runtime.cache.ticket_store import TicketStore  # noqa: E402
from reelix_runtime.cache.why_cache import WhyCache  # noqa: E402
from reelix_runtime.settings import RuntimeSettings  # noqa: E402

if TYPE_CHECKING:
    from qdrant_client import QdrantClient
    from reelix_agent.orchestrator.agent_rec_runner import AgentRecRunner
    from reelix_agent.tools import ToolRegistry, ToolRunner
    from reelix_recommendation.recommend import RecommendPipeline
    from reelix_retrieval.query_encoder import Encoder

log = logging.getLogger(__name__)


@dataclass
class RecommendationRuntime:
    """Heavy recommendation singletons (models, retriever, pipeline, tools)."""

    qdrant: "QdrantClient"
    query_encoder: "Encoder"
    recommend_pipeline: "RecommendPipeline"
    agent_rec_runner: "AgentRecRunner"
    recipes: dict[str, Any]
    tool_registry: "ToolRegistry"
    tool_runner: "ToolRunner"


@dataclass
class Stores:
    """Redis-backed stores shared by the two-phase recommendation flow."""

    ticket_store: TicketStore
    state_store: StateStore
    why_cache: WhyCache


def build_recommendation_runtime(settings: RuntimeSettings) -> RecommendationRuntime:
    """Load models and construct the retrieval/ranking/agent stack.

    Heavy: loads the sentence-transformer + BM25 assets and connects to Qdrant.
    Imports are deferred so processes that skip recommendation init don't pay
    for torch/sentence-transformers at import time.
    """
    from qdrant_client import QdrantClient
    from reelix_agent.orchestrator.agent_rec_runner import AgentRecRunner
    from reelix_agent.tools import build_registry, ToolRunner
    from reelix_models.custom_models import load_bm25_files, load_sentence_model
    from reelix_recommendation.recipes import ForYouFeedRecipe, InteractiveRecipe
    from reelix_recommendation.recommend import RecommendPipeline
    from reelix_retrieval.base_retriever import BaseRetriever
    from reelix_retrieval.query_encoder import Encoder

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    startup_t0 = time.perf_counter()

    # == Verify required credentials ==
    required = {
        "QDRANT_ENDPOINT": settings.qdrant_endpoint,
        "QDRANT_API_KEY": settings.qdrant_api_key,
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_API_KEY": settings.supabase_api_key,
        "OPENAI_API_KEY": settings.openai_api_key,
        "REDIS_URL": settings.redis_url,
    }
    missing = [
        name for name, value in required.items() if not (value and value.strip())
    ]
    if missing:
        raise RuntimeError(
            "Missing credentials in environment: " + ", ".join(sorted(missing))
        )

    # == Initialize recommendation stack ==
    embed_model = load_sentence_model()
    bm25_models, bm25_vocabs = load_bm25_files()
    query_encoder = Encoder(embed_model, bm25_models, bm25_vocabs)
    qdrant = QdrantClient(
        url=settings.qdrant_endpoint,
        api_key=settings.qdrant_api_key,
    )

    base_retriever = BaseRetriever(
        qdrant,
        movie_collection=QDRANT_MOVIE_COLLECTION_NAME,
        tv_collection=QDRANT_TV_COLLECTION_NAME,
        dense_vector_name="dense_vector",
        sparse_vector_name="sparse_vector",
    )
    pipeline = RecommendPipeline(base_retriever, rrf_k=60)

    # == Initialize agent tool infrastructure ==
    tool_registry = build_registry()

    runtime = RecommendationRuntime(
        qdrant=qdrant,
        query_encoder=query_encoder,
        recommend_pipeline=pipeline,
        agent_rec_runner=AgentRecRunner(
            pipeline=pipeline,
            query_encoder=query_encoder,
        ),
        recipes={
            "for_you_feed": ForYouFeedRecipe(query_encoder=query_encoder),
            "interactive": InteractiveRecipe(query_encoder=query_encoder),
        },
        tool_registry=tool_registry,
        tool_runner=ToolRunner(tool_registry),
    )

    log.info(
        "🔧 Recommendation stack ready in %.2fs", time.perf_counter() - startup_t0
    )
    return runtime


def build_stores(settings: RuntimeSettings) -> Stores:
    """Construct the Redis-backed ticket/session/why stores."""
    if not settings.redis_url:
        raise RuntimeError("Missing credentials in environment: REDIS_URL")

    redis_clients = make_redis_clients(settings.redis_url)

    return Stores(
        ticket_store=TicketStore(
            client=redis_clients.bytes,
            namespace=settings.ticket_namespace,
            absolute_ttl_sec=settings.ticket_ttl_sec,
        ),
        state_store=StateStore(
            client=redis_clients.bytes,
            namespace=settings.session_namespace,
            absolute_ttl_sec=settings.session_ttl_sec,
        ),
        why_cache=WhyCache(
            client=redis_clients.text,
            namespace=settings.why_cache_namespace,
            absolute_ttl_sec=settings.why_cache_ttl_sec,
        ),
    )


def build_telemetry(
    settings: RuntimeSettings, *, timeout_s: float = 5.0
) -> tuple[httpx.AsyncClient, TelemetryLogger]:
    """Construct the Supabase telemetry logger and its HTTP client.

    The caller owns the returned client's lifecycle (``await client.aclose()``).
    """
    if not settings.supabase_url or not settings.supabase_api_key:
        raise RuntimeError("Missing Supabase credits")

    http_client = httpx.AsyncClient(timeout=timeout_s)
    logger = TelemetryLogger(
        settings.supabase_url,
        settings.supabase_api_key,
        client=http_client,
        timeout_s=timeout_s,
    )
    return http_client, logger