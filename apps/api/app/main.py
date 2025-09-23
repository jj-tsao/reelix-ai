from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient

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

    try:
        yield
    finally:
        # Place for cleanup if needed in future
        pass


app = FastAPI(title="Reelix Discovery Agent API", lifespan=lifespan)


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
