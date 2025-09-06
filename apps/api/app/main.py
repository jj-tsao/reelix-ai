from fastapi import FastAPI
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "Reelix Discovery Agent API"
    class Config:
        env_file = ".env"

settings = Settings()
app = FastAPI(title=settings.app_name)

@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}
