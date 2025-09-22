from fastapi import APIRouter, Depends, HTTPException
from qdrant_client import QdrantClient

from app.supabase_client import get_supabase_client, get_current_user_id
from app.deps import get_qdrant
from services.taste_profile_service import rebuild_and_store
from reelix_user.store import fetch as fetch_profile

router = APIRouter(prefix="/taste_profile", tags=["taste"])


def get_qdrant_client(q: QdrantClient = Depends(get_qdrant)) -> QdrantClient:
    return q

@router.get("/me")
async def get_my_profile(
    sb=Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
):
    row = await fetch_profile(sb, user_id)
    if not row:
        raise HTTPException(404, "Not found")
    return {
        "last_built_at": row["last_built_at"],
        "positive_n": row["positive_n"],
        "negative_n": row["negative_n"],
        "dim": len(row["dense"]),
    }

@router.post("/rebuild")
async def rebuild_my_profile(
    sb=Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
    qdrant: QdrantClient = Depends(get_qdrant_client),
):
    # from reelix_models.custom_models import load_sentence_model
    # model = load_sentence_model()
    # text_embedder = lambda texts: model.encode(list(texts), show_progress_bar=False).tolist()

    vec, debug = await rebuild_and_store(
        sb,  
        user_id,
        qdrant,
        collection="movies",
        # text_embedder=text_embedder,
    )
    return {"dim": int(vec.shape[0]), "pos_count": debug["pos_count"], "neg_count": debug["neg_count"]}
