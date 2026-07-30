"""Candidate view helpers shared across transports."""


def item_view(c) -> dict:
    """Convert a candidate to a JSON-serializable item view."""
    p = c.payload or {}
    return {
        "id": c.id,
        "media_id": p.get("media_id"),
        "title": p.get("title"),
        "release_year": p.get("release_year"),
        "genres": p.get("genres", []),
        "imdb_rating": p.get("imdb_rating", 0.0),
        "rt_score": p.get("rt_score", "N/A"),
        "poster_url": p.get("poster_url"),
        "backdrop_url": p.get("backdrop_url"),
        "trailer_key": p.get("trailer_key"),
    }