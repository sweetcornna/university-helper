import argparse
import asyncio
import configparser
import enum
import operator
import sys
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from queue import Empty, PriorityQueue

try:
    from queue import ShutDown
except ImportError:
    # ShutDown is only available in Python 3.13+
    class ShutDown(Exception):
        pass


from threading import RLock
from typing import Any

from loguru import logger
from tqdm import tqdm

from app.services.notification import NotificationFactory

from .answer import Tiku
from .client import Account, Chaoxing, StudyResult
from .exceptions import InputFormatError, LoginError
from .live import Live
from .live_process import LiveProcessor


class ChapterResult(enum.Enum):
    SUCCESS = (0,)
    ERROR = (1,)
    NOT_OPEN = (2,)
    PENDING = 3
    CANCELLED = 4


def should_stop(config: dict[str, Any] | None = None) -> bool:
    if not isinstance(config, dict):
        return False
    callback = config.get("should_stop")
    return bool(callable(callback) and callback())


def _is_thread_start_failure(exc: Exception) -> bool:
    text = str(exc).lower()
    if "can't start new thread" in text or "cannot start new thread" in text:
        return True
    cause = getattr(exc, "__cause__", None)
    return isinstance(cause, Exception) and _is_thread_start_failure(cause)


def log_error(func):
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except BaseException as e:
            logger.error(f"Error in thread {threading.current_thread().name}: {e}")
            traceback.print_exception(type(e), e, e.__traceback__)
            raise

    return wrapper


