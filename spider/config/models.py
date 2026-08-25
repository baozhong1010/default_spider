from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from typing import Literal
except ImportError:  # pragma: no cover
    from typing_extensions import Literal

from pydantic import BaseModel, Field, root_validator

from .compat import model_dump, model_validate


class RedisConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 1
    password: Optional[str] = None
    decode_responses: bool = True


class RuntimeConfig(BaseModel):
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    timeout_seconds: float = 20
    retries: int = 2
    max_connections: int = 100
    failure_sample_dir: str = "./failure_samples"
    failure_queue_key: str = "zhaobiao:domian:fail"
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown_seconds: int = 900
    metrics_log_topn: int = 10
    log_level: str = "INFO"


class Selector(BaseModel):
    kind: Literal["xpath", "css", "regex", "jsonpath"] = "xpath"
    expr: str
    attr: Optional[str] = None


class RequestConfig(BaseModel):
    method: str = "GET"
    headers: Dict[str, str] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)
    data: Optional[Union[Dict[str, Any], str]] = None
    json_body: Optional[Union[Dict[str, Any], List[Any]]] = Field(default=None, alias="json")
    timeout_seconds: float = 20
    retries: int = 2
    retry_backoff_seconds: float = 0.6
    verify_ssl: bool = False

    class Config:
        allow_population_by_field_name = True


class PaginationConfig(BaseModel):
    mode: Literal["none", "page_param", "url_template", "json_template"] = "none"
    start_page: int = 1
    end_page: int = 1
    page_param: str = "page"
    url_template: Optional[str] = None
    json_template: Optional[str] = None

    @root_validator(skip_on_failure=True)
    def validate_pagination(cls, values):
        mode = values.get("mode")
        url_template = values.get("url_template")
        json_template = values.get("json_template")
        start_page = values.get("start_page")
        end_page = values.get("end_page")

        if mode == "url_template" and not url_template:
            raise ValueError("url_template is required when mode=url_template")
        if mode == "json_template" and not json_template:
            raise ValueError("json_template is required when mode=json_template")
        if end_page < start_page:
            raise ValueError("end_page must be >= start_page")
        return values


class CryptoConfig(BaseModel):
    enabled: bool = False
    module: str = "epoint"
    public_key: str = ""
    aes_key: str = ""
    aes_iv: str = ""
    token: str = "Epoint_WebSerivce_**##0601"
    sm2_mode: int = 0


class DetailRequestConfig(BaseModel):
    # 详情页请求方式。默认 GET；加密接口型站点可配置为 POST + body_template。
    method: str = "GET"
    # 详情接口地址；为空时回退到 entry_urls[0]。
    url: Optional[str] = None
    # 内层请求体模板，支持 {link}（列表项的详情链接，即 infoID）与 {title} 占位符。
    body_template: Optional[str] = None


class ScheduleConfig(BaseModel):
    enabled: bool = False
    interval_seconds: Optional[int] = None
    cron: Optional[str] = None
    jitter_seconds: Optional[int] = None

    @root_validator(skip_on_failure=True)
    def validate_schedule(cls, values):
        enabled = values.get("enabled")
        interval_seconds = values.get("interval_seconds")
        cron = values.get("cron")
        if enabled and not interval_seconds and not cron:
            raise ValueError("schedule requires interval_seconds or cron")
        return values


class SiteLimits(BaseModel):
    max_concurrency: int = 5
    request_interval_seconds: float = 0.0


class CookieConfig(BaseModel):
    enabled: bool = False
    redis_hash_key: Optional[str] = None
    redis_field: str = "default"
    header_name: str = "Cookie"

    @root_validator(skip_on_failure=True)
    def validate_cookie(cls, values):
        if values.get("enabled") and not values.get("redis_hash_key"):
            raise ValueError("cookie.redis_hash_key is required when cookie.enabled=true")
        return values


class DedupConfig(BaseModel):
    redis_hash_key: str = "zhaobiao:domian:linkqc"
    ttl_days: int = 30
    prune_probability: float = 0.01


