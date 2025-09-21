from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI
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
    app.state.qdrant = QdrantClient(url=settings.qdrant_endpoint, api_key=settings.qdrant_api_key)

    try:
        yield
    finally:
        # Place for cleanup if needed in future
        pass


app = FastAPI(title="Reelix Discovery Agent API", lifespan=lifespan)


@app.get("/health")
def health():
    s = app.state.settings
    return {"status": "ok", "service": s.app_name}


for r in all_routers:
    app.include_router(r)