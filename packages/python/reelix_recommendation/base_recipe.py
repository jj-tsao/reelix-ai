from reelix_core.types import QueryFilter, UserSignals


class BaseRecipe:
    # == Retrieval helpers ==
    def build_filter(self, query_filter: QueryFilter | None = None):
        from reelix_recommendation.recipe_helpers import build_filter

        return build_filter(query_filter)

    def build_bm25_query(self, genres, keywords):
        from reelix_recommendation.recipe_helpers import build_bm25_query

        return build_bm25_query(genres, keywords)

    # == LLM prompt builders ==
    def get_system_prompt(self, recipe_name):
        from reelix_models.system_prompts import get_system_prompt

        return get_system_prompt(recipe_name=recipe_name)

    def build_interactive_user_prompt(
        self, query_text: str, candidates: list, user_signals: UserSignals | None = None
    ):
        from reelix_models.user_prompts import build_interactive_user_prompt

        return build_interactive_user_prompt(
            query_text=query_text, candidates=candidates
        )

    def build_for_you_user_prompt(self, *, candidates: list, user_signals: UserSignals):
        from reelix_models.user_prompts import build_for_you_user_prompt

        return build_for_you_user_prompt(
            candidates=candidates, user_signals=user_signals
        )
