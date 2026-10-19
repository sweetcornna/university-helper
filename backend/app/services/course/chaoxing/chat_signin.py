"""Group-chat sign-in, independent of course/class discovery.

Sign protocol: cxOrz/chaoxing-signin@946df7ce94a749450894dcf243bca4eaec891db0,
functions/activity.ts preSign2, functions/general.ts GeneralSign_2 and
functions/location.ts LocationSign_2.
Latest JSON messages: yf-hao/xuexitong@3fa4111887d8452694830ef14f77615b4b048d9e,
core/apis/chat_api.py. No history/protobuf decoding, read receipts, or messages sent.
"""

import html
import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .signin import ChaoxingSigninClient, SigninSessionExpiredError

LOGIN_USER_URL = "https://im.chaoxing.com/apis/getLoginUser"
IM_TOKEN_URL = "https://learn.chaoxing.com/apis/user/getUserImToken"
IM_CHANNELS_BASE_URL = "https://a3-vip6.easemob.com/cx-dev/cxstudy/sdk/user"
CHAT_PRE_SIGN_URL = "https://mobilelearn.chaoxing.com/sign/preStuSign"
CHAT_SIGN_URL = "https://mobilelearn.chaoxing.com/sign/stuSignajax"
IM_HEADERS = {"Origin": "https://fe.chaoxing.com", "Referer": "https://fe.chaoxing.com/"}
DISCOVERY_SCOPE_MESSAGE = "仅检查群聊最新一条 JSON 消息；较早签到请填写活动链接或群聊及活动 ID。"
MAX_JSON_MESSAGE_LENGTH = 1024 * 1024
SUPPORTED_CHAT_SIGN_TYPES = ("normal", "location")
LOCATION_REQUIRED_MESSAGE = "这是位置签到，请先设置签到位置（地图选点或使用当前位置）后再提交。"
# The location preStuSign page never says 「位置签到」; it carries the location
# consent checkbox, the address field and the location widget script instead.
_LOCATION_PAGE_MARKERS = re.compile(
    r"""(?:id|name)=["'](?:ifTiJiao|paramAddress)["']|client-user-location-address\.js|class=["']zgetSite""",
    re.IGNORECASE,
)


def _numeric_id(value: Any, name: str, *, required: bool = True) -> str:
    if value is None or value == "":
        if not required:
            return ""
        raise ValueError(f"{name} is required")
    result = str(value).strip()
    if not re.fullmatch(r"[1-9][0-9]{0,31}", result):
        raise ValueError(f"{name} must be a positive numeric ID (at most 32 digits)")
    return result


def parse_chat_target(chat_id: Any = None, active_id: Any = None, activity_url: str | None = None) -> tuple[str, str]:
    """Extract ids only; user-supplied URLs are never requested."""
    normalized_chat = _numeric_id(chat_id, "chat_id", required=False)
    normalized_active = _numeric_id(active_id, "active_id", required=False)
    if activity_url:
        if not isinstance(activity_url, str) or len(activity_url) > 4096:
            raise ValueError("activity_url must be a Chaoxing sign-in link of at most 4096 characters")
        parsed = urlparse(html.unescape(activity_url.strip()))
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname != "mobilelearn.chaoxing.com"
            or parsed.netloc != "mobilelearn.chaoxing.com"
            or "sign" not in parsed.path.lower()
        ):
            raise ValueError("activity_url must be a mobilelearn.chaoxing.com sign-in link")
        query = parse_qs(parsed.query)

        def link_id(keys: tuple[str, ...], name: str) -> str:
            values = [value for key in keys for value in query.get(key, [])]
            if len(set(values)) > 1:
                raise ValueError(f"activity_url contains conflicting {name} values")
            return _numeric_id(values[0], name) if values else ""

        linked_chat = link_id(("chatId", "chatid"), "chat_id")
        linked_active = link_id(("activeId", "activePrimaryId", "aid"), "active_id")
        if normalized_chat and linked_chat and normalized_chat != linked_chat:
            raise ValueError("chat_id does not match activity_url")
        if normalized_active and linked_active and normalized_active != linked_active:
            raise ValueError("active_id does not match activity_url")
        normalized_chat = normalized_chat or linked_chat
        normalized_active = normalized_active or linked_active
    return _numeric_id(normalized_chat, "chat_id"), _numeric_id(normalized_active, "active_id")


