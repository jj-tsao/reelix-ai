import logging

from qdrant_client import QdrantClient

log = logging.getLogger(__name__)


def connect_qdrant(api_key: str, endpoint: str) -> QdrantClient:
    try:
        client = QdrantClient(
            url=endpoint,
            api_key=api_key
        )
        log.info("✅ Connected to Qdrant.")
        return client
    except Exception as e:
        log.error("❌ Error connecting to Qdrant: %s", e)
        raise
