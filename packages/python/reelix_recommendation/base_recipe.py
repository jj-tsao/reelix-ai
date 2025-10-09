import time
import json
import hashlib
from typing import Dict, Any, List
from reelix_core.types import QueryFilter, UserTasteContext, UserSignals, PromptsEnvelope, LLMCall
from reelix_core.config import CHAT_COMPLETION_MODEL


class BaseRecipe:
    # == Retrieval helpers ==
    def build_filter(self, query_filter: QueryFilter | None = None):
        from reelix_recommendation.recipe_helpers import build_filter

        return build_filter(query_filter)
    
    def build_discover_filter(self, user_context: UserTasteContext):
        from reelix_recommendation.recipe_helpers import build_discover_filter
        
        return build_discover_filter(user_context)

    def build_bm25_query(self, genres, keywords):
        from reelix_recommendation.recipe_helpers import build_bm25_query

        return build_bm25_query(genres, keywords)

    # == LLM prompt builders ==
    def get_system_prompt(self, recipe_name):
        from reelix_models.system_prompts import get_system_prompt

        return get_system_prompt(recipe_name=recipe_name)

    def build_user_prompt(
        self,
        *,
        recipe_name: str,
        candidates: list,
        query_text: str | None = None,
        user_signals: UserSignals | None = None,
    ):
        from reelix_models.user_prompts import build_for_you_user_prompt
        from reelix_models.user_prompts import build_interactive_user_prompt

        if recipe_name == "for_you_feed":
            if not user_signals:
                raise ValueError("ForYouFeedRecipe requires user_signals")
            else:
                return build_for_you_user_prompt(
                    candidates=candidates, user_signals=user_signals
                )

        if recipe_name == "interactive":
            if not query_text:
                raise ValueError("Interactive requires query_text")
            else:
                return build_interactive_user_prompt(
                    query_text=query_text, candidates=candidates
                )

        else:
            raise ValueError("LLM prompt build failed: unknown recipe.")

    # build the prompt envelope for ticket_store
    def build_prompt_envelope(
        self,
        recipe_name: str,
        system_prompt,
        user_prompt,
        candidates,
        llm_model: str = CHAT_COMPLETION_MODEL,
        llm_params: dict[str, Any] | None = None,
    ) -> PromptsEnvelope:
        items_brief: List[Dict[str, Any]] = []
        for c in candidates:
            p = getattr(c, "payload", {}) or {}
            items_brief.append(
                {
                    "media_id": p.get("media_id") or getattr(c, "id", None),
                    "title": p.get("title") or p.get("name") or "Unknown",
                }
            )

        params = {"temperature": 0.7, "top_p": 1.0}
        if llm_params:
            params.update(llm_params)

        call = LLMCall(
            call_id=1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            items_brief=items_brief,
        )

        envelope = PromptsEnvelope(
            model=llm_model,
            params=params,
            recipe={"name": recipe_name, "version": "v1"},
            output={"format": "jsonl", "schema_version": "1"},
            calls=[call],
            prompt_hash=self._prompt_hash(
                model=llm_model,
                params=params,
                recipe={"name": recipe_name, "version": "v1"},
                output={"format": "jsonl", "schema_version": "1"},
                calls=[call],
            ),
            created_at=time.time(),
        )
        return envelope

    def _prompt_hash(
        self,
        *,
        model: str,
        params: Dict[str, Any],
        recipe: Dict[str, Any],
        output: Dict[str, Any],
        calls: List[LLMCall],
    ) -> str:
        """
        Canonicalize the parts that affect generation for deterministic traceability.
        """
        canon = {
            "model": model,
            "params": params,
            "recipe": recipe,
            "output": output,
            "calls": [
                {"messages": c.messages}  # only messages affect model behavior
                for c in calls
            ],
        }
        b = json.dumps(
            canon, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(b).hexdigest()