def str_to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _validate_jobs(value: Any) -> int:
    """Return a positive job count or reject an invalid configuration value."""
    try:
        # Configuration files provide strings, while programmatic callers must
        # provide an integer-like value.  ``operator.index`` deliberately
        # rejects floats instead of silently truncating them via ``int``.
        jobs = int(value) if isinstance(value, str) else operator.index(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("jobs must be a positive integer") from exc
    if jobs <= 0:
        raise ValueError("jobs must be greater than 0")
    return jobs


def _parse_jobs_argument(value: str) -> int:
    try:
        return _validate_jobs(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Samueli924/chaoxing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--use-cookies", action="store_true", help="使用cookies登录")

    parser.add_argument("-c", "--config", type=str, default=None, help="使用配置文件运行程序")
    parser.add_argument("-u", "--username", type=str, default=None, help="手机号账号")
    parser.add_argument("-p", "--password", type=str, default=None, help="登录密码")
    parser.add_argument("-l", "--list", type=str, default=None, help="要学习的课程ID列表, 以 , 分隔")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="视频播放倍速 (默认1, 最大2)")
    parser.add_argument(
        "-j",
        "--jobs",
        type=_parse_jobs_argument,
        default=4,
        help="同时进行的章节数 (默认4, 如果一个章节有多个任务点，不会限制同时处理任务点的数量)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        "--debug",
        action="store_true",
        help="启用调试模式, 输出DEBUG级别日志",
    )
    parser.add_argument(
        "-a",
        "--notopen-action",
        type=str,
        default="retry",
        choices=["retry", "ask", "continue"],
        help="遇到关闭任务点时的行为: retry-重试, ask-询问, continue-继续",
    )

    # 在解析之前捕获 -h 的行为
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


def load_config_from_file(config_path):
    """从配置文件加载设置"""
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf8")

    common_config: dict[str, Any] = {}
    tiku_config: dict[str, Any] = {}
    notification_config: dict[str, Any] = {}

    # 检查并读取common节
    if config.has_section("common"):
        common_config = dict(config.items("common"))
        # 处理course_list，将字符串转换为列表
        if "course_list" in common_config and common_config["course_list"]:
            common_config["course_list"] = [
                item.strip() for item in common_config["course_list"].split(",") if item.strip()
            ]
        # 处理speed，将字符串转换为浮点数
        if "speed" in common_config:
            common_config["speed"] = float(common_config["speed"])
        if "jobs" in common_config:
            common_config["jobs"] = _validate_jobs(common_config["jobs"])
        # 处理notopen_action，设置默认值为retry
        if "notopen_action" not in common_config:
            common_config["notopen_action"] = "retry"
        if "use_cookies" in common_config:
            common_config["use_cookies"] = str_to_bool(common_config["use_cookies"])
        if "username" in common_config and common_config["username"] is not None:
            common_config["username"] = common_config["username"].strip()
        if "password" in common_config and common_config["password"] is not None:
            common_config["password"] = common_config["password"].strip()

    # 检查并读取tiku节
    if config.has_section("tiku"):
        tiku_config = dict(config.items("tiku"))
        # 处理数值类型转换
        for key in ["delay", "cover_rate"]:
            if key in tiku_config:
                tiku_config[key] = float(tiku_config[key])

    # 检查并读取notification节
    if config.has_section("notification"):
        notification_config = dict(config.items("notification"))

    return common_config, tiku_config, notification_config


def build_config_from_args(args):
    """从命令行参数构建配置"""
    common_config = {
        "use_cookies": args.use_cookies,
        "username": args.username,
        "password": args.password,
        "course_list": [item.strip() for item in args.list.split(",") if item.strip()] if args.list else None,
        "speed": args.speed if args.speed else 1.0,
        "jobs": _validate_jobs(args.jobs),
        "notopen_action": args.notopen_action if args.notopen_action else "retry",
    }
    return common_config, {}, {}


def init_config():
    """初始化配置"""
    args = parse_args()

    if args.config:
        return load_config_from_file(args.config)
    return build_config_from_args(args)


def init_chaoxing(common_config, tiku_config):
    """初始化超星实例"""
    username = common_config.get("username", "")
    password = common_config.get("password", "")
    use_cookies = common_config.get("use_cookies", False)

    # 如果没有提供用户名密码，从命令行获取
    if (not username or not password) and not use_cookies:
        username = input("请输入你的手机号, 按回车确认\n手机号:")
        password = input("请输入你的密码, 按回车确认\n密码:")

    account = Account(username, password)

    # 设置题库
    tiku = Tiku()
    tiku.config_set(tiku_config)  # 载入配置
    tiku = tiku.get_tiku_from_config()  # 载入题库
    tiku.init_tiku()  # 初始化题库

    # 获取查询延迟设置
    query_delay = tiku_config.get("delay", 0)
    # 获取AI题库并发配置（仅在使用AI题库时生效）
    ai_concurrency = tiku_config.get("ai_concurrency")

    # 实例化超星API
    chaoxing = Chaoxing(account=account, tiku=tiku, query_delay=query_delay, ai_concurrency=ai_concurrency)

    return chaoxing


def process_job(
    chaoxing: Chaoxing,
    course: dict,
    job: dict,
    job_info: dict,
    speed: float,
    progress_callback=None,
    should_stop_callback=None,
) -> StudyResult:
    """处理单个任务点"""
    if callable(should_stop_callback) and should_stop_callback():
        return StudyResult.CANCELLED

    # 视频任务
    if job["type"] == "video":
        logger.trace(f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        # 超星的接口没有返回当前任务是否为Audio音频任务
        video_result = chaoxing.study_video(
            course,
            job,
            job_info,
            _speed=speed,
            _type="Video",
            progress_callback=progress_callback,
            should_stop=should_stop_callback,
        )
        if video_result.is_failure():
            logger.warning("当前任务非视频任务, 正在尝试音频任务解码")
            video_result = chaoxing.study_video(
                course,
                job,
                job_info,
                _speed=speed,
                _type="Audio",
                progress_callback=progress_callback,
                should_stop=should_stop_callback,
            )
        if video_result.is_failure():
            logger.warning(f"出现异常任务 -> 任务章节: {course['title']} 任务ID: {job['jobid']}, 已跳过")
        return video_result
    # 文档任务
    if job["type"] == "document":
        logger.trace(f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        return chaoxing.study_document(course, job)
    # 测验任务
    if job["type"] == "workid":
        logger.trace(f"识别到章节检测任务, 任务章节: {course['title']}")
        return chaoxing.study_work(course, job, job_info)
    # 阅读任务
    if job["type"] == "read":
        logger.trace(f"识别到阅读任务, 任务章节: {course['title']}")
        return chaoxing.study_read(course, job, job_info)
    # 直播任务
    if job["type"] == "live":
        logger.trace(f"识别到直播任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        try:
            # 准备直播所需参数
            defaults = {
                "userid": chaoxing.get_uid(),
                "clazzId": course.get("clazzId"),
                "knowledgeid": job_info.get("knowledgeid"),
            }

            # 创建直播对象
            live = Live(
                attachment=job,
                defaults=defaults,
                course_id=course.get("courseId"),
                session_manager=chaoxing.session_manager,
            )

            # 启动直播处理线程
            run_state = {"result": None}

            def _run_live():
                run_state["result"] = asyncio.run(LiveProcessor.run_live(live, speed, should_stop_callback))

            thread = threading.Thread(target=_run_live, daemon=True)
            thread.start()
            while thread.is_alive():
                thread.join(timeout=0.5)
            if run_state["result"] is False and callable(should_stop_callback) and should_stop_callback():
                return StudyResult.CANCELLED
            return StudyResult.SUCCESS if run_state["result"] else StudyResult.ERROR
        except Exception as e:
            logger.error(f"处理直播任务时出错: {str(e)}")
            return StudyResult.ERROR

    logger.error(f"未知任务类型: {job['type']}")
    return StudyResult.ERROR


def _process_jobs_inline(
    chaoxing: Chaoxing,
    course: dict,
    jobs: list[dict],
    job_info: dict,
    speed: float,
    config: dict[str, Any] | None,
) -> ChapterResult | None:
    video_progress_callback = config.get("video_progress_callback") if config else None
    stop_callback = config.get("should_stop") if config else None

    for job in jobs:
        if should_stop(config):
            return ChapterResult.CANCELLED
        result = process_job(
            chaoxing,
            course,
            job,
            job_info,
            speed,
            progress_callback=video_progress_callback,
            should_stop_callback=stop_callback,
        )
        if result == StudyResult.CANCELLED:
            return ChapterResult.CANCELLED
        if result.is_failure():
            return ChapterResult.ERROR
    return None


@dataclass(order=True)
class ChapterTask:
    index: int
    point: dict[str, Any]
    result: ChapterResult = ChapterResult.PENDING
    tries: int = 0


class JobProcessor:
    _JOIN_POLL_INTERVAL = 0.2

    def __init__(self, chaoxing: Chaoxing, course: dict[str, Any], tasks: list[ChapterTask], config: dict[str, Any]):
        self.chaoxing = chaoxing
        self.course = course
        self.speed = config["speed"]
        self.max_tries = 5
        self.tasks = tasks
        self.failed_tasks: list[ChapterTask] = []
        self.task_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.retry_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.wait_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.threads: list[threading.Thread] = []
        self.worker_num = config["jobs"]
        self.config = config
        self._drain_lock = threading.Lock()
        # Tasks that a worker has handed off to retry_queue but that retry_thread
        # has not yet re-queued onto task_queue. During that hand-off window the
        # task is NOT counted in task_queue.unfinished_tasks (the worker already
        # called task_done()), so run() must also wait for this counter to drain
        # before terminating. Otherwise unfinished_tasks transiently hits 0 and
        # run() exits mid-retry (F05).
        self._pending_retries = 0
        self._retry_lock = threading.Lock()

    def _enqueue_retry(self, task: "ChapterTask", stop_event: threading.Event | None = None) -> None:
        """Move a task into the retry pipeline.

        Increments the pending-retry counter BEFORE the worker's task_done()
        decrements unfinished_tasks, so the task is continuously accounted for.
        """
        with self._drain_lock:
            if stop_event is not None and stop_event.is_set():
                return
            with self._retry_lock:
                self._pending_retries += 1
            try:
                self.retry_queue.put(task)
            except BaseException:
                self._release_pending_retry()
                raise

    def _release_pending_retry(self) -> None:
        with self._retry_lock:
            if self._pending_retries > 0:
                self._pending_retries -= 1

    def _has_outstanding_work(self) -> bool:
        with self._retry_lock:
            pending = self._pending_retries
        return self.task_queue.unfinished_tasks > 0 or pending > 0

    def run(self):
        """Process this batch and always shut down the threads it starts.

        The queues intentionally remain instance attributes for compatibility
        with the existing processor API, but the stop event and thread list belong
        to this invocation only. In particular, a worker from an earlier run must
        never observe the stop state of a later run.
        """
        run_stop = threading.Event()
        run_threads: list[threading.Thread] = []
        self.threads = run_threads
        thread_error: BaseException | None = None
        thread_error_lock = threading.Lock()
        run_exception: BaseException | None = None

        def record_thread_error(exc: BaseException) -> None:
            nonlocal thread_error
            with thread_error_lock:
                if thread_error is None:
                    thread_error = exc

        def run_worker() -> None:
            try:
                self.worker_thread(run_stop)
            except BaseException as exc:
                record_thread_error(exc)

        def run_retry() -> None:
            try:
                self.retry_thread(run_stop)
            except BaseException as exc:
                record_thread_error(exc)

        try:
            # A non-positive worker count would leave queued tasks with no
            # worker able to consume them, making the controller wait forever.
            # Validate before enqueueing or starting any thread.
            self.worker_num = _validate_jobs(self.worker_num)
            for task in self.tasks:
                self.task_queue.put(task)

            started_workers = 0
            for _ in range(self.worker_num):
                thread = threading.Thread(target=run_worker, daemon=True)
                try:
                    thread.start()
                except RuntimeError as exc:
                    if not _is_thread_start_failure(exc):
                        raise
                    if started_workers == 0:
                        logger.warning("Cannot start Chaoxing worker thread; processing chapters inline")
                        self._drain_pending_tasks()
                        self._run_inline()
                        return
                    logger.warning(
                        "Cannot start all Chaoxing worker threads; continuing with {} worker(s)",
                        started_workers,
                    )
                    break
                else:
                    run_threads.append(thread)
                    started_workers += 1

            retry_thread = threading.Thread(target=run_retry, daemon=True)
            try:
                retry_thread.start()
            except RuntimeError as exc:
                if not _is_thread_start_failure(exc):
                    raise
                logger.warning("Cannot start Chaoxing retry thread; retry queue will be promoted by controller loop")
            else:
                run_threads.append(retry_thread)

            while True:
                if thread_error is not None:
                    raise thread_error

                self._promote_retry_once(run_stop)
                if thread_error is not None:
                    raise thread_error

                if should_stop(self.config):
                    self._drain_pending_tasks()
                    if not self._has_outstanding_work():
                        break
                elif not self._has_outstanding_work():
                    break
                run_stop.wait(0.2)
        except BaseException as exc:
            run_exception = exc
            raise
        finally:
            cleanup_error = self._shutdown_run(run_stop, run_threads)
            if run_exception is None:
                if thread_error is not None:
                    raise thread_error
                if cleanup_error is not None:
                    raise cleanup_error

    def _shutdown_run(
        self,
        run_stop: threading.Event,
        run_threads: list[threading.Thread],
    ) -> BaseException | None:
        """Stop and join the threads belonging to one ``run`` call."""
        run_stop.set()
        cleanup_error: BaseException | None = None

        def record_cleanup_error(exc: BaseException) -> None:
            nonlocal cleanup_error
            if cleanup_error is None:
                cleanup_error = exc

        # Workers and the retry loop use timed queue gets, so setting the event
        # is enough to wake them without putting incomparable values in the
        # priority queues. Drain first to discard work requested for cancellation
        # or an exceptional run, then wait until every started thread has really
        # exited. Cleanup is best-effort: remember the first failure but continue
        # joining every other thread and make one final drain attempt.
        try:
            self._drain_pending_tasks()
        except BaseException as exc:
            record_cleanup_error(exc)

        for thread in run_threads:
            while True:
                try:
                    if not thread.is_alive():
                        break
                    thread.join(timeout=self._JOIN_POLL_INTERVAL)
                except BaseException as exc:
                    record_cleanup_error(exc)
                    # A transient join failure must not let a live worker escape
                    # this run. Sleep before retrying so a persistently broken
                    # join implementation cannot create a busy loop while the
                    # worker is responding to the stop event.
                    time.sleep(self._JOIN_POLL_INTERVAL)

        try:
            self._drain_pending_tasks()
        except BaseException as exc:
            record_cleanup_error(exc)

        return cleanup_error

    def _promote_retry_once(self, stop_event: threading.Event | None = None) -> None:
        with self._drain_lock:
            try:
                task = self.retry_queue.get_nowait()
            except Empty:
                return
            except ShutDown:
                return

            try:
                if stop_event is not None and stop_event.is_set():
                    return
                # Re-queueing increments unfinished_tasks by 1 (the matching +1
                # for the task_done() the worker already issued on the retry
                # decision). Put FIRST, then drop the pending-retry counter, so
                # the task is never simultaneously absent from both
                # unfinished_tasks and _pending_retries (which would let run()
                # exit mid-retry).
                self.task_queue.put(task)
            finally:
                try:
                    self.retry_queue.task_done()
                except ValueError:
                    pass
                self._release_pending_retry()

    def _run_inline(self) -> None:
        for task in sorted(self.tasks, key=lambda item: item.index):
            while True:
                if should_stop(self.config):
                    self._drain_pending_tasks()
                    return

                try:
                    task.result = process_chapter(self.chaoxing, self.course, task.point, self.speed, self.config)
                except Exception:
                    logger.exception("Chapter processing crashed: {}", task.point.get("title", "unknown"))
                    task.result = ChapterResult.ERROR

                match task.result:
                    case ChapterResult.SUCCESS:
                        logger.debug("Task success: {}", task.point["title"])
                        break

                    case ChapterResult.NOT_OPEN:
                        if self.config["notopen_action"] == "continue":
                            logger.warning("章节未开启: {}, 正在跳过", task.point["title"])
                            break

                        if task.tries >= self.max_tries:
                            logger.error(
                                "章节未开启: {} 可能由于上一章节的章节检测未完成, 也可能由于该章节因为时效已关闭，"
                                "请手动检查完成并提交再重试。或者在配置中配置(自动跳过关闭章节/开启题库并启用提交)",
                                task.point["title"],
                            )
                            break
                        time.sleep(1)

                    case ChapterResult.ERROR:
                        task.tries += 1
                        logger.warning(
                            "Retrying task {} ({}/{} attempts)",
                            task.point["title"],
                            task.tries,
                            self.max_tries,
                        )
                        if task.tries >= self.max_tries:
                            logger.error("Max retries reached for task: {}", task.point["title"])
                            self.failed_tasks.append(task)
                            break
                        time.sleep(1)

                    case ChapterResult.CANCELLED:
                        logger.info("Task cancelled: {}", task.point["title"])
                        self._drain_pending_tasks()
                        return

                    case _:
                        logger.error("Invalid task state {} for task {}", task.result, task.point["title"])
                        self.failed_tasks.append(task)
                        break

    def _drain_pending_tasks(self):
        with self._drain_lock:
            self._drain_pending_tasks_locked()

    def _drain_pending_tasks_locked(self) -> None:
        # Every item removed from task_queue or retry_queue has a matching
        # task_done(). Retry items additionally release the hand-off counter.
        for queue_obj, is_task_queue, is_retry in (
            (self.task_queue, True, False),
            (self.retry_queue, False, True),
            (self.wait_queue, False, False),
        ):
            while True:
                try:
                    queue_obj.get_nowait()
                except Empty:
                    break
                except ShutDown:
                    break
                else:
                    if is_task_queue or is_retry:
                        try:
                            queue_obj.task_done()
                        except ValueError:
                            pass
                    if is_retry:
                        self._release_pending_retry()

    @log_error
    def worker_thread(self, stop_event: threading.Event | None = None):
        tqdm.set_lock(tqdm.get_lock())
        while True:
            try:
                task = self.task_queue.get(timeout=0.2)
            except Empty:
                if stop_event is not None and stop_event.is_set():
                    return
                continue
            except ShutDown:
                logger.info("Queue shut down")
                return

            try:
                if stop_event is not None and stop_event.is_set():
                    return

                # 处理单个章节，并在需要时通过 config 中的回调上报章节完成进度
                try:
                    task.result = process_chapter(self.chaoxing, self.course, task.point, self.speed, self.config)
                except Exception:
                    logger.exception("Chapter processing crashed: {}", task.point.get("title", "unknown"))
                    task.result = ChapterResult.ERROR

                # A run-level stop can be requested while process_chapter is in
                # flight.  Do not create a fresh retry after shutdown starts.
                if stop_event is not None and stop_event.is_set():
                    return

                match task.result:
                    case ChapterResult.SUCCESS:
                        logger.debug("Task success: {}", task.point["title"])
                        logger.debug(f"unfinished task: {self.task_queue.unfinished_tasks}")

                    case ChapterResult.NOT_OPEN:
                        # task.tries += 1
                        if self.config["notopen_action"] == "continue":
                            logger.warning("章节未开启: {}, 正在跳过", task.point["title"])
                            continue

                        if task.tries >= self.max_tries:
                            logger.error(
                                "章节未开启: {} 可能由于上一章节的章节检测未完成, 也可能由于该章节因为时效已关闭，"
                                "请手动检查完成并提交再重试。或者在配置中配置(自动跳过关闭章节/开启题库并启用提交)",
                                task.point["title"],
                            )
                            continue

                        # Hand the task to the retry pipeline and mark THIS
                        # processing pass done in the finally block below.
                        self._enqueue_retry(task, stop_event)

                    case ChapterResult.ERROR:
                        task.tries += 1
                        logger.warning(
                            "Retrying task {} ({}/{} attempts)", task.point["title"], task.tries, self.max_tries
                        )
                        if task.tries >= self.max_tries:
                            logger.error("Max retries reached for task: {}", task.point["title"])
                            self.failed_tasks.append(task)
                            continue
                        # See NOT_OPEN branch: retry_thread re-puts the task,
                        # while this pass is balanced in finally below.
                        self._enqueue_retry(task, stop_event)

                    case ChapterResult.CANCELLED:
                        logger.info("Task cancelled: {}", task.point["title"])
                        self._drain_pending_tasks()
                        return

                    case _:
                        logger.error("Invalid task state {} for task {}", task.result, task.point["title"])
                        self.failed_tasks.append(task)
            finally:
                self.task_queue.task_done()

    @log_error
    def retry_thread(self, stop_event: threading.Event | None = None):
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return
                if should_stop(self.config):
                    self._drain_pending_tasks()
                    return
                try:
                    task = self.retry_queue.get(timeout=self._JOIN_POLL_INTERVAL)
                except Empty:
                    continue
                except ShutDown:
                    return

                pending_released = False
                try:
                    # should_stop is an application callback and may itself call
                    # back into the processor. Never invoke it while holding the
                    # non-reentrant drain lock.
                    stopping = (stop_event is not None and stop_event.is_set()) or should_stop(self.config)

                    # Re-queueing increments unfinished_tasks by 1 (the
                    # matching +1 for the task_done() the worker already issued
                    # on the retry decision). Put FIRST, then drop the
                    # pending-retry counter, so the task is never simultaneously
                    # absent from both counters (F05).
                    with self._drain_lock:
                        if stopping or (stop_event is not None and stop_event.is_set()):
                            self._release_pending_retry()
                            pending_released = True
                            self._drain_pending_tasks_locked()
                            return
                        self.task_queue.put(task)
                        self._release_pending_retry()
                        pending_released = True
                finally:
                    if not pending_released:
                        self._release_pending_retry()
                    try:
                        self.retry_queue.task_done()
                    except ValueError:
                        pass

                if stop_event is not None:
                    if stop_event.wait(1):
                        return
                else:
                    time.sleep(1)
        except ShutDown:
            pass


def process_chapter(
    chaoxing: Chaoxing,
    course: dict[str, Any],
    point: dict[str, Any],
    speed: float,
    config: dict[str, Any] | None = None,
) -> ChapterResult:
    """处理单个章节

    当所有任务点成功完成时，如果 config 中提供了 chapter_done_callback，
    则回调通知外部（如 Web 端）更新进度统计。
    """
    logger.info(f'当前章节: {point["title"]}')

    # 通知外部当前章节开始（用于前端显示当前正在学习的章节）
    if config is not None:
        start_cb = config.get("chapter_start_callback")
        if callable(start_cb):
            try:
                start_cb(course, point)
            except Exception as e:
                logger.debug(f"调用 chapter_start_callback 时出错: {e}")
    if point["has_finished"]:
        logger.info(f'章节：{point["title"]} 已完成所有任务点')
        # 该章节在超星端已标记完成：必须计入"已完成章节"统计。learning_manager
        # 把所有章节(含已完成)都加进 total_chapters，而 completed_chapters 只在
        # chapter_done_callback 里累加；若此处直接 return 而不回调，预先完成的章节
        # 只进 total 不进 completed，进度条永远到不了 100%。(F-progress)
        if config is not None:
            done_cb = config.get("chapter_done_callback")
            if callable(done_cb):
                try:
                    done_cb(course, point)
                except Exception as e:
                    logger.debug(f"调用 chapter_done_callback 时出错: {e}")
        return ChapterResult.SUCCESS

    # 随机等待，避免请求过快
    chaoxing.rate_limiter.limit_rate(random_time=True, random_min=0, random_max=0.2)

    # 获取当前章节的所有任务点
    job_info = None
    jobs, job_info = chaoxing.get_job_list(course, point)
    if should_stop(config):
        return ChapterResult.CANCELLED

    # 发现未开放章节, 根据配置处理
    if job_info and job_info.get("notOpen", False):
        return ChapterResult.NOT_OPEN

    # get_job_list 失败时会返回 ({}, {}) —— 既无 jobs 也无 job_info，
    # 不能把它当成"空任务/已完成"静默成功，否则章节会被错误标记 SUCCESS。
    if not job_info and not jobs:
        logger.error("获取章节任务列表失败: {}", point.get("title", "unknown"))
        return ChapterResult.ERROR

    # 已经默认处理空任务，此处不需要判断
    if not jobs:
        pass

    # TODO: 个别章节很恶心，多到5个点，可以并行处理，将来会让不同课程不同章节的所有任务点共享一个队列，从而实现全局并行
    job_results: list[StudyResult] = []
    video_progress_callback = config.get("video_progress_callback") if config else None
    stop_callback = config.get("should_stop") if config else None
    executor = ThreadPoolExecutor(max_workers=5)
    fast_shutdown = False
    try:
        pending = set()
        try:
            for job in jobs:
                pending.add(
                    executor.submit(
                        process_job,
                        chaoxing,
                        course,
                        job,
                        job_info,
                        speed,
                        progress_callback=video_progress_callback,
                        should_stop_callback=stop_callback,
                    )
                )
        except RuntimeError as exc:
            if not _is_thread_start_failure(exc):
                raise
            fast_shutdown = True
            for future in pending:
                future.cancel()
            logger.warning("Cannot start Chaoxing job worker thread; processing task points inline")
            inline_result = _process_jobs_inline(chaoxing, course, jobs, job_info, speed, config)
            if inline_result is not None:
                return inline_result
            pending = set()
        while pending:
            if should_stop(config):
                fast_shutdown = True
                for future in pending:
                    future.cancel()
                return ChapterResult.CANCELLED
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            if not done:
                continue
            for future in done:
                result = future.result()
                job_results.append(result)
                if result == StudyResult.CANCELLED:
                    fast_shutdown = True
                    for pending_future in pending:
                        pending_future.cancel()
                    return ChapterResult.CANCELLED
                if result.is_failure():
                    fast_shutdown = True
                    for pending_future in pending:
                        pending_future.cancel()
                    return ChapterResult.ERROR
    finally:
        executor.shutdown(wait=not fast_shutdown, cancel_futures=fast_shutdown)

    for result in job_results:
        if result == StudyResult.CANCELLED:
            return ChapterResult.CANCELLED
        if result.is_failure():
            return ChapterResult.ERROR

    # 所有任务点均成功，通知外部本章节已完成（用于前端进度统计）
    if config is not None:
        callback = config.get("chapter_done_callback")
        if callable(callback):
            try:
                callback(course, point)
            except Exception as e:
                logger.debug(f"调用 chapter_done_callback 时出错: {e}")

    return ChapterResult.SUCCESS


def process_course(chaoxing: Chaoxing, course: dict[str, Any], config: dict):
    """处理单个课程"""
    logger.info(f"开始学习课程: {course['title']}")

    # 获取当前课程的所有章节
    point_list = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])

    # 为了支持课程任务回滚, 采用下标方式遍历任务点

    _old_format_sizeof = tqdm.format_sizeof
    _old_tqdm_lock = tqdm.get_lock()
    try:
        tqdm.format_sizeof = format_time
        tqdm.set_lock(RLock())

        tasks = []

        for i, point in enumerate(point_list["points"]):
            task = ChapterTask(point=point, index=i)
            tasks.append(task)
        p = JobProcessor(chaoxing, course, tasks, config)
        p.run()
    finally:
        tqdm.format_sizeof = _old_format_sizeof
        tqdm.set_lock(_old_tqdm_lock)


def filter_courses(all_course, course_list):
    """过滤要学习的课程"""
    if not course_list:
        # 手动输入要学习的课程ID列表
        print("*" * 10 + "课程列表" + "*" * 10)
        for course in all_course:
            print(f"ID: {course['courseId']} 课程名: {course['title']}")
        print("*" * 28)
        try:
            course_list = input("请输入想要学习的课程列表,以逗号分隔,例: 2151141,189191,198198\n").split(",")
        except Exception as e:
            raise InputFormatError("输入格式错误") from e

    # 筛选需要学习的课程
    course_task = []
    course_ids = []
    for course in all_course:
        if course["courseId"] in course_list and course["courseId"] not in course_ids:
            course_task.append(course)
            course_ids.append(course["courseId"])

    # 如果没有指定课程，则学习所有课程
    if not course_task:
        course_task = all_course

    return course_task


def format_time(num, suffix="", divisor=""):
    total_time = round(num)
    sec = total_time % 60
    mins = (total_time % 3600) // 60
    hrs = total_time // 3600

    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{sec:02d}"

    return f"{mins:02d}:{sec:02d}"


def main():
    """主程序入口"""
    # Bind a no-op notifier up front so the error handler below can always call
    # notification.send(...) even if setup fails before the real notifier is
    # built (avoids UnboundLocalError masking the real error).
    notification = NotificationFactory.create_service(None)
    try:
        # 初始化配置
        common_config, tiku_config, notification_config = init_config()

        # 强制播放按照配置文件调节
        common_config["speed"] = min(2.0, max(1.0, common_config.get("speed", 1.0)))
        common_config["notopen_action"] = common_config.get("notopen_action", "retry")

        # 初始化超星实例
        chaoxing = init_chaoxing(common_config, tiku_config)

        # 设置外部通知（config_set + get_notification_from_config + init_notification）
        notification = NotificationFactory.create_service(notification_config)

        # 检查当前登录状态
        _login_state = chaoxing.login(login_with_cookies=common_config.get("use_cookies", False))
        if not _login_state["status"]:
            raise LoginError(_login_state["msg"])

        # 获取所有的课程列表
        all_course = chaoxing.get_course_list()

        # 过滤要学习的课程
        course_task = filter_courses(all_course, common_config.get("course_list"))

        # 开始学习
        logger.info(f"课程列表过滤完毕, 当前课程任务数量: {len(course_task)}")
        for course in course_task:
            process_course(chaoxing, course, common_config)

        logger.info("所有课程学习任务已完成")
        notification.send("chaoxing : 所有课程学习任务已完成")

    except SystemExit as e:
        if e.code != 0:
            logger.error(f"错误: 程序异常退出, 返回码: {e.code}")
        sys.exit(e.code)
    except KeyboardInterrupt as e:
        logger.error(f"错误: 程序被用户手动中断, {e}")
    except BaseException as e:
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        try:
            notification.send(f"chaoxing : 出现错误 {type(e).__name__}: {e}\n{traceback.format_exc()}")
        except Exception:
            pass  # 如果通知发送失败，忽略异常
        raise e


if __name__ == "__main__":
    main()
