from .routes_taste_profile import router as taste_profile_router
from .routes_recommend import router as recommend_router
from .routes_discover import router as discover_router

all_routers = [taste_profile_router, discover_router, recommend_router]
