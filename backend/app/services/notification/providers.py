"""
通知服务模块，用于向外部服务发送通知消息。
支持多种通知服务，如ServerChan、Qmsg和Bark。
"""

import configparser
import ipaddress
import socket
from abc import ABC, abstractmethod
from urllib.parse import unquote, urlparse

import requests
from loguru import logger

# Hostnames that are never legitimate notification targets (cloud metadata, etc.).
_BLOCKED_HOSTNAMES = frozenset(
    {
        "instance-data.ec2.internal",
        "localhost",
        "metadata.azure.com",
        "metadata.google.internal",
        "metadata",
    }
)


def _is_blocked_ip(ip: "ipaddress._BaseAddress") -> bool:
    """Return True for any address that must not be reachable from the server."""
    # Treat all IPv4-mapped IPv6 literals as unsafe. Even when the mapped IPv4
    # value is globally routable, different HTTP clients can disagree about
    # the address family and destination formatting.
    if getattr(ip, "ipv4_mapped", None) is not None:
        return True
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_notification_url(url: str | None) -> bool:
    """SSRF guard for outbound notification webhooks (F55).

    Accept only http/https URLs whose host does not resolve to a
    loopback/private/link-local/reserved/metadata address. This is a
    best-effort guard against using the notification feature as an SSRF
    primitive against cloud metadata or internal services.

    The URL is validated using the same authority syntax that ``requests``
    receives. In particular, userinfo and backslashes are rejected before DNS
    resolution. Both are dangerous here because URL parsers do not agree on
    how they delimit the authority (for example, a backslash can make a
    public-looking hostname resolve to a loopback address in requests).
    """
    if not url or not isinstance(url, str):
        return False

    try:
        normalized_url = url.strip()

        # Requests normalizes backslashes in a URL before connecting. Reject
        # them (including percent-encoded backslashes) in the complete input,
        # rather than only in ``parsed.netloc``, so validation and the eventual
        # request cannot disagree about the authority boundary.
        if not normalized_url or "\\" in normalized_url or "%5c" in normalized_url.lower():
            return False

        # Raw C0 controls are stripped/normalized by URL clients. Rejecting
        # them avoids another validation/request parsing mismatch while still
        # allowing ordinary (properly percent-encoded) URL characters.
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in normalized_url):
            return False

        parsed = urlparse(normalized_url)

        if parsed.scheme not in ("http", "https"):
            return False

        # A literal ``@`` denotes userinfo, including an empty userinfo
        # component (``http://@host``). Percent escapes in an authority are
        # rejected as well because clients may decode them at different
        # stages (and could turn an encoded delimiter into userinfo).
        authority = parsed.netloc
        decoded_authority = unquote(authority)
        if authority.endswith(":"):
            # ``urlparse`` reports an empty port as ``None``; reject the
            # explicit delimiter so it cannot be interpreted differently by
            # requests/urllib3.
            return False
        if (
            "@" in authority
            or "@" in decoded_authority
            or "\\" in authority
            or "\\" in decoded_authority
            or "%" in authority
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False

        # Accessing ``port`` forces malformed ports (e.g. ``:abc`` or an
        # out-of-range integer) to fail closed instead of being sent to a
        # different URL parser later.
        parsed_port = parsed.port
        if parsed_port is not None and not 1 <= parsed_port <= 65535:
            return False
    except Exception:
        return False

    try:
        hostname = parsed.hostname
        if not hostname:
            return False

        normalized_hostname = hostname.rstrip(".").lower()
        if not normalized_hostname or normalized_hostname in _BLOCKED_HOSTNAMES:
            return False

        # If the host is a literal IP, validate it directly. ``ip_address``
        # also handles IPv6 and IPv4-mapped IPv6 literals.
        try:
            literal_ip = ipaddress.ip_address(hostname)
        except ValueError:
            literal_ip = None
        if literal_ip is not None:
            return not _is_blocked_ip(literal_ip)

        # Otherwise resolve the hostname and reject if ANY resolved address is
        # internal. An empty or malformed answer is a resolution failure, not
        # evidence that the host is safe.
        infos = socket.getaddrinfo(hostname, None)
        if not infos:
            return False
    except Exception:
        # Cannot resolve -> treat as unsafe rather than fetching blindly.
        return False

    try:
        for info in infos:
            try:
                sockaddr = info[4]
                resolved = ipaddress.ip_address(sockaddr[0])
            except Exception:
                return False
            try:
                if _is_blocked_ip(resolved):
                    return False
            except Exception:
                return False
    except Exception:
        # Treat resolver iterators that fail while being consumed as unsafe.
        return False

    return True


def _is_redirect_response(response) -> bool:
    """Return True when a notification response is any HTTP redirect."""
    status_code = getattr(response, "status_code", None)
    # Real requests responses always expose an integer status code. The type
    # guard also keeps lightweight requests mocks (without status_code) usable.
    return isinstance(status_code, int) and 300 <= status_code < 400


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
        try:
            allowed = validate_notification_url(self.url)
        except Exception:
            # Keep the outbound path fail-closed even if a resolver or URL
            # parser unexpectedly escapes the validator's defensive guards.
            allowed = False
        if not allowed:
            logger.error(f"{self.name} 通知地址校验失败")
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

            # Only configured provider implementations are instantiable here;
            # module globals also contain imported modules and logger objects.
            provider_class = _PROVIDER_CLASSES.get(provider_name) if isinstance(provider_name, str) else None
            if not provider_class:
                logger.error("未找到配置的通知服务提供商")
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
        logger.info(f"已初始化{self.name}通知服务")

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
            response = requests.post(
                self.url,
                json=params,
                headers=headers,
                timeout=10,
                allow_redirects=False,
            )
            if _is_redirect_response(response):
                logger.error(f"Server酱通知发送失败：服务返回重定向状态 {response.status_code}")
                return False
            response.raise_for_status()
            response.json()
            logger.info(f"{self.name}通知发送成功")
            return True
        except requests.RequestException as e:
            logger.error(f"{self.name}通知发送失败: {type(e).__name__}")
        except ValueError as e:
            logger.error(f"{self.name}返回数据解析失败: {type(e).__name__}")
        except Exception as e:
            # A provider/parser implementation must not expose URL or token
            # contents if an unexpected outbound error escapes requests.
            logger.error(f"{self.name}通知发送失败: {type(e).__name__}")
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
        logger.info(f"已初始化{self.name}通知服务")

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
            response = requests.post(
                self.url,
                params=params,
                headers=headers,
                timeout=10,
                allow_redirects=False,
            )
            if _is_redirect_response(response):
                logger.error(f"Qmsg酱通知发送失败：服务返回重定向状态 {response.status_code}")
                return False
            response.raise_for_status()
            response.json()
            logger.info(f"{self.name}通知发送成功")
            return True
        except requests.RequestException as e:
            logger.error(f"{self.name}通知发送失败: {type(e).__name__}")
        except ValueError as e:
            logger.error(f"{self.name}返回数据解析失败: {type(e).__name__}")
        except Exception as e:
            logger.error(f"{self.name}通知发送失败: {type(e).__name__}")
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
        logger.info(f"已初始化{self.name}通知服务")

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
            response = requests.post(
                self.url,
                params=params,
                timeout=10,
                allow_redirects=False,
            )
            if _is_redirect_response(response):
                logger.error(f"Bark通知发送失败：服务返回重定向状态 {response.status_code}")
                return False
            response.raise_for_status()
            response.json()
            logger.info(f"{self.name}通知发送成功")
            return True
        except requests.RequestException as e:
            logger.error(f"{self.name}通知发送失败: {type(e).__name__}")
        except ValueError as e:
            logger.error(f"{self.name}返回数据解析失败: {type(e).__name__}")
        except Exception as e:
            logger.error(f"{self.name}通知发送失败: {type(e).__name__}")
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
        logger.info(f"已初始化{self.name}通知服务")

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
            response = requests.post(
                self.url,
                data=params,
                timeout=10,
                allow_redirects=False,
            )
            if _is_redirect_response(response):
                logger.error(f"Telegram通知发送失败：服务返回重定向状态 {response.status_code}")
                return False
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                logger.info(f"{self.name}通知发送成功")
                return True
            logger.error(f"{self.name}通知发送失败: provider response rejected")
        except requests.RequestException as e:
            logger.error(f"{self.name}通知发送失败: {type(e).__name__}")
        except ValueError as e:
            logger.error(f"{self.name}返回数据解析失败: {type(e).__name__}")
        except Exception as e:
            logger.error(f"{self.name}通知发送失败: {type(e).__name__}")
        return False


_PROVIDER_CLASSES = {
    "ServerChan": ServerChan,
    "Qmsg": Qmsg,
    "Bark": Bark,
    "Telegram": Telegram,
}


# 为了向后兼容，保留原来的Notification类
Notification = DefaultNotification
