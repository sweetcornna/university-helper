import configparser
import os
import random
from re import sub

from loguru import logger

from .answer_cache import CacheDAO
from .answer_check import check_answer
from .answer_utils import _apply_ocr_to_title_if_needed


# TODO: 重构此部分代码，将此类改为抽象类，加载题库方法改为静态方法，禁止直接初始化此类
class Tiku:
    CONFIG_PATH = os.path.join(os.getcwd(), "config.ini")  # TODO: 从运行参数中获取config路径

    # Class-level defaults are kept ONLY as a read-only safety net for code/tests
    # that construct a Tiku subclass while bypassing __init__ (so attribute reads
    # never AttributeError). The real per-task values are ALWAYS set as INSTANCE
    # attributes in __init__ below — that is what guarantees per-task isolation in
    # the multi-tenant single-worker process. Never mutate true_list/false_list in
    # place (always reassign) so the shared class-level lists can never leak across
    # tenants. Names are identical so quiz/work_legacy consumers are unaffected.
    DISABLE = False  # 停用标志
    SUBMIT = False  # 提交标志
    COVER_RATE = 0.8  # 覆盖率
    true_list: list = []
    false_list: list = []

    def __init__(self) -> None:
        self._name = None
        self._api = None
        self._conf = None
        # Shadow the class-level defaults with per-instance attributes so every
        # Tiku instance owns its own flags and its own (distinct) list objects.
        self.DISABLE = False  # 停用标志
        self.SUBMIT = False  # 提交标志
        self.COVER_RATE = 0.8  # 覆盖率
        self.true_list = []
        self.false_list = []

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value):
        self._api = value

    @property
    def token(self):
        return self._token

    @token.setter
    def token(self, value):
        self._token = value

    def init_tiku(self):
        # 仅用于题库初始化, 应该在题库载入后作初始化调用, 随后才可以使用题库
        # 尝试根据配置文件设置提交模式
        if not self._conf:
            self.config_set(self._get_conf())

        # 如果仍然没有配置或已经被标记为禁用, 直接关闭题库功能
        if not self._conf or self.DISABLE:
            self.DISABLE = True
            return

        conf = self._conf

        # 设置提交模式（缺省为不直接提交）
        submit_val = str(conf.get("submit", "false")).strip().lower()
        self.SUBMIT = submit_val == "true"

        # 设置覆盖率（缺省为 0.8）
        cover_raw = conf.get("cover_rate", "0.8")
        try:
            self.COVER_RATE = float(cover_raw)
        except (TypeError, ValueError):
            self.COVER_RATE = 0.8

        # 判断题映射表，支持缺省配置。
        # 每个列表独立生效：用户只配置 true_list（或只配置 false_list）时，
        # 应当采用其配置值，另一侧回退到默认，而不是因为没有同时配置而全部丢弃。
        true_raw = conf.get("true_list")
        false_raw = conf.get("false_list")

        default_true = ["正确", "对", "T", "True", "true"]
        default_false = ["错误", "错", "F", "False", "false"]

        if true_raw:
            self.true_list = [s for s in true_raw.split(",") if s] or default_true
        else:
            self.true_list = default_true

        if false_raw:
            self.false_list = [s for s in false_raw.split(",") if s] or default_false
        else:
            self.false_list = default_false

        # 调用自定义题库初始化
        self._init_tiku()

    def _init_tiku(self):
        # 仅用于题库初始化, 例如配置token, 交由自定义题库完成
        pass

    def config_set(self, config):
        self._conf = config

    def _get_conf(self):
        """
        从默认配置文件查询配置, 如果未能查到, 停用题库
        """
        try:
            config = configparser.ConfigParser()
            config.read(self.CONFIG_PATH, encoding="utf8")
            return config["tiku"]
        except (KeyError, FileNotFoundError):
            logger.info("未找到tiku配置, 已忽略题库功能")
            self.DISABLE = True
            return None

    def query(self, q_info: dict) -> str | None:
        if self.DISABLE:
            return None

        # 预处理, 去除【单选题】这样与标题无关的字段
        logger.debug(f"原始标题：{q_info['title']}")

        # 检测并处理题目中的图片链接：使用本地 OCR 将公式图片转为文本
        _apply_ocr_to_title_if_needed(q_info)

        q_info["title"] = sub(r"^\d+", "", q_info["title"])
        q_info["title"] = sub(r"（\d+\.\d+分）$", "", q_info["title"])
        logger.debug(f"处理后标题：{q_info['title']}")

        # 先过缓存。CacheDAO 现在共享进程级内存快照并在 add_cache 时写穿到磁盘，
        # 因此每题构造一个新实例的代价是 O(1)（不再每题重新读取/解析整个文件）。
        cache_dao = CacheDAO()
        answer = cache_dao.get_cache(q_info["title"])
        if answer:
            logger.info(f"从缓存中获取答案：{q_info['title']} -> {answer}")
            return answer.strip()
        answer = self._query(q_info)
        if answer:
            answer = answer.strip()
            logger.info(f"从{self.name}获取答案：{q_info['title']} -> {answer}")

            q_type = q_info.get("type")

            # 对 AI / 硅基流动等大模型题库更宽松：对填空/单选/多选/未知题型，
            # 只要有非空答案就直接使用并写入缓存，不再依赖 check_answer 的严格
            # 类型判断，避免丢弃诸如"输入/输出"、"Babbage machine"这种正常答案。
            # 但判断题必须先归一化映射到 true_list/false_list，否则一句完整的
            # 句子（如"这道题表述是对的"）会在 judgement_select 里退化为随机选择，
            # 而且会被缓存固化，导致判断题覆盖率静默变成随机。
            from api.answer import AI, SiliconFlow  # type: ignore

            if isinstance(self, (AI, SiliconFlow)):
                if q_type == "judgement":
                    normalized = self._normalize_judgement_answer(answer)
                    if normalized is None:
                        logger.info(f"从{self.name}获取到的判断题答案无法归一化为 正确/错误，已舍弃：{answer}")
                        return None
                    cache_dao.add_cache(q_info["title"], normalized)
                    return normalized
                cache_dao.add_cache(q_info["title"], answer)
                return answer

            if check_answer(answer, q_type, self):
                cache_dao.add_cache(q_info["title"], answer)
                return answer
            logger.info(f"从{self.name}获取到的答案类型与题目类型不符，已舍弃")
            return None

        logger.error(f"从{self.name}获取答案失败：{q_info['title']}")
        return None

    def _normalize_judgement_answer(self, answer: str) -> str | None:
        """将（AI 返回的）判断题答案归一化为 true_list / false_list 中的标准值。

        - 若答案精确命中 true_list / false_list，直接返回该标准值；
        - 否则尝试基于关键字（正确/对/true/错误/错/false 等）作宽松匹配，
          命中则返回对应列表的首个标准值；
        - 无法判定时返回 None，调用方据此丢弃且不缓存，避免污染缓存与覆盖率统计。
        """
        if not answer:
            return None
        text = answer.strip()
        if text in self.true_list:
            return text
        if text in self.false_list:
            return text

        true_default = self.true_list[0] if self.true_list else "正确"
        false_default = self.false_list[0] if self.false_list else "错误"

        lowered = text.lower()
        true_markers = ["正确", "对", "true", "√", "yes", "right", "correct"]
        false_markers = ["错误", "错", "false", "×", "no", "wrong", "incorrect"]
        hit_true = any(m in text or m in lowered for m in true_markers)
        hit_false = any(m in text or m in lowered for m in false_markers)
        # 同时命中两边（例如句子里既有"正确"又有"错误"）无法判定
        if hit_true and not hit_false:
            return true_default
        if hit_false and not hit_true:
            return false_default
        return None

    def _query(self, q_info: dict) -> str | None:
        """
        查询接口, 交由自定义题库实现
        """

    def get_tiku_from_config(self):
        """
        从配置文件加载题库, 这个配置可以是用户提供, 可以是默认配置文件
        """
        if not self._conf:
            # 尝试从默认配置文件加载
            self.config_set(self._get_conf())
        if self.DISABLE:
            return self
        try:
            cls_name = self._conf["provider"]
            if not cls_name:
                raise KeyError
        except KeyError:
            self.DISABLE = True
            logger.info("未找到题库配置, 已忽略题库功能")
            return self
        # Import providers at runtime to build the lookup (avoids circular imports)
        from .answer_providers import (
            AI,
            SiliconFlow,
            TikuAdapter,
            TikuGo,
            TikuLike,
            TikuLocalCache,
            TikuYanxi,
        )

        _provider_map = {
            "TikuYanxi": TikuYanxi,
            "TikuGo": TikuGo,
            "TikuLike": TikuLike,
            "TikuAdapter": TikuAdapter,
            "LocalCache": TikuLocalCache,
            "AI": AI,
            "SiliconFlow": SiliconFlow,
        }

        # provider 支持逗号分隔的多题库回退链：单个 → 直接返回该题库；
        # 多个 → 构造 TikuFallback，按配置顺序逐个兜底。
        names = [name.strip() for name in str(cls_name).split(",") if name.strip()]
        if not names:
            self.DISABLE = True
            logger.error("题库 provider 配置为空, 已忽略题库功能")
            return self

        unknown = [name for name in names if name not in _provider_map]
        if unknown:
            self.DISABLE = True
            logger.error(f"未知的题库 provider: {', '.join(unknown)}")
            return self

        if len(names) == 1:
            new_cls = _provider_map[names[0]]()
            new_cls.config_set(self._conf)
            return new_cls

        chain = []
        for name in names:
            provider = _provider_map[name]()
            provider.config_set(self._conf)
            chain.append(provider)
        fallback = TikuFallback(chain)
        fallback.config_set(self._conf)
        return fallback

    def judgement_select(self, answer: str) -> bool:
        """
        这是一个专用的方法, 要求配置维护两个选项列表, 一份用于正确选项, 一份用于错误选项, 以应对题库对判断题答案响应的各种可能的情况
        它的作用是将获取到的答案answer与可能的选项列对比并返回对应的布尔值
        """
        if self.DISABLE:
            return False
        # 对响应的答案作处理
        answer = answer.strip()
        if answer in self.true_list:
            return True
        if answer in self.false_list:
            return False
        # 无法判断, 随机选择
        logger.error(
            f"无法判断答案 -> {answer} 对应的是正确还是错误, 请自行判断并加入配置文件重启脚本, 本次将会随机选择选项"
        )
        return random.choice([True, False])

    def get_submit_params(self):
        """
        这是一个专用方法, 用于根据当前设置的提交模式, 响应对应的答题提交API中的pyFlag值
        """
        # 留空直接提交, 1保存但不提交
        if self.SUBMIT:
            return ""
        return "1"

    @property
    def wants_concurrent_query(self) -> bool:
        """Whether a card's questions should be answered concurrently.

        Only the AI provider opts in — it is built for it (each request is bounded
        by its own semaphore). Other providers (incl. SiliconFlow) stay sequential,
        preserving existing behaviour. TikuFallback overrides this to opt in when
        any link in the chain is an AI provider.
        """
        from .answer_providers import AI

        return isinstance(self, AI)