class ListExtractionConfig(BaseModel):
    response_html_selectors: List[Selector] = Field(default_factory=list)
    item_selectors: List[Selector] = Field(default_factory=list)
    link_selectors: List[Selector] = Field(default_factory=list)
    title_selectors: List[Selector] = Field(default_factory=list)
    date_selectors: List[Selector] = Field(default_factory=list)
    detail_url_template: Optional[str] = None
    min_title_length: int = 8
    fallback_auto: bool = True


class DetailExtractionConfig(BaseModel):
    # 若详情响应是 JSON，且真正 HTML 正文在某个字段里，用这个先提取（例如 $.custom.custom.infoContent）
    response_html_selectors: List[Selector] = Field(default_factory=list)
    content_selectors: List[Selector] = Field(default_factory=list)
    fallback_auto: bool = True
    fallback_readability: bool = True
    min_content_length: int = 30


class AttachmentConfig(BaseModel):
    enabled: bool = True
    selectors: List[Selector] = Field(default_factory=list)
    # 附件文件名提取规则（与 selectors 按位置对齐）；为空时回退到 URL 路径 basename
    filename_selectors: List[Selector] = Field(default_factory=list)
    allowed_extensions: List[str] = Field(
        default_factory=lambda: [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".txt"]
    )
    max_bytes: int = 50 * 1024 * 1024


class ClassificationConfig(BaseModel):
    default_type: Literal["zhaobiao", "zhongbiao"] = "zhaobiao"
    zhongbiao_keywords: List[str] = Field(
        default_factory=lambda: ["中标", "成交", "结果", "合同", "废标", "终止", "候选人"]
    )


class AreaExtractionConfig(BaseModel):
    enabled: bool = True
    use_title_first: bool = True
    fixed_value: Optional[str] = None
    province_keywords: List[str] = Field(
        default_factory=lambda: [
            "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江",
            "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州",
            "云南", "陕西", "甘肃", "青海", "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门", "台湾",
        ]
    )


class OutputConfig(BaseModel):
    enabled: bool = True
    queue_zhaobiao: str = "zhaobiao:result:zhaobiao"
    queue_zhongbiao: str = "zhaobiao:result:zhongbiao"
    attachment_dir_zhaobiao: str = "/root/pachong/zhaobiao/data/附件"
    attachment_dir_zhongbiao: str = "/root/pachong/zhaobiao/data_zb/附件"


class SiteConfig(BaseModel):
    id: str
    enabled: bool = True
    name: str = ""
    entry_urls: List[str] = Field(default_factory=list)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    limits: SiteLimits = Field(default_factory=SiteLimits)
    request: RequestConfig = Field(default_factory=RequestConfig)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    crypto: CryptoConfig = Field(default_factory=CryptoConfig)
    detail_request: DetailRequestConfig = Field(default_factory=DetailRequestConfig)
    cookie: CookieConfig = Field(default_factory=CookieConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    list_extraction: ListExtractionConfig = Field(default_factory=ListExtractionConfig)
    detail_extraction: DetailExtractionConfig = Field(default_factory=DetailExtractionConfig)
    attachments: AttachmentConfig = Field(default_factory=AttachmentConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    area_extraction: AreaExtractionConfig = Field(default_factory=AreaExtractionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @root_validator(skip_on_failure=True)
    def validate_site(cls, values):
        if not values.get("entry_urls"):
            raise ValueError("entry_urls is required")
        return values


class DefaultsConfig(BaseModel):
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)


class AppConfig(BaseModel):
    root_dir: Path
    redis: RedisConfig
    runtime: RuntimeConfig
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    sites: List[SiteConfig]

    def site_map(self) -> Dict[str, SiteConfig]:
        return {site.id: site for site in self.sites}


def apply_defaults(site: SiteConfig, defaults: DefaultsConfig) -> SiteConfig:
    site_data = model_dump(site)

    def _merge(default_obj: BaseModel, target_key: str) -> None:
        default_data = model_dump(default_obj)
        site_data[target_key] = dict(default_data, **site_data.get(target_key, {}))

    _merge(defaults.dedup, "dedup")
    _merge(defaults.output, "output")
    _merge(defaults.classification, "classification")
    return model_validate(SiteConfig, site_data)



