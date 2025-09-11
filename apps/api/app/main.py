from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Reelix Discovery Agent API"
    # Ignore unrelated env vars (e.g., SUPABASE_URL keys) to prevent validation errors
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
app = FastAPI(title=settings.app_name)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


# Routers
from .routers.profile import router as profile_router  # noqa: E402

app.include_router(profile_router)
