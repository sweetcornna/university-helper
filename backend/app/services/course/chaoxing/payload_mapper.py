from typing import Any


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_csv_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(items)
    return str(value).strip()


def normalize_tiku_config(raw_config: Any) -> dict[str, Any]:
    if not isinstance(raw_config, dict):
        return {}

    config: dict[str, Any] = dict(raw_config)

    token_text = _as_csv_text(config.get("tokens") or config.get("token"))
    if token_text:
        config["tokens"] = token_text

    cover_rate = config.get("coverage_threshold", config.get("cover_rate"))
    if cover_rate not in (None, ""):
        config["cover_rate"] = _as_float(cover_rate, default=0.8, minimum=0.0, maximum=1.0)

    judge_mapping = config.get("judge_mapping")
    if isinstance(judge_mapping, dict):
        true_list = _as_csv_text(judge_mapping.get("correct"))
        false_list = _as_csv_text(judge_mapping.get("wrong"))
        if true_list:
            config["true_list"] = true_list
        if false_list:
            config["false_list"] = false_list

    if "submit_mode" in config:
        submit_mode = str(config.get("submit_mode") or "").strip().lower()
        if submit_mode:
            config["submit"] = "true" if submit_mode in {"submit", "auto", "direct"} else "false"

    provider = str(config.get("provider") or "").strip()
    token_required_providers = {"TikuYanxi", "TikuLike"}
    if provider in token_required_providers and not token_text:
        # Disable token-based tiku provider when no token is supplied.
        config.pop("provider", None)

    return config
