from pathlib import Path


QDRANT_MOVIE_COLLECTION_NAME = "Movies_BGE_AUG-RE"
QDRANT_TV_COLLECTION_NAME = "TV_Shows_BGE_AUG-RE"

INTENT_MODEL = "JJTsao/intent-classifier-distilbert-movierec"  # Fine-tuned intent classification model for query intent classifiation
EMBEDDING_MODEL = "JJTsao/fine-tuned_movie_retriever-bge-base-en-v1.5"  # Fine-tuned sentence transfomer model for query dense vector embedding
RERANKER_MODEL = "JJTsao/movietv-reranker-cross-encoder-base-v1"
CHAT_COMPLETION_MODEL = "gpt-4o-mini"

NLTK_PATH = Path(__file__).resolve().parent.parent / "reelix_models" / "assets" / "nltk_data"
BM25_PATH = Path(__file__).resolve().parent.parent / "reelix_models" / "assets" / "bm25_files"
