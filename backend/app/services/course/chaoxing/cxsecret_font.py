##
# @Author: SocialSisterYi
# @Edit: Samueli924
# @Reference: https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy
#

import base64
import hashlib
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import IO

from fontTools.ttLib.tables._g_l_y_f import Glyph, table__g_l_y_f
from fontTools.ttLib.ttFont import TTFont

from api.exceptions import FontDecodeError
from api.logger import logger

# 康熙部首替换表
KX_RADICALS_TAB = str.maketrans(
    # 康熙部首
    "⼀⼁⼂⼃⼄⼅⼆⼇⼈⼉⼊⼋⼌⼍⼎⼏⼐⼑⼒⼓⼔⼕⼖⼗⼘⼙⼚⼛⼜⼝⼞⼟⼠⼡⼢⼣⼤⼥⼦⼧⼨⼩⼪⼫⼬⼭⼮⼯⼰⼱⼲⼳⼴⼵⼶⼷⼸⼹⼺⼻⼼⼽⼾⼿⽀⽁⽂⽃⽄⽅⽆⽇⽈⽉⽊⽋⽌⽍⽎⽏⽐⽑⽒⽓⽔⽕⽖⽗⽘⽙⽚⽛⽜⽝⽞⽟⽠⽡⽢⽣⽤⽥⽦⽧⽨⽩⽪⽫⽬⽭⽮⽯⽰⽱⽲⽳⽴⽵⽶⽷⽸⽹⽺⽻⽼⽽⽾⽿⾀⾁⾂⾃⾄⾅⾆⾇⾈⾉⾊⾋⾌⾍⾎⾏⾐⾑⾒⾓⾔⾕⾖⾗⾘⾙⾚⾛⾜⾝⾞⾟⾠⾡⾢⾣⾤⾥⾦⾧⾨⾩⾪⾫⾬⾭⾮⾯⾰⾱⾲⾳⾴⾵⾶⾷⾸⾹⾺⾻⾼髙⾽⾾⾿⿀⿁⿂⿃⿄⿅⿆⿇⿈⿉⿊⿋⿌⿍⿎⿏⿐⿑⿒⿓⿔⿕⺠⻬⻩⻢⻜⻅⺟⻓",
    # 对应汉字
    "一丨丶丿乙亅二亠人儿入八冂冖冫几凵刀力勹匕匚匸十卜卩厂厶又口囗土士夂夊夕大女子宀寸小尢尸屮山巛工己巾干幺广廴廾弋弓彐彡彳心戈戶手支攴文斗斤方无日曰月木欠止歹殳毋比毛氏气水火爪父爻爿片牙牛犬玄玉瓜瓦甘生用田疋疒癶白皮皿目矛矢石示禸禾穴立竹米糸缶网羊羽老而耒耳聿肉臣自至臼舌舛舟艮色艸虍虫血行衣襾見角言谷豆豕豸貝赤走足身車辛辰辵邑酉采里金長門阜隶隹雨青非面革韋韭音頁風飛食首香馬骨高高髟鬥鬯鬲鬼魚鳥鹵鹿麥麻黃黍黑黹黽鼎鼓鼠鼻齊齒龍龜龠民齐黄马飞见母长",
)


