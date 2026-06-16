"""
通知服务模块，用于向外部服务发送通知消息。
支持多种通知服务，如ServerChan、Qmsg和Bark。
"""

import configparser
import ipaddress
import socket
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import requests
from loguru import logger

# Hostnames that are never legitimate notification targets (cloud metadata, etc.).
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
    }
)


def _is_blocked_ip(ip: "ipaddress._BaseAddress") -> bool:
    """Return True for any address that must not be reachable from the server."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        # IPv4-mapped/compatible IPv6 that wrap a blocked v4 address.
        or (getattr(ip, "ipv4_mapped", None) is not None and _is_blocked_ip(ip.ipv4_mapped))
    )


def validate_notification_url(url: str | None) -> bool:
    """SSRF guard for outbound notification webhooks (F55).

    Accept only http/https URLs whose host does not resolve to a
    loopback/private/link-local/reserved/metadata address. This is a
    best-effort guard against using the notification feature as an SSRF
    primitive against cloud metadata or internal services.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
    except (ValueError, TypeError):
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return False

    # If the host is a literal IP, validate it directly.
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        return not _is_blocked_ip(literal_ip)

    # Otherwise resolve the hostname and reject if ANY resolved address is internal.
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # Cannot resolve -> treat as unsafe rather than fetching blindly.
        return False

    for info in infos:
        sockaddr = info[4]
        try:
            resolved = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if _is_blocked_ip(resolved):
            return False

    return True


class NotificationService(ABC):
    """
    通知服务基类，定义通知服务的公共接口和实现。
    所有具体的通知服务类应继承此类并实现必要的方法。
    """

    CONFIG_PATH = "config.ini"

    def __init__(self):
        """初始化通知服务"""
        self.name = self.__class__.__name__
        self.url = ""
        self.tg_chat_id = ""
        self._conf = None
        self.disabled = False

    def config_set(self, config: dict[str, str]) -> None:
        """
        设置通知服务的配置

        Args:
            config: 包含配置参数的字典
        """
        self._conf = config

    def _load_config_from_file(self) -> dict[str, str] | None:
        """
        从配置文件中加载通知服务的配置

        Returns:
            成功返回配置字典，失败返回None
        """
        try:
            config = configparser.ConfigParser()
            config.read(self.CONFIG_PATH, encoding="utf8")
            return config["notification"]
        except (KeyError, FileNotFoundError):
            logger.info("未找到notification配置，已忽略外部通知功能")
            self.disabled = True
            return None

    def init_notification(self) -> None:
        """初始化通知服务，加载配置并进行必要的设置"""
        if not self._conf:
            self._conf = self._load_config_from_file()

        if not self.disabled and self._conf:
            self._init_service()

    @abstractmethod
    def _init_service(self) -> None:
        """
        初始化特定的通知服务，由子类实现
        """

    @abstractmethod
    def _send(self, message: str) -> bool:
        """
        发送通知消息，由子类实现

        Args:
            message: 要发送的消息内容

        Returns:
            发送成功返回True，失败返回False
        """

    def _url_allowed(self) -> bool:
        """Reject outbound POSTs to unvalidated/internal URLs (F55 SSRF guard)."""
        if not validate_notification_url(self.url):
            logger.error(f"拒绝向不被允许的通知地址发送请求: {self.url!r}")
            return False
        return True

    def send(self, message: str) -> bool:
        """
        发送通知消息的公共接口

        Args:
            message: 要发送的消息内容

        Returns:
            发送成功返回True，未发送或失败返回False
        """
        if self.disabled:
            return False
        return bool(self._send(message))


class NotificationFactory:
    """
    通知服务工厂类，用于创建和获取通知服务实例
    """

    @staticmethod
    def create_service(config: dict[str, str] | None = None) -> NotificationService:
        """
        根据配置创建通知服务实例

        Args:
            config: 通知服务的配置，如果为None则从配置文件加载

        Returns:
            通知服务实例
        """
        service = DefaultNotification()

        if config:
            service.config_set(config)

        # 尝试获取具体的通知服务
        service = service.get_notification_from_config()
        service.init_notification()

        return service


class DefaultNotification(NotificationService):
    """
    默认通知服务，当未配置任何通知服务时使用
    """

    def _init_service(self) -> None:
        pass

    def _send(self, message: str) -> bool:
        return False

    def get_notification_from_config(self) -> NotificationService:
        """
        根据配置创建具体的通知服务实例

        Returns:
            通知服务实例
        """
        if not self._conf:
            self._conf = self._load_config_from_file()

        if self.disabled:
            return self

        try:
            provider_name = self._conf["provider"]
            if not provider_name:
                raise KeyError("未指定通知服务提供商")

            # 获取对应的通知服务类
            provider_class = globals().get(provider_name)
            if not provider_class:
                logger.error(f"未找到名为 {provider_name} 的通知服务提供商")
                self.disabled = True
                return self

            # 创建通知服务实例
            service = provider_class()
            service.config_set(self._conf)
            return service

        except KeyError:
            self.disabled = True
            logger.info("未找到外部通知配置，已忽略外部通知功能")
            return self


