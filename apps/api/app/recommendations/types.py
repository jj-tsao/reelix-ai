from typing import Protocol, Tuple, Dict, Any, List, runtime_checkable
from qdrant_client.models import Filter as QFilter
from reelix_core.types import UserTasteContext
from schemas import QueryFilter

SparseVec = Dict[str, List[float]]


@runtime_checkable
class OrchestrationRecipe(Protocol):
    name: str

    def build_inputs(
        self,
        *,
        media_type: str,
        query_text: str|None = None,
        query_filter: QueryFilter|None = None,
        user_context: UserTasteContext|None = None,
    ) -> Tuple[List[float], SparseVec, QFilter]: ...

    # def build_prompt(
    #     self,
    #     *,
    #     query_text: Optional[str],
    #     user_ctx: Optional[UserTasteContext],
    #     candidates,
    # ) -> str: ...

    def pipeline_params(self) -> Dict[str, Any]: ...
