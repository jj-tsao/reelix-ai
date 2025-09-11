from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from .routers import all_routers

class Settings(BaseSettings):
    app_name: str = "Reelix Discovery Agent API"
    # Ignore unrelated env vars to prevent validation errors
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
app = FastAPI(title=settings.app_name)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


for r in all_routers:
    app.include_router(r)
