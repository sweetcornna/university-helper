"""Re-export hub for backward compatibility.

All implementation has been split into:
- answer_utils.py       (utility functions)
- answer_cache.py       (CacheDAO)
- answer_base.py        (Tiku base class, TikuFallback)
- answer_providers/     (TikuYanxi, TikuGo, TikuLike, TikuAdapter, TikuLocalCache, AI, SiliconFlow)
"""

from .answer_base import Tiku, TikuFallback
from .answer_cache import CacheDAO
from .answer_providers import (
    AI,
    SiliconFlow,
    TikuAdapter,
    TikuGo,
    TikuLike,
    TikuLocalCache,
    TikuYanxi,
)

__all__ = [
    "CacheDAO",
    "Tiku",
    "TikuFallback",
    "TikuYanxi",
    "TikuGo",
    "TikuLike",
    "TikuAdapter",
    "TikuLocalCache",
    "AI",
    "SiliconFlow",
]
