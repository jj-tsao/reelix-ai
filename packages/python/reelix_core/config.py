import os
from typing import Final

def env_str(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

QDRANT_API_KEY: Final[str]   = env_str("QDRANT_API_KEY")
QDRANT_ENDPOINT: Final[str]  = env_str("QDRANT_ENDPOINT")

QDRANT_MOVIE_COLLECTION_NAME = "Movies_BGE_AUG-RE"
QDRANT_TV_COLLECTION_NAME = "TV_Shows_BGE_AUG-RE"