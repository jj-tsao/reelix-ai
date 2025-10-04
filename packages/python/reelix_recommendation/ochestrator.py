from typing import Tuple, List, Dict
from reelix_recommendation.types import OrchestrationRecipe
from reelix_recommendation.recommend import RecommendPipeline
from reelix_core.types import UserTasteContext, QueryFilter
from reelix_ranking.types import Candidate, ScoreTrace

def orchestrate(
    *,
    recipe: OrchestrationRecipe,
    media_type: str,
    query_text: str | None = None,
    query_filter: QueryFilter | None = None,
    user_id: str | None = None,
    user_context: UserTasteContext | None = None,
    pipeline: RecommendPipeline,
)-> Tuple[List[Candidate], Dict[str, ScoreTrace]]:
    dense_vec, sparse_vec, qfilter = recipe.build_inputs(
        media_type=media_type,
        query_text=query_text,
        query_filter=query_filter,
        user_context=user_context,
    )
    params = recipe.pipeline_params()
    final, traces = pipeline.run(
        media_type=media_type,
        dense_vec=dense_vec,
        sparse_vec=sparse_vec,
        query_text=query_text,
        qfilter=qfilter,
        **params,
    )

    # plan = recipe.build_prompt_plan(
    #     query_text, user_context, final
    # )  # {mode: none|oneshot|stream, user_message: str}
    return final, traces  # , plan
