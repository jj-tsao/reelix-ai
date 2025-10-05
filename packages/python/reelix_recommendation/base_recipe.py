from reelix_core.types import QueryFilter


class BaseRecipe:
    def build_filter(self, query_filter: QueryFilter|None = None):
        from reelix_recommendation.recipe_helpers import build_filter

        return build_filter(query_filter)
    
    def format_context(self, candidates: list):
        from reelix_recommendation.recipe_helpers import format_context
        
        return format_context(candidates)
    
    def build_bm25_query(self, genres, keywords):
        from reelix_recommendation.recipe_helpers import build_bm25_query
        
        return build_bm25_query(genres, keywords)

    # def profile_block(self, ctx):
    #     from app.rec.helpers import build_profile_block
    #     return build_profile_block(ctx)
