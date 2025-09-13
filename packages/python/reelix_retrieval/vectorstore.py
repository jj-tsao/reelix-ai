from qdrant_client import QdrantClient


def connect_qdrant(api_key: str, endpoint: str) -> QdrantClient:
    try:
        client = QdrantClient(
            url=endpoint,
            api_key=api_key
        )
        print ("✅ Connected to Qdrant.")
        return client
    except Exception as e:
        print(f"❌ Error connecting to Qdrant: {e}")
        raise
