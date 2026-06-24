from ..answer_base import Tiku


class TikuLocalCache(Tiku):
    """本地缓存题库：只复用进程级答案缓存，从不调用外部题库 API。

    `Tiku.query()` always consults the shared answer cache first, so a provider
    whose `_query` returns None effectively answers from cache only. This makes
    the "本地缓存 / LocalCache" option in the frontend a real, token-free choice
    (e.g. as the first link in a fallback chain) instead of a dead value.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "本地缓存题库"

    def _query(self, q_info: dict):
        # Never hit the network; cache is handled by the base Tiku.query().
        return None
