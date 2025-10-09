from typing import List, Optional, Tuple
from qdrant_client.models import (
    Filter as QFilter,
    models as qmodels,
    FieldCondition,
    Range,
)


def build_qfilter(
    exclude_ids: Optional[List[int]] = None,
    genres: Optional[List[str]] = None,
    providers: Optional[List[int]] = None,
    year_range: Optional[Tuple[int, int]] = (1970, 2025),
    titles: Optional[List[str]] = None,
    release_year: Optional[int] = None,
) -> QFilter:
    must_not = []
    must = []

    if exclude_ids:
        must_not.append(FieldCondition(key="media_id", match=qmodels.MatchAny(any=list(exclude_ids))))
    
    if genres:
        must.append(
            FieldCondition(key="genres", match=qmodels.MatchAny(any=list(genres)))
        )

    if providers:
        must.append(
            FieldCondition(
                key="watch_providers", match=qmodels.MatchAny(any=list(providers))
            )
        )

    if year_range:
        start, end = year_range
        if start > end:
            start, end = end, start
        must.append(
            FieldCondition(
                key="release_year",
                range=Range(gte=int(start), lte=int(end)),
            )
        )

    if titles:
        must.append(
            FieldCondition(key="title", match=qmodels.MatchAny(any=list(titles)))
        )

    if release_year:
        must.append(
            FieldCondition(
                key="release_year", match=qmodels.MatchValue(value=int(release_year))
            )
        )

    return QFilter(must=must, must_not=must_not or None)