class ServerChan(NotificationService):
    """
    Server酱通知服务
    """

    def _init_service(self) -> None:
        """初始化Server酱服务"""
        if not self._conf or not self._conf.get("url"):
            self.disabled = True
            logger.info("未找到Server酱url配置，已忽略该通知服务")
            return

        self.url = self._conf["url"]
        logger.info(f"已初始化Server酱通知服务，URL: {self.url}")

    def _send(self, message: str) -> bool:
        """
        通过Server酱发送通知

        Args:
            message: 要发送的消息内容
        """
        if not self._url_allowed():
            return False

        params = {
            "text": message,  # 兼容两个版本的Server酱
            "desp": message,
        }
        headers = {"Content-Type": "application/json;charset=utf-8"}

        try:
            response = requests.post(self.url, json=params, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            logger.info(f"Server酱通知发送成功: {result}")
            return True
        except requests.RequestException as e:
            logger.error(f"Server酱通知发送失败: {e}")
        except ValueError as e:
            logger.error(f"Server酱返回数据解析失败: {e}")
        return False


class Qmsg(NotificationService):
    """
    Qmsg酱通知服务
    """

    def _init_service(self) -> None:
        """初始化Qmsg酱服务"""
        if not self._conf or not self._conf.get("url"):
            self.disabled = True
            logger.info("未找到Qmsg酱url配置，已忽略该通知服务")
            return

        self.url = self._conf["url"]
        logger.info(f"已初始化Qmsg酱通知服务，URL: {self.url}")

    def _send(self, message: str) -> bool:
        """
        通过Qmsg酱发送通知

        Args:
            message: 要发送的消息内容
        """
        if not self._url_allowed():
            return False

        params = {"msg": message}
        headers = {"Content-Type": "application/json;charset=utf-8"}

        try:
            response = requests.post(self.url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            logger.info(f"Qmsg酱通知发送成功: {result}")
            return True
        except requests.RequestException as e:
            logger.error(f"Qmsg酱通知发送失败: {e}")
        except ValueError as e:
            logger.error(f"Qmsg酱返回数据解析失败: {e}")
        return False


class Bark(NotificationService):
    """
    Bark通知服务
    """

    def _init_service(self) -> None:
        """初始化Bark服务"""
        if not self._conf or not self._conf.get("url"):
            self.disabled = True
            logger.info("未找到Bark的url配置，已忽略该通知服务")
            return

        self.url = self._conf["url"]
        logger.info(f"已初始化Bark通知服务，URL: {self.url}")

    def _send(self, message: str) -> bool:
        """
        通过Bark发送通知

        Args:
            message: 要发送的消息内容
        """
        if not self._url_allowed():
            return False

        params = {"body": message}

        try:
            response = requests.post(self.url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()
            logger.info(f"Bark通知发送成功: {result}")
            return True
        except requests.RequestException as e:
            logger.error(f"Bark通知发送失败: {e}")
        except ValueError as e:
            logger.error(f"Bark返回数据解析失败: {e}")
        return False


class Telegram(NotificationService):
    """
    通过Telegram发送通知
    """

    def _init_service(self) -> None:
        """初始化Telegram服务"""
        if not self._conf or not self._conf.get("url") or not self._conf.get("tg_chat_id"):
            self.disabled = True
            logger.info("未找到Telegram的url或tg_chat_id配置，已忽略该通知服务")
            return
        self.tg_chat_id = self._conf["tg_chat_id"]
        self.url = self._conf["url"]
        logger.info(f"已初始化Telegram通知服务，Chat_id: {self.tg_chat_id} URL: {self.url}")

    def _send(self, message: str) -> bool:
        """
        通过Telegram发送通知

        Args:
            message: 要发送的消息内容
        """
        if not self._url_allowed():
            return False

        params = {"chat_id": self.tg_chat_id, "text": message, "parse_mode": "HTML"}

        try:
            response = requests.post(self.url, data=params, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                logger.info(f"Telegram通知发送成功: {result}")
                return True
            logger.error(f"Telegram通知发送失败: {result}")
        except requests.RequestException as e:
            logger.error(f"Telegram通知发送失败: {e}")
        except ValueError as e:
            logger.error(f"Telegram返回数据解析失败: {e}")
        return False


# 为了向后兼容，保留原来的Notification类
Notification = DefaultNotification
