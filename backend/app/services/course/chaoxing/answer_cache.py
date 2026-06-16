import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from loguru import logger

# Persist the answer cache under a writable path. In production the container
# runs with a read-only rootfs (docker-compose.server.yml: read_only: true) and
# only /tmp is writable (tmpfs). A relative "cache.json" resolves under the
# read-only code dir (/srv/backend) and every write fails with OSError, leaving
# the cache permanently empty. Mirror cookies.py: default under /tmp and allow an
# env override via CHAOXING_CACHE_FILE.
DEFAULT_CACHE_FILE = os.environ.get("CHAOXING_CACHE_FILE", "/tmp/chaoxing_answer_cache.json")


class CacheDAO:
    """
    @Author: SocialSisterYi
    @Reference: https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy

    The answer cache is process-wide: every question's Tiku.query() constructs a
    CacheDAO, so per-CacheDAO state cannot be relied on for persistence. To make
    the cache actually effective and cheap we keep one in-memory snapshot keyed by
    the on-disk file path, guarded by a per-path lock. add_cache writes through to
    disk immediately (so a fresh CacheDAO sees previously cached answers) and
    get_cache reads the in-memory snapshot (so a quiz of N questions does O(1)
    file reads, not O(N) full re-parses).
    """

    # path -> {"snapshot": dict, "lock": RLock, "loaded": bool}
    _shared: dict = {}
    _shared_guard = threading.RLock()

    def __init__(self, file: str | None = None):
        self.cache_file = Path(file if file is not None else DEFAULT_CACHE_FILE)
        key = str(self.cache_file)
        with CacheDAO._shared_guard:
            state = CacheDAO._shared.get(key)
            if state is None:
                state = {"snapshot": {}, "lock": threading.RLock(), "loaded": False}
                CacheDAO._shared[key] = state
        self._state = state
        self._lock = state["lock"]
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        """Load the on-disk cache into the shared snapshot exactly once per path."""
        with self._lock:
            if self._state["loaded"]:
                return
            if self.cache_file.is_file():
                self._state["snapshot"] = self._read_cache()
            else:
                # Best-effort initialize an empty file; a read-only / missing dir
                # must not crash answering (cache is an optimization).
                self._write_cache({})
                self._state["snapshot"] = {}
            self._state["loaded"] = True

    def _read_cache(self) -> dict:
        # 新增缓存文件读取的异常处理
        try:
            with self._lock:
                if not self.cache_file.is_file():
                    return {}
                try:
                    with self.cache_file.open("r", encoding="utf8") as fp:
                        return json.load(fp)
                except json.JSONDecodeError as e:
                    logger.error(f"缓存文件 JSON 解析失败: {e}, 尝试恢复...")
                    # 尝试从原始二进制中以 utf-8 忽略错误地恢复有效 JSON 段
                    try:
                        raw = self.cache_file.read_bytes()
                        text = raw.decode("utf-8", errors="ignore")
                        start = text.find("{")
                        end = text.rfind("}")
                        if start != -1 and end != -1 and start < end:
                            try:
                                return json.loads(text[start : end + 1])
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # 若无法恢复，备份损坏文件并返回空缓存
                    try:
                        bak_name = f"{self.cache_file.name}.bak.{int(time.time())}"
                        bak_path = self.cache_file.with_name(bak_name)
                        shutil.copy2(self.cache_file, bak_path)
                        logger.error(f"缓存文件已损坏，已备份为: {bak_path}，将使用空缓存继续运行")
                    except Exception as ex:
                        logger.error(f"备份损坏缓存失败: {ex}")
                    return {}
                except UnicodeDecodeError as e:
                    logger.error(f"缓存文件编码读取失败: {e}, 采用恢复策略...")
                    try:
                        raw = self.cache_file.read_bytes()
                        text = raw.decode("utf-8", errors="ignore")
                        start = text.find("{")
                        end = text.rfind("}")
                        if start != -1 and end != -1 and start < end:
                            try:
                                return json.loads(text[start : end + 1])
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        bak_name = f"{self.cache_file.name}.bak.{int(time.time())}"
                        bak_path = self.cache_file.with_name(bak_name)
                        shutil.copy2(self.cache_file, bak_path)
                        logger.error(f"缓存文件编码错误，已备份为: {bak_path}，将使用空缓存继续运行")
                    except Exception as ex:
                        logger.error(f"备份损坏缓存失败: {ex}")
                    return {}
        except Exception as e:
            logger.error(f"读取缓存异常: {e}")
            return {}

    def _write_cache(self, data: dict) -> None:
        # 为缓存写入加锁，防止并发写入损坏文件
        try:
            with self._lock:
                parent = self.cache_file.parent
                if not parent.exists():
                    parent.mkdir(parents=True, exist_ok=True)
                # 写入临时文件后原子替换，减少并发写入时的损坏风险
                fd, tmp_path = tempfile.mkstemp(prefix=self.cache_file.name, dir=str(parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf8") as fp:
                        json.dump(data, fp, ensure_ascii=False)
                        fp.flush()
                    os.replace(tmp_path, str(self.cache_file))
                except Exception as e:
                    # 清理临时文件
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    logger.error(f"Failed to write cache atomically: {e}")
        except OSError as e:
            logger.error(f"Failed to write cache: {e}")

    def get_cache(self, question: str) -> str | None:
        # Serve from the in-memory snapshot (loaded once per file path) so a quiz
        # of N questions does O(1) disk reads instead of O(N) full re-parses.
        with self._lock:
            return self._state["snapshot"].get(question)

    def add_cache(self, question: str, answer: str) -> None:
        # Write through: update the shared snapshot AND persist to disk so a
        # freshly constructed CacheDAO (one per question in Tiku.query) sees it.
        with self._lock:
            self._state["snapshot"][question] = answer
            # Persist the full snapshot atomically. Best-effort: a write failure
            # (e.g. read-only fs) must not break answering; the in-memory snapshot
            # still serves the rest of this run. _write_cache already swallows
            # IOError, but guard here too so no write path can ever propagate.
            try:
                self._write_cache(dict(self._state["snapshot"]))
            except Exception as e:  # pragma: no cover - defensive
                logger.error(f"Failed to persist cache (in-memory cache still active): {e}")

    def flush_cache(self) -> None:
        # Retained for backward compatibility. add_cache now writes through, so
        # this simply re-persists the current snapshot.
        with self._lock:
            self._write_cache(dict(self._state["snapshot"]))