class TikuFallback(Tiku):
    """多题库回退：按配置顺序依次查询，命中即返回，未命中/类型不符则回退到下一个。

    The fallback wraps an ordered list of already-configured Tiku providers.
    `judgement_select()`/`get_submit_params()`/`COVER_RATE`/`DISABLE` are served by
    the base class from this fallback's own config, so the consumers in
    quiz_service / work_legacy_service treat it like any other Tiku. `query()` is
    overridden (see below) because the per-provider validation already happens
    inside `_query`, so the base class must NOT re-validate the chosen answer.
    """

    def __init__(self, providers=None) -> None:
        super().__init__()
        self.name = "多题库回退"
        self.providers = list(providers or [])

    def query(self, q_info: dict) -> str | None:
        """Cache → chain, with the chain result taken as authoritative.

        `_query` already validates each provider's answer (lenient acceptance for
        AI/SiliconFlow links, `check_answer` for the rest). The base `Tiku.query()`
        would re-run the strict `check_answer` here — and because ``self`` is the
        fallback, not an AI instance, it would discard valid multi-token LLM
        answers that a direct AI selection keeps. Overriding query() makes an
        AI-bearing chain behave exactly like selecting that AI directly.
        """
        if self.DISABLE:
            return None
        _apply_ocr_to_title_if_needed(q_info)
        q_info["title"] = sub(r"^\d+", "", q_info["title"])
        q_info["title"] = sub(r"（\d+\.\d+分）$", "", q_info["title"])

        cache_dao = CacheDAO()
        cached = cache_dao.get_cache(q_info["title"])
        if cached:
            logger.info(f"从缓存中获取答案：{q_info['title']} -> {cached}")
            return cached.strip()

        answer = self._query(q_info)
        if answer:
            answer = answer.strip()
            logger.info(f"从{self.name}获取答案：{q_info['title']} -> {answer}")
            cache_dao.add_cache(q_info["title"], answer)
            return answer
        logger.error(f"从{self.name}获取答案失败：{q_info['title']}")
        return None

    @property
    def wants_concurrent_query(self) -> bool:
        from .answer_providers import AI

        return any(isinstance(p, AI) for p in self.providers)

    def _init_tiku(self):
        # Initialize each child; silently drop any that disable themselves or
        # fail to initialize (e.g. token-required provider with no token, or AI
        # without endpoint/key). A mixed chain stays usable as long as one works.
        active = []
        for provider in self.providers:
            try:
                if provider._conf is None:
                    provider.config_set(self._conf)
                provider.init_tiku()
                if provider.DISABLE:
                    logger.info(f"题库 {provider.name} 不可用，已从回退链移除")
                    continue
                active.append(provider)
            except Exception as e:
                logger.error(f"初始化题库 {provider.name} 失败，已从回退链移除: {e}")
        self.providers = active
        if not self.providers:
            logger.error("多题库回退初始化失败: 没有可用题库")
            self.DISABLE = True
        else:
            logger.info("多题库回退已启用，查询顺序: " + " → ".join(p.name for p in self.providers))

    def _query(self, q_info: dict) -> str | None:
        # Import here to avoid a circular import with answer_providers.
        from .answer_providers import AI, SiliconFlow

        q_type = q_info.get("type")
        for provider in self.providers:
            try:
                answer = provider._query(q_info)
            except Exception as e:
                logger.exception(f"{self.name} 查询时 {provider.name} 异常: {e}")
                continue
            if not answer:
                logger.info(f"{provider.name} 未命中，回退到下一个题库")
                continue
            answer = answer.strip()

            # Mirror Tiku.query()'s AI/SiliconFlow special-casing so a chain that
            # ends in an LLM behaves exactly like selecting that LLM directly.
            if isinstance(provider, (AI, SiliconFlow)):
                if q_type == "judgement":
                    normalized = provider._normalize_judgement_answer(answer)
                    if normalized is None:
                        logger.info(f"{provider.name} 判断题答案无法归一化，回退到下一个题库")
                        continue
                    logger.info(f"{provider.name} 命中答案")
                    return normalized
                logger.info(f"{provider.name} 命中答案")
                return answer

            if check_answer(answer, q_type, provider):
                logger.info(f"{provider.name} 命中答案")
                return answer
            logger.info(f"{provider.name} 返回答案类型与题目类型不符，回退到下一个题库")
        return None
