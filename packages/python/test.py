import os

from dotenv import find_dotenv, load_dotenv
from reelix_retrieval.vectorstore import connect_qdrant
from reelix_retrieval.embedding_loader import load_embeddings_qdrant
from reelix_user.taste_profile import build_taste_vector

load_dotenv(find_dotenv(), override=False)

QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_ENDPOINT = os.getenv("QDRANT_ENDPOINT")

qdrant = connect_qdrant(QDRANT_API_KEY, QDRANT_ENDPOINT)

embds = load_embeddings_qdrant(qdrant, "movie", [11, 12])

