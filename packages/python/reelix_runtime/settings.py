from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    """Shared settings for any process hosting the recommendation stack."""

    # credentials
    qdrant_endpoint: str | None = None
    qdrant_api_key: str | None = None
    supabase_url: str | None = None
    supabase_api_key: str | None = None
    openai_api_key: str | None = None
    redis_url: str | None = None

    # redis store config
    ticket_namespace: str = "reelix:ticket:"
    why_cache_namespace: str = "reelix:why:"
    session_namespace: str = "reelix:agent:session:"
    ticket_ttl_sec: int = 3600  # 60 min cap
    session_ttl_sec: int = 7 * 24 * 3600  # 7d cap
    why_cache_ttl_sec: int = 14 * 24 * 3600  # 2 weeks cap

    # env config
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
