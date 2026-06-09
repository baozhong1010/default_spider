from spider.config.models import ClassificationConfig


def classify_bid_type(title, content, cfg):
    # type: (str, str, ClassificationConfig) -> str
    merged = "%s\n%s" % (title, content)
    for keyword in cfg.zhongbiao_keywords:
        if keyword and keyword in merged:
            return "zhongbiao"
    return cfg.default_type
