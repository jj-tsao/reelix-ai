QDRANT_MOVIE_COLLECTION_NAME = "Movies_BGE_AUG-RE"
QDRANT_TV_COLLECTION_NAME = "TV_Shows_BGE_AUG-RE"

INTENT_MODEL = "JJTsao/intent-classifier-distilbert-movierec"  # Fine-tuned intent classification model for query intent classifiation
EMBEDDING_MODEL = "JJTsao/fine-tuned_movie_retriever-bge-base-en-v1.5"  # Fine-tuned sentence transfomer model for query dense vector embedding
RERANKER_MODEL = "JJTsao/movietv-reranker-cross-encoder-base-v1"
OPENAI_MODEL = "gpt-4o-mini"
