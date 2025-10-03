from schemas import QueryFilter

class BaseRecipe:
    def build_filter(self, query_filter: QueryFilter):
        from recipe_helpers import build_filter
        return build_filter(query_filter)
    
    # def ctx_to_sparse(self, ctx, media_type):
    #     from app.rec.helpers import sparse_from_context
    #     return sparse_from_context(ctx, media_type)

    # def profile_block(self, ctx):
    #     from app.rec.helpers import build_profile_block
    #     return build_profile_block(ctx)