def _object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and len(value) <= MAX_JSON_MESSAGE_LENGTH:
        try:
            decoded = json.loads(value)
        except ValueError:
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def _sign_type(card: dict[str, Any]) -> str:
    name = str(card.get("atypeName") or "")
    for keyword, sign_type in (
        ("拍照", "photo"),
        ("位置", "location"),
        ("定位", "location"),
        ("二维码", "qrcode"),
        ("手势", "gesture"),
        ("密码", "code"),
        ("签到码", "code"),
        ("人脸", "face"),
    ):
        if keyword in name:
            return sign_type
    if str(card.get("ifphoto")) == "1":
        return "photo"
    if "otherId" in card:
        return {"0": "normal", "2": "qrcode", "3": "gesture", "4": "location", "5": "code"}.get(
            str(card["otherId"]), "unknown"
        )
    return "normal" if name in ("签到", "普通签到", "一般签到") else "unknown"


class ChaoxingChatSigninService:
    def __init__(self, client: ChaoxingSigninClient):
        self.client = client
        self.session = client.session

    def _credentials(self) -> dict[str, str]:
        user_response = self.session.get(
            LOGIN_USER_URL, params={"crossOrigin": "true", "detail": "1"}, headers=IM_HEADERS, timeout=12
        )
        user_payload = self.client._read_json_response(user_response, "群聊登录信息")
        user = self._data(user_payload)
        puid = str(user.get("puid") or "")
        if not puid:
            raise requests.RequestException("群聊登录信息缺少 puid，无法确认当前账号")
        if not self.client.uid or puid != str(self.client.uid):
            raise SigninSessionExpiredError("群聊登录账号与学习通账号不一致，请重新登录")
        token_response = self.session.get(IM_TOKEN_URL, params={"crossOrigin": "true"}, headers=IM_HEADERS, timeout=12)
        token_payload = self.client._read_json_response(token_response, "群聊登录凭证")
        token_data = self._data(token_payload)
        token = self._first(token_data, ("hxToken", "token", "imToken", "userImToken", "access_token"))
        tuid = self._first(token_data, ("uid", "tuid", "imTuid", "username", "userName"))
        if not token or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", tuid):
            raise requests.RequestException("群聊登录凭证缺少有效 token 或 tuid，请重新登录后重试")
        if "\r" in token or "\n" in token or len(token) > 16384 or tuid in (".", ".."):
            raise requests.RequestException("群聊登录凭证格式异常")
        token = token.removeprefix("Bearer ").strip()
        if not token:
            raise requests.RequestException("群聊登录凭证为空")
        return {"puid": puid, "tuid": tuid, "token": token}

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("data", "msg"):
            if isinstance(payload.get(key), dict):
                return payload[key]
        return payload

    @staticmethod
    def _first(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
        return ""

    def get_tasks(self, chat_id: str | None = None) -> dict[str, Any]:
        selected_chat = _numeric_id(chat_id, "chat_id", required=False)
        credentials = self._credentials()
        response = self.session.get(
            f"{IM_CHANNELS_BASE_URL}/{credentials['tuid']}/user_channels/list",
            params={
                "limit": 50,
                "cursor": "",
                "need_mark": "true",
                "needEmptySession": "true",
                "_v": int(time.time() * 1000),
            },
            headers={**IM_HEADERS, "Authorization": f"Bearer {credentials['token']}"},
            timeout=12,
        )
        payload = self.client._read_json_response(response, "群聊会话列表")
        envelope = payload.get("data")
        if isinstance(envelope, dict):
            channels = envelope.get("channel_infos")
            if channels is None:
                channels = envelope.get("channels")
        else:
            channels = envelope if isinstance(envelope, list) else payload.get("channels")
        if not isinstance(channels, list) or any(not isinstance(channel, dict) for channel in channels):
            raise requests.RequestException("群聊会话列表缺少有效 channels，无法检测群聊签到")

        warnings = [DISCOVERY_SCOPE_MESSAGE]
        if (isinstance(envelope, dict) and envelope.get("cursor")) or payload.get("cursor") or len(channels) >= 50:
            warnings.append("仅检查最近 50 个会话，更多群聊请直接填写活动链接或 ID。")
        tasks = []
        seen = set()
        for channel in channels[:50]:
            channel_id = str(channel.get("channel_id") or "")
            if channel.get("session_type") != "groupchat" and "@conference." not in channel_id:
                continue
            raw_chat_id = channel.get("session_to") or channel_id.split("@", 1)[0]
            try:
                current_chat = _numeric_id(raw_chat_id, "chat_id")
            except ValueError:
                warnings.append("有群聊未提供有效群 ID，无法检测其最新签到。")
                continue
            if selected_chat and selected_chat != current_chat:
                continue
            meta = _object(channel.get("meta"))
            raw_message = meta.get("payload") if meta else None
            if raw_message is None:
                if channel.get("meta") not in (None, {}, ""):
                    warnings.append(f"群聊 {current_chat} 的最新消息无可解析 JSON 附件；请填写活动链接或 ID。")
                continue
            message = _object(raw_message)
            if message is None:
                warnings.append(
                    f"群聊 {current_chat} 的最新消息不是 JSON；暂不支持 Base64/protobuf，请填写活动链接或 ID。"
                )
                continue
            ext = _object(message.get("ext"))
            if ext is None:
                if message.get("ext") not in (None, {}, ""):
                    warnings.append(f"群聊 {current_chat} 的消息扩展不是可解析 JSON；请填写活动链接或 ID。")
                continue
            attachment = _object(ext.get("attachment"))
            if attachment is None:
                if ext.get("attachment") not in (None, {}, ""):
                    warnings.append(f"群聊 {current_chat} 的消息附件不是可解析 JSON；请填写活动链接或 ID。")
                continue
            card = _object(attachment.get("att_chat_course"))
            if not card:
                if attachment.get("att_chat_course") not in (None, {}, ""):
                    warnings.append(f"群聊 {current_chat} 的签到卡片不是可解析 JSON；请填写活动链接或 ID。")
                continue
            if str(card.get("atype")) not in ("2", "74") and "sign" not in str(card.get("url") or "").lower():
                continue
            course_info = _object(card.get("courseInfo")) or {}
            if course_info.get("courseid") not in (None, "", "0", 0, "null"):
                continue
            try:
                active_id = _numeric_id(card.get("aid") or card.get("activeId"), "active_id")
                attached_chat = _numeric_id(attachment.get("chatid") or card.get("chatId"), "chat_id", required=False)
            except ValueError:
                warnings.append(f"群聊 {current_chat} 的签到卡片缺少有效活动 ID。")
                continue
            if attached_chat and attached_chat != current_chat:
                warnings.append(f"群聊 {current_chat} 的卡片群 ID 不一致，未加入签到列表。")
                continue
            key = (current_chat, active_id)
            if key in seen:
                continue
            seen.add(key)
            sign_type = _sign_type(card)
            task = self._task(current_chat, active_id, sign_type)
            task.update(
                name=str(card.get("title") or "群聊签到"),
                chatName=str(channel.get("name") or channel.get("chatName") or task["chatName"]),
                startTime=meta.get("timestamp"),
            )
            if sign_type not in SUPPORTED_CHAT_SIGN_TYPES:
                task["unsupportedReason"] = "群聊目前支持普通签到和位置签到，请在学习通 App 完成此类型。"
            tasks.append(task)
        return {"tasks": tasks, "warnings": list(dict.fromkeys(warnings)), "scope": "latest_messages"}

    @staticmethod
    def _task(chat_id: str, active_id: str, sign_type: str = "unknown") -> dict[str, Any]:
        return {
            "taskId": f"chat:{chat_id}:{active_id}",
            "subjectType": "chat",
            "subjectId": chat_id,
            "chatId": chat_id,
            "chatName": f"群聊 {chat_id}",
            "activeId": active_id,
            "name": "群聊签到",
            "type": sign_type,
            "status": "unknown",
            "actionable": sign_type in SUPPORTED_CHAT_SIGN_TYPES,
            "source": "chat",
        }

    @staticmethod
    def _inspect_pre_sign(content: str) -> tuple[str | None, str]:
        """Return the sign type this page accepts (normal/location), or None with the reason."""
        soup = BeautifulSoup(content, "lxml")
        text = soup.get_text(" ", strip=True)
        if re.search(r"已结束|已删除|不存在|未开始|无权限|不在.{0,8}群|已经签到|您已签到|你已签到", text):
            return None, text[:240]
        fields = {
            str(node.get("name") or node.get("id") or ""): str(node.get("value") or "")
            for node in soup.select("input[name], input[id]")
        }
        sign_type = _sign_type(
            {"otherId": fields["otherId"], "ifphoto": fields.get("ifphoto")} if "otherId" in fields else {}
        )
        if fields.get("ifphoto") == "1":
            sign_type = "photo"
        if sign_type == "unknown" and (_LOCATION_PAGE_MARKERS.search(content) or re.search(r"位置签到|定位签到", text)):
            sign_type = "location"
        if sign_type == "location":
            return "location", ""
        if (
            ("otherId" in fields and sign_type != "normal")
            or sign_type not in ("unknown", "normal")
            or re.search(r"拍照|二维码|手势|签到码|密码签到|人脸", text)
        ):
            return (
                None,
                "群聊目前支持普通签到和位置签到；此活动需要照片、二维码、手势、签到码或其他验证，请在学习通 App 完成。",
            )
        normal_form = "签到" in text and "stuSignajax" in content
        if sign_type == "normal" or normal_form:
            return "normal", ""
        return None, "无法确认此群聊活动的签到类型，请在学习通 App 核对活动类型。"

    @staticmethod
    def _location_form(location: dict[str, Any] | None) -> dict[str, str] | None:
        """Coordinates the user chose, or None when no usable location was given."""
        location = location or {}
        try:
            latitude = float(location.get("latitude"))
            longitude = float(location.get("longitude"))
        except (TypeError, ValueError):
            return None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or (latitude, longitude) in ((-1, -1), (0, 0)):
            return None
        return {
            "address": str(location.get("address") or "").strip(),
            "latitude": str(latitude),
            "longitude": str(longitude),
        }

    def sign_once(
        self,
        chat_id: Any = None,
        active_id: Any = None,
        activity_url: str | None = None,
        location: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chat_id, active_id = parse_chat_target(chat_id, active_id, activity_url)
        credentials = self._credentials()
        response = self.session.get(
            CHAT_PRE_SIGN_URL,
            params={
                "activeId": active_id,
                "code": "",
                "uid": credentials["puid"],
                "courseId": "null",
                "classId": 0,
                "general": 0,
                "chatId": chat_id,
                "appType": 0,
                "tid": credentials["tuid"],
                "atype": "null",
                "sys": 0,
            },
            timeout=12,
        )
        self.client._validate_response(response, "群聊签到预处理")
        content = response.text or ""
        if not content.strip() or "<" not in content:
            raise requests.RequestException("群聊签到预处理返回了无法解析的页面")
        text = BeautifulSoup(content, "lxml").get_text(" ", strip=True)
        if re.search(r"(?:访问|请求|操作).{0,12}频繁|稍后重试|访问受限|系统繁忙", text):
            raise requests.RequestException("群聊签到预处理请求受限，请稍后重试")
        sign_type, message = self._inspect_pre_sign(content)
        task = self._task(chat_id, active_id, sign_type or "unknown")
        if sign_type is None:
            return {"status": False, "message": message, "data": {"task": task}}
        if sign_type == "location":
            form = self._location_form(location)
            if form is None:
                # The platform accepts a location sign-in without coordinates and the
                # teacher then sees 「未获取到位置」; never submit one like that.
                return {
                    "status": False,
                    "message": LOCATION_REQUIRED_MESSAGE,
                    "data": {"task": task, "requiresLocation": True},
                }
            submit = self.session.post(
                CHAT_SIGN_URL,
                data={
                    **form,
                    "activeId": active_id,
                    "uid": credentials["puid"],
                    "clientip": "",
                    "useragent": "",
                    "fid": "",
                    "ifTiJiao": 1,
                },
                timeout=12,
            )
        else:
            submit = self.session.get(
                CHAT_SIGN_URL,
                params={"activeId": active_id, "uid": credentials["puid"], "clientip": ""},
                timeout=12,
            )
        self.client._validate_response(submit, "群聊签到提交")
        result = (submit.text or "").strip()
        if not result or "<" in result or result.startswith(("{", "[")):
            raise requests.RequestException("群聊签到提交返回了无法识别的结果，请在学习通 App 核对签到状态")
        return {"status": result == "success", "message": result[:240], "data": {"task": task}}
