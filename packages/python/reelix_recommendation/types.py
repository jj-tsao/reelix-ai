from typing import Protocol, Tuple, Dict, Any, List, runtime_checkable
from qdrant_client.models import Filter as QFilter
from reelix_core.types import UserTasteContext, QueryFilter, PromptsEnvelope

SparseVec = Dict[str, List[float]]


@runtime_checkable
class OrchestrationRecipe(Protocol):
    name: str

    def build_inputs(
        self,
        *,
        media_type: str,
        query_text: str | None = None,
        query_filter: QueryFilter | None = None,
        user_context: UserTasteContext | None = None,
    ) -> Tuple[List[float], SparseVec, QFilter]: ...

    def pipeline_params(self) -> Dict[str, Any]: ...

    def build_prompt(
        self,
        *,
        query_text: str | None = None,
        user_context: UserTasteContext | None = None,
        candidates,
    ) -> PromptsEnvelope: ...
