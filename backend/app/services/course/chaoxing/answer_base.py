import configparser
import os
import random
from re import sub
from typing import Optional

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
    DISABLE = False     # 停用标志
    SUBMIT = False      # 提交标志
    COVER_RATE = 0.8    # 覆盖率
    true_list: list = []
    false_list: list = []

    def __init__(self) -> None:
        self._name = None
        self._api = None
        self._conf = None
        # Shadow the class-level defaults with per-instance attributes so every
        # Tiku instance owns its own flags and its own (distinct) list objects.
        self.DISABLE = False     # 停用标志
        self.SUBMIT = False      # 提交标志
        self.COVER_RATE = 0.8    # 覆盖率
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
        submit_val = str(conf.get('submit', 'false')).strip().lower()
        self.SUBMIT = submit_val == 'true'

        # 设置覆盖率（缺省为 0.8）
        cover_raw = conf.get('cover_rate', '0.8')
        try:
            self.COVER_RATE = float(cover_raw)
        except (TypeError, ValueError):
            self.COVER_RATE = 0.8

        # 判断题映射表，支持缺省配置。
        # 每个列表独立生效：用户只配置 true_list（或只配置 false_list）时，
        # 应当采用其配置值，另一侧回退到默认，而不是因为没有同时配置而全部丢弃。
        true_raw = conf.get('true_list')
        false_raw = conf.get('false_list')

        default_true = ['正确', '对', 'T', 'True', 'true']
        default_false = ['错误', '错', 'F', 'False', 'false']

        if true_raw:
            self.true_list = [s for s in true_raw.split(',') if s] or default_true
        else:
            self.true_list = default_true

        if false_raw:
            self.false_list = [s for s in false_raw.split(',') if s] or default_false
        else:
            self.false_list = default_false

        # 调用自定义题库初始化
        self._init_tiku()

    def _init_tiku(self):
        # 仅用于题库初始化, 例如配置token, 交由自定义题库完成
        pass

    def config_set(self,config):
        self._conf = config

    def _get_conf(self):
        """
        从默认配置文件查询配置, 如果未能查到, 停用题库
        """
        try:
            config = configparser.ConfigParser()
            config.read(self.CONFIG_PATH, encoding="utf8")
            return config['tiku']
        except (KeyError, FileNotFoundError):
            logger.info("未找到tiku配置, 已忽略题库功能")
            self.DISABLE = True
            return None

    def query(self,q_info:dict) -> Optional[str]:
        if self.DISABLE:
            return None

        # 预处理, 去除【单选题】这样与标题无关的字段
        logger.debug(f"原始标题：{q_info['title']}")

        # 检测并处理题目中的图片链接：使用本地 OCR 将公式图片转为文本
        _apply_ocr_to_title_if_needed(q_info)

        q_info['title'] = sub(r'^\d+', '', q_info['title'])
        q_info['title'] = sub(r'（\d+\.\d+分）$', '', q_info['title'])
        logger.debug(f"处理后标题：{q_info['title']}")

        # 先过缓存。CacheDAO 现在共享进程级内存快照并在 add_cache 时写穿到磁盘，
        # 因此每题构造一个新实例的代价是 O(1)（不再每题重新读取/解析整个文件）。
        cache_dao = CacheDAO()
        answer = cache_dao.get_cache(q_info['title'])
        if answer:
            logger.info(f"从缓存中获取答案：{q_info['title']} -> {answer}")
            return answer.strip()
        else:
            answer = self._query(q_info)
            if answer:
                answer = answer.strip()
                logger.info(f"从{self.name}获取答案：{q_info['title']} -> {answer}")

                q_type = q_info.get('type')

                # 对 AI / 硅基流动等大模型题库更宽松：对填空/单选/多选/未知题型，
                # 只要有非空答案就直接使用并写入缓存，不再依赖 check_answer 的严格
                # 类型判断，避免丢弃诸如"输入/输出"、"Babbage machine"这种正常答案。
                # 但判断题必须先归一化映射到 true_list/false_list，否则一句完整的
                # 句子（如"这道题表述是对的"）会在 judgement_select 里退化为随机选择，
                # 而且会被缓存固化，导致判断题覆盖率静默变成随机。
                from api.answer import AI, SiliconFlow  # type: ignore
                if isinstance(self, (AI, SiliconFlow)):
                    if q_type == 'judgement':
                        normalized = self._normalize_judgement_answer(answer)
                        if normalized is None:
                            logger.info(
                                f"从{self.name}获取到的判断题答案无法归一化为 正确/错误，已舍弃：{answer}"
                            )
                            return None
                        cache_dao.add_cache(q_info['title'], normalized)
                        return normalized
                    cache_dao.add_cache(q_info['title'], answer)
                    return answer

                if check_answer(answer, q_type, self):
                    cache_dao.add_cache(q_info['title'], answer)
                    return answer
                else:
                    logger.info(f"从{self.name}获取到的答案类型与题目类型不符，已舍弃")
                    return None

            logger.error(f"从{self.name}获取答案失败：{q_info['title']}")
        return None

    def _normalize_judgement_answer(self, answer: str) -> Optional[str]:
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

        true_default = self.true_list[0] if self.true_list else '正确'
        false_default = self.false_list[0] if self.false_list else '错误'

        lowered = text.lower()
        true_markers = ['正确', '对', 'true', '√', 'yes', 'right', 'correct']
        false_markers = ['错误', '错', 'false', '×', 'no', 'wrong', 'incorrect']
        hit_true = any(m in text or m in lowered for m in true_markers)
        hit_false = any(m in text or m in lowered for m in false_markers)
        # 同时命中两边（例如句子里既有"正确"又有"错误"）无法判定
        if hit_true and not hit_false:
            return true_default
        if hit_false and not hit_true:
            return false_default
        return None



    def _query(self, q_info:dict) -> Optional[str]:
        """
        查询接口, 交由自定义题库实现
        """
        pass


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
            cls_name = self._conf['provider']
            if not cls_name:
                raise KeyError
        except KeyError:
            self.DISABLE = True
            logger.info("未找到题库配置, 已忽略题库功能")
            return self
        # FIXME: Implement using StrEnum instead. This is not only buggy but also not safe
        # Import providers at runtime to build the lookup (avoids circular imports)
        from .answer_providers import TikuYanxi, TikuLike, TikuAdapter, AI, SiliconFlow
        _provider_map = {
            'TikuYanxi': TikuYanxi,
            'TikuLike': TikuLike,
            'TikuAdapter': TikuAdapter,
            'AI': AI,
            'SiliconFlow': SiliconFlow,
        }
        if cls_name not in _provider_map:
            self.DISABLE = True
            logger.error(f"未知的题库 provider: {cls_name}")
            return self
        new_cls = _provider_map[cls_name]()
        new_cls.config_set(self._conf)
        return new_cls

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
        elif answer in self.false_list:
            return False
        else:
            # 无法判断, 随机选择
            logger.error(f'无法判断答案 -> {answer} 对应的是正确还是错误, 请自行判断并加入配置文件重启脚本, 本次将会随机选择选项')
            return random.choice([True,False])

    def get_submit_params(self):
        """
        这是一个专用方法, 用于根据当前设置的提交模式, 响应对应的答题提交API中的pyFlag值
        """
        # 留空直接提交, 1保存但不提交
        if self.SUBMIT:
            return ""
        else:
            return "1"
