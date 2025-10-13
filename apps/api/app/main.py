import os
import time
from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient

from reelix_core.config import (
    NLTK_PATH,
    QDRANT_MOVIE_COLLECTION_NAME,
    QDRANT_TV_COLLECTION_NAME,
)
from app.infrastructure.cache.ticket_store import make_ticket_store
from .routers import all_routers


class Settings(BaseSettings):
    app_name: str = "Reelix Discovery Agent API"
    # credentials
    qdrant_endpoint: str | None = None
    qdrant_api_key: str | None = None
    supabase_url: str | None = None
    supabase_api_key: str | None = None
    openai_api_key: str | None = None
    # ticket_store config
    use_redis_ticket_store: bool = False
    redis_url: str | None = None
    ticket_namespace: str = "disc:ticket:"
    ticket_ttl_abs: int = 3600  # 60 min absolute cap
    # env conifg
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def _should_init_recommendation() -> bool:
    flag = os.getenv("REELIX_SKIP_RECOMMENDER_INIT", "")
    return flag.strip().lower() not in {"1", "true", "yes"}


def _init_recommendation_stack(app: FastAPI) -> None:
    import nltk

    from reelix_models.custom_models import (
        load_bm25_files,
        load_cross_encoder,
        load_sentence_model,
        setup_intent_classifier,
    )
    from reelix_recommendation.recommend import RecommendPipeline
    from reelix_retrieval.base_retriever import BaseRetriever
    from reelix_retrieval.query_encoder import Encoder
    from reelix_recommendation.recipes import InteractiveRecipe, ForYouFeedRecipe
    from openai import OpenAI
    from reelix_models.llm_completion import OpenAIChatLLM

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    startup_t0 = time.perf_counter()

    required = {
        "QDRANT_ENDPOINT": app.state.settings.qdrant_endpoint,
        "QDRANT_API_KEY": app.state.settings.qdrant_api_key,
        "SUPABASE_URL": app.state.settings.supabase_url,
        "SUPABASE_API_KEY": app.state.settings.supabase_api_key,
        "OPENAI_API_KEY": app.state.settings.openai_api_key,
    }
    missing = [
        name for name, value in required.items() if not (value and value.strip())
    ]
    if missing:
        raise RuntimeError(
            "Missing API keys in environment: " + ", ".join(sorted(missing))
        )

    nltk_data_path = str(NLTK_PATH)
    if nltk_data_path not in nltk.data.path:
        nltk.data.path.append(nltk_data_path)

    intent_classifier = setup_intent_classifier()
    embed_model = load_sentence_model()
    bm25_models, bm25_vocabs = load_bm25_files()
    query_encoder = Encoder(embed_model, bm25_models, bm25_vocabs)
    cross_encoder = load_cross_encoder()
    openai_client = OpenAI(api_key=app.state.settings.openai_api_key)
    chat_completion_llm = OpenAIChatLLM(
        openai_client, request_timeout=60.0, max_retries=2
    )

    app.state.qdrant = QdrantClient(
        url=app.state.settings.qdrant_endpoint,
        api_key=app.state.settings.qdrant_api_key,
    )

    base_retriever = BaseRetriever(
        app.state.qdrant,
        movie_collection=QDRANT_MOVIE_COLLECTION_NAME,
        tv_collection=QDRANT_TV_COLLECTION_NAME,
        dense_vector_name="dense_vector",
        sparse_vector_name="sparse_vector",
    )
    pipeline = RecommendPipeline(base_retriever, ce_model=cross_encoder, rrf_k=60)

    app.state.supabase_url = app.state.settings.supabase_url
    app.state.supabase_api_key = app.state.settings.supabase_api_key

    app.state.intent_classifier = intent_classifier
    app.state.embed_model = embed_model
    app.state.bm25_models = bm25_models
    app.state.bm25_vocabs = bm25_vocabs
    app.state.query_encoder = query_encoder
    app.state.cross_encoder = cross_encoder
    app.state.recommend_pipeline = pipeline
    app.state.recipes = {
        "for_you_feed": ForYouFeedRecipe(query_encoder=app.state.query_encoder),
        "interactive": InteractiveRecipe(query_encoder=app.state.query_encoder),
    }
    app.state.chat_completion_llm = chat_completion_llm

    # create the ticket store
    # use_redis_env = os.getenv("USE_REDIS_TICKET_STORE", "").lower() in {"1", "true", "yes"}
    # redis_url = os.getenv("REDIS_URL") or (app.state.settings.redis_url or "")

    app.state.ticket_store = make_ticket_store(
        use_redis=app.state.settings.use_redis_ticket_store,
        redis_url=app.state.settings.redis_url,
        namespace=app.state.settings.ticket_namespace,
        absolute_ttl_sec=app.state.settings.ticket_ttl_abs,
        # Optional redis client kwargs for timeouts:
        # client_kwargs={"socket_connect_timeout": 2, "socket_timeout": 3} if use_redis else None,
    )

    print(f"🔧 Total startup time: {time.perf_counter() - startup_t0:.2f}s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(find_dotenv(), override=False)

    settings = Settings()
    app.state.settings = settings

    # Eager init of external clients/models
    if _should_init_recommendation():
        try:
            _init_recommendation_stack(app)
        except ModuleNotFoundError as exc:
            missing = exc.name or "dependency"
            raise RuntimeError(
                f"Missing dependency '{missing}' required for recommendation bootstrap. "
                "Install it or set REELIX_SKIP_RECOMMENDER_INIT=1 to skip initialization."
            ) from exc
    else:
        print(
            "⚠️ Recommendation stack initialization skipped by REELIX_SKIP_RECOMMENDER_INIT"
        )

    try:
        yield
    finally:
        # Place for cleanup if needed in future
        pass


app = FastAPI(title="Reelix Discovery Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version="0.1.0",
        description="Reelix Discovery Agent API",
        routes=app.routes,
    )
    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            operation.setdefault("security", []).append({"BearerAuth": []})
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi


@app.get("/health")
def health():
    s = app.state.settings
    return {"status": "ok", "service": s.app_name}


@app.get("/")
def read_root():
    return {"status": "ok"}


for r in all_routers:
    app.include_router(r)
