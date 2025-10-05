from reelix_core.types import UserTasteContext
from reelix_retrieval.query_encoder import Encoder as QueryEncoder
from reelix_recommendation.base_recipe import BaseRecipe
from reelix_core.types import QueryFilter, LLMPrompts
from reelix_models.system_prompts import get_system_prompt


class ForYouFeedRecipe(BaseRecipe):
    name = "for_you_feed"

    def __init__(self, query_encoder: QueryEncoder):
        self.query_encoder = query_encoder

    def build_inputs(
        self,
        *,
        media_type: str,
        query_text: str | None,
        query_filter: QueryFilter | None,
        user_context: UserTasteContext | None,
    ):
        if not user_context:
            raise ValueError("ForYouFeedRecipe requires user_context")

        dense_vec = user_context.taste_vector
        bm25_bag = self.build_bm25_query(
            genres=user_context.signals.genres_include,
            keywords=user_context.signals.keywords_include,
        )
        sparse_vec = self.query_encoder.encode_sparse(bm25_bag, media_type)

        if user_context.provider_filter_mode == "SELECTED":
            subs = user_context.active_subscriptions
            filters = self.build_filter(QueryFilter(genres=[], providers=subs))
        else:
            filters = self.build_filter()

        return dense_vec, sparse_vec, filters

    def pipeline_params(self):
        return dict(
            final_top_k=20,
            weights=dict(
                dense=0.45, sparse=0.15, rating=0.18, popularity=0.08, genre=0.14
            ),
        )

    def build_prompt(
        self, *, query_text: str, user_context: UserTasteContext, candidates
    ) -> LLMPrompts:
        system_prompt = get_system_prompt(recipe_name=self.name)

        context = self.format_context(candidates)
        user_message = f"Here is the user query: {query_text}\n\nHere are the candidate items:\n{context}"

        return LLMPrompts(system=system_prompt, user=user_message)


class InteractiveRecipe(BaseRecipe):
    name = "interactive"

    def __init__(self, query_encoder: QueryEncoder):
        self.query_encoder = query_encoder

    def build_inputs(
        self,
        *,
        media_type: str,
        query_text: str | None,
        query_filter: QueryFilter | None,
        user_context: UserTasteContext | None,
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
        return dict(
            final_top_k=20,
            weights=dict(
                dense=0.60, sparse=0.10, rating=0.20, popularity=0.10, genre=0.00
            ),
        )

    def build_prompt(
        self, *, query_text: str, user_context: UserTasteContext, candidates
    ) -> LLMPrompts:
        system_prompt = get_system_prompt(recipe_name=self.name)

        context = self.format_context(candidates)
        user_message = f"Here is the user query: {query_text}\n\nHere are the candidate items:\n{context}"

        return LLMPrompts(system=system_prompt, user=user_message)
