from reelix_core.types import UserTasteContext
from reelix_retrieval.query_encoder import Encoder as QueryEncoder
from app.recommendations.base_recipe import BaseRecipe
from schemas import QueryFilter


class InteractiveRecipe(BaseRecipe):
    name = "interactive"

    def __init__(self, query_encoder: QueryEncoder):
        self.query_encoder = query_encoder
        
    def build_inputs(
        self,
        *,
        media_type: str,
        query_text: str|None = None,
        query_filter: QueryFilter|None = None,
        user_context: UserTasteContext|None = None,
    ):
        if not query_text or not query_filter:
            raise ValueError("InteractiveRecipe requires query_text and query_filter")

        dense_vec, sparse_vec = self.query_encoder.dense_and_sparse(
            text=query_text, media_type=media_type
        )

        # if user_context:
        #     c_sparse = self.ctx_to_sparse(user_ctx, media_type) if user_ctx else None
        #     sparse = merge_sparse(q_sparse, c_sparse, alpha=0.3) if c_sparse else q_sparse

        filters = self.build_filter(query_filter)
        return dense_vec, sparse_vec, filters

    def pipeline_params(self):
        return dict(final_top_k=20)

    # def build_prompt(self, *, query_text, user_ctx, candidates):
    #     return build_llm_prompt(query_text, user_ctx, candidates, mode="interactive")
