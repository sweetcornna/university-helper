# -*- coding: utf-8 -*-
"""Regression tests for provider-text -> Chaoxing option mapping."""

from app.services.course.chaoxing.answer_check import check_single
from app.services.course.chaoxing.quiz_service import _map_multiple_choice, _map_single_choice


def test_single_full_option_text_can_contain_chinese_comma():
    options = [
        "A. 电流越小，伤害越大",
        "B. 电流频率越高，伤害越大",
        "C. 交流电对人体没有危害",
        "D. 接触时间与伤害程度无关",
    ]
    answer = "电流频率越高，伤害越大"

    assert check_single(answer) is True
    assert _map_single_choice(answer, options) == "B"


def test_multiple_full_text_maps_each_option_once():
    options = [
        "A. 待灭菌的物品必须压得越紧越好",
        "B. 待灭菌的物品放置不宜过紧",
        "C. 灭菌过程中可以随时开盖",
        "D. 必须将冷空气充分排除，否则锅内温度达不到规定温度，影响灭菌效果",
    ]
    answer = "待灭菌的物品放置不宜过紧 必须将冷空气充分排除，否则锅内温度达不到规定温度，影响灭菌效果"

    assert _map_multiple_choice(answer, options) == "BD"


def test_multiple_direct_letters_are_deduplicated_in_option_order():
    options = ["A. one", "B. two", "C. three", "D. four"]

    assert _map_multiple_choice("D,B,B", options) == "BD"


def test_embedded_ascii_letters_in_prose_are_not_treated_as_choice_letters():
    options = [
        "A. BSL-3级实验室适用于所有基础教学",
        "B. BSL只是设备型号",
        "C. BSL-2级实验室与BSL-1级实验室相比，主要增加了安全防护要求",
        "D. BSL-1级实验室必须使用正压服",
    ]

    assert _map_single_choice(
        "BSL-2级实验室与BSL-1级实验室相比，主要增加了安全防护要求",
        options,
    ) == "C"


def test_overlapping_option_text_prefers_longest_non_overlapping_match():
    options = [
        "A. 安全装置",
        "B. 必须安装合理可靠的安全装置",
        "C. 可以拆除防护罩",
        "D. 无需安全装置",
    ]

    assert _map_multiple_choice("必须安装合理可靠的安全装置", options) == "B"


def test_ambiguous_or_unrelated_text_is_rejected():
    options = ["A. abc", "B. abc", "C. def"]

    assert _map_single_choice("abc", options) == ""
    assert _map_multiple_choice("unrelated", options) == ""
