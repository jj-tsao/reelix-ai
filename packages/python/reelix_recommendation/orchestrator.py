from typing import Tuple, List, Dict
from reelix_recommendation.types import OrchestrationRecipe
from reelix_recommendation.recommend import RecommendPipeline
from reelix_core.types import UserTasteContext, QueryFilter, LLMPrompts
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
) -> Tuple[List[Candidate], Dict[str, ScoreTrace], LLMPrompts]:
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

    def summarize_ranking(ranking: List[Candidate], top_k: int = 20):
        for idx, r in enumerate(ranking[:top_k], start=1):
            print(
                f"#{idx}: Title: {r.payload['title']} | Dense Score: {r.dense_score} | Sparse Score: {r.sparse_score} | Rating: {r.payload['vote_average']} | Popularity: {r.payload['popularity']}"
            )

    summarize_ranking(final)

    llm_prompts = recipe.build_prompt(
        query_text=query_text, user_context=user_context, candidates=final
    )

    print(llm_prompts.user)

    return final, traces, llm_prompts
