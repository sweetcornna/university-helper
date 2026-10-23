from app.services.course.chaoxing.payload_mapper import normalize_tiku_config


def test_normalize_tiku_config_maps_frontend_fields():
    normalized = normalize_tiku_config(
        {
            "provider": "TikuYanxi",
            "token": "token-a,token-b",
            "coverage_threshold": 0.9,
            "judge_mapping": {"correct": ["对", "正确"], "wrong": ["错", "错误"]},
            "submit_mode": "submit",
        }
    )

    assert normalized["provider"] == "TikuYanxi"
    assert normalized["tokens"] == "token-a,token-b"
    assert normalized["cover_rate"] == 0.9
    assert normalized["true_list"] == "对,正确"
    assert normalized["false_list"] == "错,错误"
    assert normalized["submit"] == "true"


def test_normalize_tiku_config_disables_token_provider_without_token():
    normalized = normalize_tiku_config(
        {
            "provider": "TikuYanxi",
            "token": "",
            "coverage_threshold": 0.75,
            "submit_mode": "save",
        }
    )

    assert "provider" not in normalized
    assert "tokens" not in normalized
    assert normalized["cover_rate"] == 0.75
    assert normalized["submit"] == "false"


def test_normalize_tiku_config_drops_tokenless_provider_from_fallback_chain():
    # The web UI defaults to "TikuYanxi,TikuGo"; without a token the Yanxi link
    # used to log "初始化题库 言溪题库 失败 ... 'tokens'" on every task.
    normalized = normalize_tiku_config({"provider": "TikuYanxi,TikuGo", "token": ""})

    assert normalized["provider"] == "TikuGo"


def test_normalize_tiku_config_keeps_token_providers_when_token_given():
    normalized = normalize_tiku_config({"provider": "TikuYanxi,TikuGo", "token": "t1"})

    assert normalized["provider"] == "TikuYanxi,TikuGo"
    assert normalized["tokens"] == "t1"
