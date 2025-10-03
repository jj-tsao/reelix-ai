# app/rec/recipes.py
from fastapi import Depends
from reelix_core.types import UserTasteContext
from base_recipe import BaseRecipe
from deps import get_query_encoder
from schemas import QueryFilter
# from app.rec.helpers import merge_sparse, build_llm_prompt


class InteractiveRecipe(BaseRecipe):  # inherits helpers, no ABC required
    name = "interactive"

    def build_inputs(
        self,
        *,
        media_type: str,
        query_text: str,
        query_filter: QueryFilter,
        user_id: str | None,
        user_context: UserTasteContext | None,
        query_encoder=Depends(get_query_encoder),
    ):
        dense_vec, sparse_vec = query_encoder.dense_and_sparse(query_text, media_type)

        # if user_context:
        #     c_sparse = self.ctx_to_sparse(user_ctx, media_type) if user_ctx else None
        #     sparse = merge_sparse(q_sparse, c_sparse, alpha=0.3) if c_sparse else q_sparse

        filters = self.build_filter(query_filter)
        return dense_vec, sparse_vec, filters

    def pipeline_params(self):
        return dict(final_top_k=20)

    def build_prompt(self, *, query_text, user_ctx, candidates):
        return build_llm_prompt(query_text, user_ctx, candidates, mode="interactive")
