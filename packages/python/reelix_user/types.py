from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

MediaType = str
MediaId = int

@dataclass
class Interaction:
    media_type: MediaType    # 'movie' | 'tv'  
    media_id: MediaId        # tmdb id
    kind: str                # 'love' | 'like' | 'dislike'
    ts: datetime             # tz-aware

@dataclass
class UserSignals:
    genres_include: list[str]
    keywords_include: list[str]
    interactions: list[Interaction]

@dataclass
class BuildParams:
    dim: int = 768
    w_love: float = 2.0
    w_like: float = 1.0
    w_dislike: float = 1.5
    lambda_month: float = 0.3      # decay per 30 days
    alpha: float = 1.0             # +pos centroid
    beta: float = 0.6              # −neg centroid
    gamma: float = 0.2             # genre/vibe prior
    delta: float = 0.15            # keyword prior
    min_pos_for_profile: int = 1
    min_total_for_profile: int = 2
