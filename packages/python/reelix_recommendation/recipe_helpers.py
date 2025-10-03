from qdrant_client.models import Filter as QFilter
from reelix_retrieval.qdrant_filter import build_qfilter
from reelix_core.types import QueryFilter


def build_filter(query_filter: QueryFilter) -> QFilter:
    qfilter = build_qfilter(
        genres=query_filter.genres,
        providers=query_filter.providers,
        year_range=query_filter.year_range,
    )
    return qfilter
