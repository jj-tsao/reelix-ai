import re
from typing import Iterable, List
from qdrant_client.models import Filter as QFilter
from reelix_retrieval.qdrant_filter import build_qfilter
from reelix_core.types import QueryFilter, UserTasteContext


def build_filter(query_filter: QueryFilter | None = None) -> QFilter:
    if query_filter:
        qfilter = build_qfilter(
            genres=query_filter.genres,
            providers=query_filter.providers,
            year_range=query_filter.year_range,
        )
    else:
        qfilter = build_qfilter()
    return qfilter


def format_rec_context(candidates: list):
    context = "\n\n".join([c.payload.get("llm_context", "") for c in candidates])
    return context


def format_discover_context(user_context: UserTasteContext, candidates: list):
    genres = ", ".join([g for g in user_context.signals.genres_include])
    keywords = ", ".join([k for k in user_context.signals.keywords_include])
    pos = ", ".join([k for k in user_context.signals.keywords_include])
    context = f"The user enjoyes {genres} genres, and themes of {keywords}"
    
    context += "\n\n".join([c.payload.get("embedding_text", "") for c in candidates])
    return context


def build_bm25_query(
    genres_include: Iterable[str],
    keywords_include: Iterable[str],
    *,
    boost_keywords: int = 2,
) -> str:
    def _clean(s: str) -> str:
        s = s.strip().lower()
        s = s.replace("-", " ")
        s = re.sub(r"\s+", " ", s)
        return s

    # 1) normalize + de-dupe
    gen = sorted({_clean(g) for g in genres_include or [] if g and g.strip()})
    kws = sorted({_clean(k) for k in keywords_include or [] if k and k.strip()})

    # 2) gentle boosting (dup up to tf_clip=3 total occurrences)
    boosted_keywords = []
    for k in kws:
        # ensure at most 3 total repeats later; keep this modest
        boosted_keywords.extend([k] * max(1, min(boost_keywords, 2)))

    # 4) assemble — just a space-separated string (your tokenizer lowercases,
    # strips punctuation, removes stopwords, and Porter-stems later). :contentReference[oaicite:5]{index=5}
    bag: List[str] = []
    bag.extend(gen)  # genres once each
    bag.extend(boosted_keywords)  # keywords (lightly boosted + expanded)

    return " ".join(bag).strip()
