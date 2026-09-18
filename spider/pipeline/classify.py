from spider.config.models import ClassificationConfig


def classify_bid_type(title, content, cfg):
    # type: (str, str, ClassificationConfig) -> str
    if getattr(cfg, "title_only", False):
        # 只按标题判定：避开正文模板里的「未来时态」结果词（见 models.ClassificationConfig）
        merged = title or ""
    else:
        merged = "%s\n%s" % (title, content)
    for keyword in cfg.zhongbiao_keywords:
        if keyword and keyword in merged:
            return "zhongbiao"
    return cfg.default_type
