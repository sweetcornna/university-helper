"""Legacy work/quiz handling service for Chaoxing."""

import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from .answer import Tiku
from .answer_check import cut
from .decode import decode_questions_info
from .exceptions import MaxRetryExceeded

# API URL constants
WORK_API_URL = "https://mooc1.chaoxing.com/mooc-ans/api/work"
SUBMIT_WORK_URL = "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew"


class ChaoxingWorkLegacyService:
    """Handles legacy work/quiz answering and submission."""

    def __init__(self, tiku: Tiku, rollback_times: int, kwargs: dict, session_manager=None):
        self.tiku = tiku
        self.rollback_times = rollback_times
        self.kwargs = kwargs
        self.session_manager = session_manager

    # ------------------------------------------------------------------
    # Static utility methods (extracted from nested functions)
    # ------------------------------------------------------------------

    @staticmethod
    def _random_answer(question_type: str, options: str, multi_cut_func) -> str:
        """Generate a random answer for a question.

        Args:
            question_type: One of 'multiple', 'single', 'judgement'
            options: The options string
            multi_cut_func: Reference to _multi_cut bound method or callable
        """
        answer = ""
        if not options:
            return answer

        if question_type == "multiple":
            logger.debug(f"当前选项列表[cut前] -> {options}")
            _op_list = multi_cut_func(options)
            logger.debug(f"当前选项列表[cut后] -> {_op_list}")

            if not _op_list:
                logger.error("选项为空, 未能正确提取题目选项信息! 请反馈并提供以上信息")
                return answer

            available_options = len(_op_list)
            select_count = 0

            if available_options <= 1:
                select_count = available_options
            else:
                max_possible = min(4, available_options)
                min_possible = min(2, available_options)

                weights_map = {
                    2: [1.0],
                    3: [0.3, 0.7],
                    4: [0.1, 0.5, 0.4],
                    5: [0.1, 0.4, 0.3, 0.2],
                }

                weights = weights_map.get(max_possible, [0.3, 0.4, 0.3])
                possible_counts = list(range(min_possible, max_possible + 1))

                weights = weights[: len(possible_counts)]

                weights_sum = sum(weights)
                if weights_sum > 0:
                    weights = [w / weights_sum for w in weights]

                select_count = random.choices(possible_counts, weights=weights, k=1)[0]

            selected_options = random.sample(_op_list, select_count) if select_count > 0 else []

            answer = "".join(sorted(option[:1] for option in selected_options))
        elif question_type == "single":
            answer = random.choice(options.split("\n"))[:1]
        elif question_type == "judgement":
            answer = "true" if random.choice([True, False]) else "false"
        logger.info(f"随机选择 -> {answer}")
        return answer

    def _multi_cut(self, answer: str, origin_html_content: str = ""):
        """
        将多选题答案字符串按特定字符进行切割, 并返回切割后的答案列表

        参数:
        answer(str): 多选题答案字符串.

        返回:
        list[str]: 切割后的答案列表,如果无法切割, 则返回默认的选项列表None
        """
        res = cut(answer)
        if res is None:
            logger.warning(f"未能从网页中提取题目信息, 以下为相关信息：\n\t{answer}\n\n{origin_html_content}\n")
            logger.warning("未能正确提取题目选项信息! 请反馈并提供以上信息")
            return None
        return res

    @staticmethod
    def _clean_res(res):
        cleaned_res = []
        if isinstance(res, str):
            res = [res]
        for c in res:
            cleaned = re.sub(r"^[A-Za-z]|[.,!?;:，。！？；：]", "", c)
            cleaned_res.append(cleaned.strip())
        return cleaned_res

    @staticmethod
    def _is_subsequence(a, o):
        iter_o = iter(o)
        return all(c in iter_o for c in a)

    # ------------------------------------------------------------------
    # Network helpers
    # ------------------------------------------------------------------

    def _fetch_response(self, session, url, _job, _job_info, _course):
        """Fetch work page with retry logic.

        Returns:
            Tuple of (response, questions_dict)
        """
        max_retries = 3
        delay = 1
        retries = 0
        while retries < max_retries:
            try:
                _resp = session.get(
                    url,
                    params={
                        "api": "1",
                        "workId": _job["jobid"].replace("work-", ""),
                        "jobid": _job["jobid"],
                        "originJobId": _job["jobid"],
                        "needRedirect": "true",
                        "skipHeader": "true",
                        "knowledgeid": str(_job_info["knowledgeid"]),
                        "ktoken": _job_info["ktoken"],
                        "cpi": _job_info["cpi"],
                        "ut": "s",
                        "clazzId": _course["clazzId"],
                        "type": "",
                        "enc": _job["enc"],
                        "mooc2": "1",
                        "courseid": _course["courseId"],
                    },
                )

                # 未创建完成该测验则不进行答题
                if "教师未创建完成该测验" in _resp.text:
                    raise PermissionError("教师未创建完成该测验")

                questions = decode_questions_info(_resp.text)

                if _resp.status_code == 200 and questions.get("questions"):
                    return (_resp, questions)

                logger.warning(
                    f"无效响应 (Code: {getattr(_resp, 'status_code', 'Unknown')}), 重试中... ({retries + 1}/{max_retries})"
                )

            except PermissionError:
                raise
            except Exception as e:
                logger.warning(f"请求失败: {str(e)[:50]}, 重试中... ({retries + 1}/{max_retries})")
            retries += 1
            time.sleep(delay * (2**retries))
        raise MaxRetryExceeded(f"超过最大重试次数 ({max_retries})")

    # ------------------------------------------------------------------
    # Question handling
    # ------------------------------------------------------------------

    def _handle_question(self, q, inc_found, origin_html_content):
        """Process a single question: query tiku, match answer, fill form."""
        logger.debug(f"当前题目信息 -> {q}")
        # 添加搜题延迟 #428 - 默认0s延迟
        query_delay = self.kwargs.get("query_delay", 0)
        if query_delay:
            time.sleep(query_delay)
        res = self.tiku.query(q)
        answer = ""

        def _multi_cut_with_context(ans):
            return self._multi_cut(ans, origin_html_content)

        if not res:
            # 随机答题
            answer = self._random_answer(q["type"], q["options"], _multi_cut_with_context)
            q[f'answerSource{q["id"]}'] = "random"
        else:
            # 根据响应结果选择答案
            if q["type"] == "multiple":
                options_list = self._multi_cut(q["options"], origin_html_content)
                if options_list is not None:
                    opt_letters = "".join(o[:1] for o in options_list)
                    letters_raw = "".join(ch for ch in str(res) if ch.isalpha()).upper()
                    letters_filtered = "".join(ch for ch in letters_raw if ch in opt_letters)
                    if letters_filtered:
                        unique_letters = []
                        for ch in letters_filtered:
                            if ch not in unique_letters:
                                unique_letters.append(ch)
                        answer = "".join(sorted(unique_letters))
                    else:
                        res_list = self._multi_cut(res, origin_html_content)
                        if res_list is not None:
                            for _a in self._clean_res(res_list):
                                for o in options_list:
                                    if self._is_subsequence(_a, o):
                                        answer += o[:1]
                            answer = "".join(sorted(answer))
            elif q["type"] == "single":
                options_list = self._multi_cut(q["options"], origin_html_content)
                if options_list is not None:
                    opt_letters = "".join(o[:1] for o in options_list)
                    letters_raw = "".join(ch for ch in str(res) if ch.isalpha()).upper()
                    letters_filtered = "".join(ch for ch in letters_raw if ch in opt_letters)
                    if len(letters_filtered) == 1:
                        answer = letters_filtered
                    else:
                        t_res = self._clean_res(res)
                        if t_res:
                            for o in options_list:
                                if self._is_subsequence(t_res[0], o):
                                    answer = o[:1]
                                    break
            elif q["type"] == "judgement":
                answer = "true" if self.tiku.judgement_select(res) else "false"
            elif q["type"] == "completion":
                # Tiku.query() 始终返回 str 或 None；进入此分支时 res 必为非空 str
                # （多空填空答案已由 provider 以 '\n' 连接），故无需 list 分支。
                answer = str(res).strip()
            else:
                answer = res

            if not answer:
                logger.warning(f"找到答案但答案未能匹配 -> {res}\t随机选择答案")
                answer = self._random_answer(q["type"], q["options"], _multi_cut_with_context)
                q[f'answerSource{q["id"]}'] = "random"
            else:
                logger.info(f"成功获取到答案：{answer}")
                q[f'answerSource{q["id"]}'] = "cover"
                inc_found()
        # 填充答案
        q["answerField"][f'answer{q["id"]}'] = answer
        logger.info(f'{q["title"]} 填写答案为 {answer}')

    def _fallback_random_answer(self, q, origin_html_content=""):
        """当 _handle_question 抛异常时，为该题填入随机答案，避免提交时该题留空。"""
        try:

            def _multi_cut_with_context(ans):
                return self._multi_cut(ans, origin_html_content)

            answer = self._random_answer(q.get("type", ""), q.get("options", ""), _multi_cut_with_context)
            q[f'answerSource{q["id"]}'] = "random"
            q.setdefault("answerField", {})[f'answer{q["id"]}'] = answer
        except Exception as exc:  # noqa: BLE001 - 兜底，确保提交表单字段不缺失
            logger.error("生成随机兜底答案失败 (id={}): {}", q.get("id"), exc)
            q.setdefault("answerField", {})[f'answer{q["id"]}'] = ""
            q[f'answerSource{q["id"]}'] = "random"

    @staticmethod
    def _fill_answers_into_form(questions, is_save: bool):
        """将每道题的 answerField 写回提交表单。

        - is_save=True: 仅在 answerSource 为 cover 时写入答案（随机答案留空）。
        - is_save=False: 所有 answer* 字段直接写入（提交时保留随机答案）。
        """
        for q in questions["questions"]:
            src = q.get(f'answerSource{q["id"]}', "")
            for key, val in q["answerField"].items():
                if not isinstance(key, str) or not key.startswith("answer"):
                    continue
                if is_save:
                    questions[key] = val if src == "cover" else ""
                else:
                    questions[key] = val

            answertype_key = f'answertype{q["id"]}'
            if answertype_key in q["answerField"]:
                questions[answertype_key] = q["answerField"][answertype_key]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def study_work(self, _course, _job, _job_info):
        """Process a legacy work/quiz task.

        Returns:
            StudyResult enum value
        """
        from .client import StudyResult

        if not self.tiku or self.tiku.DISABLE:
            return StudyResult.SUCCESS
        _ORIGIN_HTML_CONTENT = ""

        _session = self.session_manager.get_session()

        try:
            final_resp, questions = self._fetch_response(_session, WORK_API_URL, _job, _job_info, _course)
        except Exception as e:
            logger.error(f"请求失败: {e}")
            return StudyResult.ERROR

        _ORIGIN_HTML_CONTENT = final_resp.text

        # 搜题
        total_questions = len(questions["questions"])
        found_answers = 0

        # 若题库含 AI（含 AI 回退链），则在同一张卷内并发搜题
        if self.tiku.wants_concurrent_query:
            lock = threading.Lock()

            def inc_found_concurrent():
                nonlocal found_answers
                with lock:
                    found_answers += 1

            ai_concurrency = self.kwargs.get("ai_concurrency", 3)
            try:
                ai_concurrency = int(ai_concurrency)
            except (TypeError, ValueError):
                ai_concurrency = 3
            ai_concurrency = max(1, ai_concurrency)

            with ThreadPoolExecutor(max_workers=ai_concurrency) as executor:
                future_to_q = {
                    executor.submit(self._handle_question, q, inc_found_concurrent, _ORIGIN_HTML_CONTENT): q
                    for q in questions["questions"]
                }
                # 收集 future 结果：ThreadPoolExecutor 会吞掉 worker 异常，
                # 若不调用 .result() 则失败的题目会被静默留空并照常提交。
                for future in as_completed(future_to_q):
                    q = future_to_q[future]
                    try:
                        future.result()
                    except Exception as exc:
                        logger.error(
                            "AI 并发答题处理题目失败 (id={}), 回退随机答案: {}",
                            q.get("id"),
                            exc,
                        )
                        self._fallback_random_answer(q, _ORIGIN_HTML_CONTENT)
        else:

            def inc_found_seq():
                nonlocal found_answers
                found_answers += 1

            for q in questions["questions"]:
                self._handle_question(q, inc_found_seq, _ORIGIN_HTML_CONTENT)

        cover_rate = (found_answers / total_questions) * 100
        logger.info(f"章节检测题库覆盖率： {cover_rate:.0f}%")

        # 提交模式
        if self.tiku.get_submit_params() == "1":
            questions["pyFlag"] = "1"
        elif cover_rate >= self.tiku.COVER_RATE * 100 or self.rollback_times >= 1:
            questions["pyFlag"] = ""
        else:
            questions["pyFlag"] = "1"
            logger.info(f"章节检测题库覆盖率低于{self.tiku.COVER_RATE * 100:.0f}% ，不予提交")

        # 组建提交表单
        if questions["pyFlag"] == "1":
            self._fill_answers_into_form(questions, is_save=True)
        else:
            self._fill_answers_into_form(questions, is_save=False)

        del questions["questions"]

        res = _session.post(
            SUBMIT_WORK_URL,
            data=questions,
            headers={
                "Host": "mooc1.chaoxing.com",
                "sec-ch-ua-platform": '"Windows"',
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "sec-ch-ua-mobile": "?0",
                "Origin": "https://mooc1.chaoxing.com",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
            },
        )
        if res.status_code == 200:
            res_json = res.json()
            if res_json["status"]:
                logger.info(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题成功 -> {res_json["msg"]}')
            else:
                msg = str(res_json.get("msg", ""))
                if "已过期" in msg:
                    logger.warning(
                        f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败(作业已过期，将跳过本作业) -> {msg}'
                    )
                    return StudyResult.SUCCESS

                logger.error(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败 -> {msg}')
                return StudyResult.ERROR
        else:
            logger.error(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败 -> {res.text}')
            return StudyResult.ERROR
        return StudyResult.SUCCESS