def resource_path(relative_path: str) -> str:
    """
    获取资源文件的路径，兼容PyInstaller打包后的环境。

    解析顺序（返回第一个真实存在的候选，否则回退到稳定的 backend 根目录候选）：
      1. PyInstaller 临时目录 (sys._MEIPASS)
      2. backend 根目录（由本文件位置推导，与进程 CWD 无关）—— 生产环境
         uvicorn 的 CWD 不一定是 backend，旧实现用 os.path.abspath(".")
         会解析到错误目录导致即便已放置 resource/ 也找不到。(audit F14)
      3. 进程当前工作目录

    Args:
        relative_path: 相对路径

    Returns:
        资源文件的绝对路径
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, relative_path))
    # .../backend/app/services/course/chaoxing/cxsecret_font.py -> parents[4] == backend
    backend_root = Path(__file__).resolve().parents[4]
    backend_candidate = str(backend_root / relative_path)
    candidates.append(backend_candidate)
    candidates.append(os.path.join(os.path.abspath("."), relative_path))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    # Stable fallback independent of CWD so a shipped file is found even if cwd
    # differs; if it is genuinely absent the caller degrades gracefully.
    return backend_candidate


class FontHashDAO:
    """
    字体哈希数据访问对象，负责管理字体哈希映射表
    """

    def __init__(self, file_path: str = "resource/font_map_table.json"):
        """
        初始化字体哈希数据访问对象

        Args:
            file_path: 字体映射表JSON文件路径，相对于资源目录

        Raises:
            FileNotFoundError: 当字体映射表文件不存在时
            json.JSONDecodeError: 当字体映射表JSON格式错误时
        """
        self.char_map: dict[str, str] = {}  # unicode -> hash
        self.hash_map: dict[str, str] = {}  # hash -> unicode

        full_path = resource_path(file_path)
        try:
            with open(full_path, encoding="utf-8") as fp:
                self.char_map = json.load(fp)
                self.hash_map = {hash_val: char for char, hash_val in self.char_map.items()}
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise FontDecodeError(f"加载字体映射表失败: {full_path} - {e}") from e

    def find_char(self, font_hash: str) -> str | None:
        """
        通过字体哈希值查找对应的Unicode字符编码

        Args:
            font_hash: 字体哈希值

        Returns:
            对应的Unicode字符编码，如果未找到则返回None
        """
        return self.hash_map.get(font_hash)

    def find_hash(self, char: str) -> str | None:
        """
        通过Unicode字符编码查找对应的字体哈希值

        Args:
            char: Unicode字符编码 (如 "uni4E00")

        Returns:
            对应的字体哈希值，如果未找到则返回None
        """
        return self.char_map.get(char)


# 初始化字体哈希DAO单例
#
# NOTE (audit F14): the data file resource/font_map_table.json (the font-hash ->
# original-character mapping table) is NOT shipped in this repository and is not
# generated/downloaded at build or startup. When it is absent, FontHashDAO falls
# back to EMPTY char_map/hash_map below, which means decrypt() cannot reverse
# Chaoxing's encrypted (anti-scrape) fonts and instead passes the garbled
# characters through unchanged. This is a documented, known limitation rather
# than a crash: encrypted-font question stems will appear garbled.
#
# To enable encrypted-font decoding, place a valid font_map_table.json under a
# "resource/" directory resolvable from the process CWD (see resource_path()).
try:
    fonthash_dao = FontHashDAO()
except Exception as e:
    logger.warning(
        "初始化字体哈希数据失败，加密字体解码功能将退化为原样返回 " f"(缺少 resource/font_map_table.json) - {e}"
    )
    fonthash_dao = FontHashDAO.__new__(FontHashDAO)
    fonthash_dao.char_map = {}
    fonthash_dao.hash_map = {}


def hash_glyph(glyph: Glyph) -> str:
    """
    计算TTF字体字形的哈希值

    Args:
        glyph: TTF字体字形对象

    Returns:
        字形的MD5哈希值
    """
    if glyph.numberOfContours <= 0:
        return ""

    pos_data = []
    last_index = 0

    for i in range(glyph.numberOfContours):
        end_point = glyph.endPtsOfContours[i]
        for j in range(last_index, end_point + 1):
            x, y = glyph.coordinates[j]
            flag = glyph.flags[j] & 0x01
            pos_data.append(f"{x}{y}{flag}")
        last_index = end_point + 1

    pos_bin = "".join(pos_data)
    return hashlib.md5(pos_bin.encode()).hexdigest()


def font2map(font_data: IO | Path | str) -> dict[str, str]:
    """
    从字体文件或Base64编码的字体数据中提取字形哈希映射表

    Args:
        font_data: 字体文件路径、文件对象或Base64编码的字体数据

    Returns:
        字形名称到哈希值的映射字典 ({"uni4E00": "hash值", ...})

    Raises:
        ValueError: 当无法解析字体数据时
    """
    font_hashmap = {}

    # 处理Base64编码的字体数据
    if isinstance(font_data, str) and font_data.startswith("data:application/font-ttf;charset=utf-8;base64,"):
        try:
            font_data = BytesIO(base64.b64decode(font_data[47:]))
        except Exception as e:
            raise FontDecodeError(f"无法解码Base64字体数据: {e}") from e

    try:
        with TTFont(font_data, lazy=False) as font_file:
            table: table__g_l_y_f = font_file["glyf"]
            for name in table.glyphOrder:
                if name.startswith("uni"):
                    glyph_hash = hash_glyph(table.glyphs[name])
                    if glyph_hash:
                        font_hashmap[name] = glyph_hash
    except Exception as e:
        raise FontDecodeError(f"无法解析字体文件: {e}") from e

    return font_hashmap


def decrypt(dst_fontmap: dict[str, str], encrypted_text: str) -> str:
    """
    解密超星学习通加密字体的文本

    Args:
        dst_fontmap: 目标字体的字形哈希映射表
        encrypted_text: 加密的文本

    Returns:
        解密后的文本
    """
    result = []

    for char in encrypted_text:
        # 构造Unicode字符名称 (如 "uni4E00")
        char_code = f"uni{ord(char):X}"

        # 查找字符在目标字体中的哈希值
        if char_code in dst_fontmap:
            dst_hash = dst_fontmap[char_code]
            # 通过哈希值找回原始字符
            original_char_code = fonthash_dao.find_char(dst_hash)
            if original_char_code:
                # 将Unicode编码转换为字符
                try:
                    original_char = chr(int(original_char_code[3:], 16))
                    result.append(original_char)
                    continue
                except (ValueError, IndexError):
                    pass

        # 如果无法解密，则保留原字符
        result.append(char)

    # 替换解密后的康熙部首
    decrypted_text = "".join(result).translate(KX_RADICALS_TAB)
    return decrypted_text
