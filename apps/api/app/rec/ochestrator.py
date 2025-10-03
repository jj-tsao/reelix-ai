from fastapi import Depends
from deps import get_recommend_pipeline
from registry import get_recipe
from schemas import UserTasteContext, QueryFilters


def orchestrate(*, kind: str, media_type: str, query_text: str|None, user_id: str|None, user_ctx: UserTasteContext|None, query_filters:QueryFilters|None, pipeline = Depends(get_recommend_pipeline)):
    recipe = get_recipe(kind)
    dense_vec, sparse_vec, filters = recipe.build_inputs(media_type, query_text, user_ctx, query_filters)
    params = recipe.pipeline_params()

    final, traces = pipeline.run(
        query_text=query_text or "[PROFILE-BASED]",
        dense_vec=dense_vec,
        sparse_vec=sparse_vec,
        media_type=media_type,
        genres=filters.get("genres"), providers=filters.get("providers"),
        year_range=filters.get("year_range"),
        **params,
    )
    plan = recipe.build_prompt_plan(query_text, user_ctx, final)  # {mode: none|oneshot|stream, user_message: str}
    return final, traces, plan
