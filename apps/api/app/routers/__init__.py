from .routes_taste_profile import router as taste_profile_router
from .routes_recommendations import router as recommend_router
from .routes_discovery import router as discover_router
from .routes_watchlist import router as watchlist_router

all_routers = [
    taste_profile_router,
    discover_router,
    recommend_router,
    watchlist_router,
]
