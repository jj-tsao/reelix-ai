from fastapi import Request
from reelix_recommendation.recommend import RecommendPipeline
from schemas import UserTasteContext, QueryFilter


def orchestrate(
    request: Request, 
    *,
    kind: str,
    media_type: str,
    query_text: str | None = None,
    query_filter: QueryFilter | None = None,
    user_id: str | None = None,
    user_context: UserTasteContext | None = None,
    pipeline: RecommendPipeline,
):
    recipe = request.app.state.recipes[kind]
    dense_vec, sparse_vec, filters = recipe.build_inputs(
        media_type=media_type, query_text=query_text, query_filters=query_filter, user_id=user_id, user_context=user_context
    )
    params = recipe.pipeline_params()

    final, traces = pipeline.run(
        query_text=query_text or "[PROFILE-BASED]",
        dense_vec=dense_vec,
        sparse_vec=sparse_vec,
        media_type=media_type,
        genres=filters.get("genres"),
        providers=filters.get("providers"),
        year_range=filters.get("year_range"),
        **params,
    )
    # plan = recipe.build_prompt_plan(
    #     query_text, user_context, final
    # )  # {mode: none|oneshot|stream, user_message: str}
    return final, traces #, plan
