from spider.config.models import AreaExtractionConfig


def detect_area(title, content, cfg):
    # type: (str, str, AreaExtractionConfig) -> str
    # fixed_value has highest priority; if configured, always use it.
    if cfg.fixed_value:
        return cfg.fixed_value.strip()

    if not cfg.enabled:
        return ""

    pools = [title, content] if cfg.use_title_first else [content, title]
    for text in pools:
        for province in cfg.province_keywords:
            if province in text:
                if province in {"北京", "天津", "上海", "重庆"}:
                    return province + "市"
                return province + "省"

    if "全国" in (title + content):
        return "全国"
    return ""
