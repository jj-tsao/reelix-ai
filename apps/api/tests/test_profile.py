from typing import Any, Dict
import os


def test_upsert_preferences_success(test_client):
    payload: Dict[str, Any] = {
        "year_min": 1990,
        "year_max": 2024,
        "genres_include": ["action"],
        "include_movies": True,
        "diversity_level": 1,
    }
    res = test_client.post("/profile/preferences", json=payload)
    assert res.status_code == 200
    data = res.json()
    # Should echo back fields in snake_case
    assert data["year_min"] == 1990
    assert data["year_max"] == 2024
    assert data["genres_include"] == ["action"]


def test_upsert_subscriptions_success(test_client):
    payload = {
        "subscriptions": [
            {"provider_id": "netflix", "active": True},
            {"provider_id": "max", "active": False},
        ]
    }
    res = test_client.post("/profile/subscriptions", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list) and len(data) == 2
    providers = {row["provider_id"] for row in data}
    assert providers == {"netflix", "max"}


def test_insert_interactions_success(test_client):
    payload = {
        "interactions": [
            {
                "media_type": "movie",
                "tmdb_id": 603,
                "event_type": "like",
                "weight": 1.0,
            },
            {"media_type": "tv", "tmdb_id": 1396, "event_type": "view"},
        ]
    }
    res = test_client.post("/profile/interactions", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["tmdb_id"] == 603
    assert data[1]["media_type"] == "tv"


def test_preferences_bad_range_400(test_client):
    # runtime_min > runtime_max should trigger 400 via pydantic validation
    payload = {"runtime_min": 200, "runtime_max": 100}
    res = test_client.post("/profile/preferences", json=payload)
    assert res.status_code == 422  # FastAPI validation error


def test_rls_forbidden_maps_403(test_client, monkeypatch):
    # Make the fake client raise a permission error when executing
    class ForbiddenExc(Exception):
        code = "PGRST301"

        def __init__(self):
            self.message = "permission denied"

    class FailingQuery:
        def upsert(self, *_, **__):
            return self

        def select(self, *_):
            return self

        def execute(self):
            raise ForbiddenExc()

    class FailingClient:
        def table(self, *_):
            return FailingQuery()

    def _override_client():
        return FailingClient()

    from apps.api.app.repositories.supabase_client import get_supabase_client, get_current_user_id
    from app.main import app
    from fastapi.testclient import TestClient

    os.environ.setdefault("QDRANT_ENDPOINT", "http://localhost:6333")
    os.environ.setdefault("QDRANT_API_KEY", "test_qdrant_key")
    os.environ.setdefault("SUPABASE_URL", "http://localhost")
    os.environ.setdefault("SUPABASE_ANON_KEY", "test_anon_key")

    app.dependency_overrides[get_supabase_client] = _override_client
    app.dependency_overrides[get_current_user_id] = (
        lambda: "00000000-0000-0000-0000-000000000000"
    )

    with TestClient(app) as c:
        res = c.post("/profile/preferences", json={"include_movies": True})
        assert res.status_code == 403
        assert res.json()["detail"] == "forbidden/ownership"


def test_missing_token_401_enforced():
    # Build a client without dependency overrides so require_bearer_token is active
    import os
    from fastapi.testclient import TestClient

    # Ensure env is present before importing app
    os.environ.setdefault("QDRANT_ENDPOINT", "http://localhost:6333")
    os.environ.setdefault("QDRANT_API_KEY", "test_qdrant_key")
    os.environ.setdefault("SUPABASE_URL", "http://localhost")
    os.environ.setdefault("SUPABASE_ANON_KEY", "test_anon_key")
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/profile/preferences", json={"include_movies": True})
        assert r.status_code == 401
        assert "Authorization" in r.json()["detail"] or r.json()["detail"].startswith(
            "Missing"
        )
