import os
from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError as PgRestError
from reelix_core.errors import DomainError

from reelix_runtime import (
    RuntimeSettings,
    build_recommendation_runtime,
    build_stores,
    build_telemetry,
)
from app.observability import init_tracing
from .routers import all_routers


class Settings(RuntimeSettings):
    app_name: str = "Reelix Discovery Agent API"


def _should_init_recommendation() -> bool:
    flag = os.getenv("REELIX_SKIP_RECOMMENDER_INIT", "")
    return flag.strip().lower() not in {"1", "true", "yes"}


def _init_recommendation_stack(app: FastAPI) -> None:
    runtime = build_recommendation_runtime(app.state.settings)
    stores = build_stores(app.state.settings)

    app.state.qdrant = runtime.qdrant
    app.state.query_encoder = runtime.query_encoder
    app.state.recommend_pipeline = runtime.recommend_pipeline
    app.state.agent_rec_runner = runtime.agent_rec_runner
    app.state.recipes = runtime.recipes
    app.state.tool_registry = runtime.tool_registry
    app.state.tool_runner = runtime.tool_runner

    app.state.ticket_store = stores.ticket_store
    app.state.state_store = stores.state_store
    app.state.why_cache = stores.why_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings

    http_client, logger = build_telemetry(settings, timeout_s=5.0)
    app.state.logger = logger

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
        await http_client.aclose()
        await app.state.why_cache.aclose()


load_dotenv(find_dotenv(), override=False)

app = FastAPI(title="Reelix Discovery Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://reelixai.netlify.app", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_tracing(app)


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


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": str(exc)}},
    )


@app.exception_handler(PgRestError)
async def postgrest_error_handler(request: Request, exc: PgRestError):
    # Fallback if any PgRestError leaks past the repo mapping
    status = 400 if getattr(exc, "code", "") in ("22P02", "23502") else 500
    return JSONResponse(
        status_code=status,
        content={"error": {"code": "db_error", "message": "database error"}},
    )


@app.get("/health")
def health():
    s = app.state.settings
    return {"status": "ok", "service": s.app_name}


@app.get("/")
def read_root():
    s = app.state.settings
    return {"status": "ok", "service": s.app_name}


for r in all_routers:
    app.include_router(r)
