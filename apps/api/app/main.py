import os
import time
from contextlib import asynccontextmanager

import nltk
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
from .routers import all_routers


class Settings(BaseSettings):
    app_name: str = "Reelix Discovery Agent API"
    qdrant_endpoint: str | None = None
    qdrant_api_key: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(find_dotenv(), override=False)

    settings = Settings()
    app.state.settings = settings

    if not settings.qdrant_endpoint or not settings.qdrant_api_key:
        raise RuntimeError("Missing QDRANT_ENDPOINT or QDRANT_API_KEY")

    # Eager init of external clients/models
    app.state.qdrant = QdrantClient(
        url=settings.qdrant_endpoint, api_key=settings.qdrant_api_key
    )

    # Initialize recommendation stack
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    startup_t0 = time.perf_counter()

    nltk_data_path = str(NLTK_PATH)
    if nltk_data_path not in nltk.data.path:
        nltk.data.path.append(nltk_data_path)

    from reelix_models.custom_models import (
        load_bm25_files,
        load_cross_encoder,
        load_sentence_model,
        setup_intent_classifier,
    )
    from reelix_recommendation.recommend import RecommendPipeline

    # from reelix_recommendation.chat import build_chat_fn
    from reelix_retrieval.base_retriever import BaseRetriever
    from reelix_retrieval.query_encoder import Encoder

    intent_classifier = setup_intent_classifier()
    embed_model = load_sentence_model()
    bm25_models, bm25_vocabs = load_bm25_files()
    query_encoder = Encoder(embed_model, bm25_models, bm25_vocabs)
    cross_encoder = load_cross_encoder()

    base_retriever = BaseRetriever(
        app.state.qdrant,
        movie_collection=QDRANT_MOVIE_COLLECTION_NAME,
        tv_collection=QDRANT_TV_COLLECTION_NAME,
        dense_vector_name="dense_vector",
        sparse_vector_name="sparse_vector",
    )
    pipeline = RecommendPipeline(base_retriever, ce_model=cross_encoder, rrf_k=60)
    # chat_fn = build_chat_fn(
    #     pipeline=pipeline,
    #     intent_classifier=intent_classifier,
    #     query_encoder=query_encoder,
    # )

    app.state.intent_classifier = intent_classifier
    app.state.embed_model = embed_model
    app.state.bm25_models = bm25_models
    app.state.bm25_vocabs = bm25_vocabs
    app.state.query_encoder = query_encoder
    app.state.cross_encoder = cross_encoder
    app.state.recommend_pipeline = pipeline
    # app.state.chat_fn = chat_fn

    print(f"🔧 Total startup time: {time.perf_counter() - startup_t0:.2f}s")

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


for r in all_routers:
    app.include_router(r)
