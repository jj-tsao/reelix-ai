import os
from collections import Counter
from typing import Dict, List

import joblib
from rank_bm25 import BM25Okapi

from reelix_retrieval.bm25_tokenizer import tokenize_for_bm25


def fit_and_save_bm25(
    media_type: str,
    corpus: List[str],
    bm25_dir: str,
):
    """Fit BM25 on the given corpus and save model + vocabulary.

    The BM25 model (IDF / doc-length stats) is always rebuilt from the
    current corpus.  If a vocabulary already exists on disk, new terms
    are appended with stable indices so that previously-stored sparse
    vectors in Qdrant remain compatible.
    """
    # Tokenize and process the corpus
    tokenized_corpus = [tokenize_for_bm25(doc) for doc in corpus]

    # Fit BM25 model on current corpus
    model = BM25Okapi(tokenized_corpus)

    # Load existing vocabulary or start fresh
    os.makedirs(bm25_dir, exist_ok=True)
    vocab_path = bm25_dir / f"{media_type}_bm25_vocab.joblib"

    if os.path.exists(vocab_path):
        vocab = joblib.load(vocab_path)
        next_index = max(vocab.values()) + 1 if vocab else 0
        print(f"Loaded existing vocabulary with {len(vocab)} terms from {bm25_dir}")
    else:
        vocab = {}
        next_index = 0

    # Extend vocabulary with any new terms
    for tokens in tokenized_corpus:
        for token in tokens:
            if token not in vocab:
                vocab[token] = next_index
                next_index += 1

    # Save model and vocabulary
    joblib.dump(model, bm25_dir / f"{media_type}_bm25_model.joblib")
    joblib.dump(vocab, vocab_path)

    print(f"BM25 model and vocabulary ({len(vocab)} terms) saved to {bm25_dir}")
    return model, vocab


def create_bm25_sparse_vector(
        document: str, 
        vocabulary: Dict[str, int], 
        bm25: BM25Okapi
):       
    # Tokenize corpus and document
    tokenized_document = tokenize_for_bm25(document)
    
    # Handle empty document case
    if not tokenized_document:
        print (f"Failed to tokenize document:'{document[:60]}'")
        return {'indices': [], 'values': []}

    # Calculate term frequencies (tf)
    term_counts = Counter(tokenized_document)

    # Calculate BM25 scores for each term in the document
    indices = []
    values = []
    
    for term, tf in term_counts.items():
        if term in vocabulary:
            term_index = vocabulary[term]
            idf = bm25.idf.get(term, 0)
            doc_length = len(tokenized_document)
            avg_doc_length = bm25.avgdl
            k1, b = bm25.k1, bm25.b
            
            # Standard BM25 formula
            numerator = idf * tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * doc_length / avg_doc_length)
            
            if denominator != 0:
                weight = numerator / denominator
                indices.append(term_index)
                values.append(float(weight))  # Ensure float type for DB compatibility
    
    # Ensure indices are sorted for DB efficiency
    if indices:
        # Sort by index
        sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
        indices, values = zip(*sorted_pairs)
        indices, values = list(indices), list(values)
        # density = len(indices) / len(vocabulary)
        # print(f"🧪 Sparse Vector Density: {len(indices)} terms / {len(vocabulary)} = {density:.4f}")
    
    return {'indices': indices, 'values': values}