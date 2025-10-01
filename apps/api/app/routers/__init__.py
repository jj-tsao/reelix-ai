from .taste_profile import router as taste_profile_router
# from .discover import router as discover_router
from .recommend import router as recommend_router
# from .profile import router as profile_router

all_routers = [taste_profile_router, recommend_router]
