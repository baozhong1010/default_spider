import html as html_lib
import re
from dataclasses import dataclass, field
from typing import List, Set

from lxml import etree
from readability import Document

from spider.config.models import AttachmentConfig, DetailExtractionConfig
from spider.extract.selector_engine import apply_selector, first_non_empty, html_tree
from spider.utils.helpers import normalize_space, resolve_url


@dataclass
class DetailExtractResult:
    content: str
    attachment_urls: List[str] = field(default_factory=list)
    attachment_names: List[str] = field(default_factory=list)
    title: str = ""
    date: str = ""


class DetailExtractor(object):
    def __init__(self, detail_cfg, attachment_cfg):
        # type: (DetailExtractionConfig, AttachmentConfig) -> None
        self.detail_cfg = detail_cfg
        self.attachment_cfg = attachment_cfg

    def extract(self, raw_text, base_url):
        # type: (str, str) -> DetailExtractResult
        content_html = self._resolve_content_html(raw_text)
        tree = html_tree(content_html)
        if tree is None:
            return DetailExtractResult(content="", attachment_urls=[])

        # 标题/日期选择器针对**原始响应**取（响应是 JSON 时才能用 jsonpath 命中字段），
        # 正文选择器针对预处理后的 content_html 取。
        meta_tree = tree
        if self.detail_cfg.response_html_selectors:
            candidate = html_tree(raw_text)
            if candidate is not None:
                meta_tree = candidate
        detail_title = self._extract_title_by_rules(meta_tree, raw_text)
        detail_date = self._extract_date_by_rules(meta_tree, raw_text)
        content = self._extract_content_by_rules(tree, content_html)
        if (not self.to_plain_text(content) or len(self.to_plain_text(content)) < self.detail_cfg.min_content_length) and self.detail_cfg.fallback_auto:
            content = self._extract_content_by_auto(tree)
        if (not self.to_plain_text(content) or len(self.to_plain_text(content)) < self.detail_cfg.min_content_length) and self.detail_cfg.fallback_readability:
            content = self._extract_with_readability(content_html)

        content = content.strip()
        attachment_urls, attachment_names = self._extract_attachments(tree, raw_text, base_url)
        return DetailExtractResult(
            content=content,
            attachment_urls=attachment_urls,
            attachment_names=attachment_names,
            title=detail_title,
            date=detail_date,
        )

    def _resolve_content_html(self, raw_text):
        # type: (str) -> str
        if not self.detail_cfg.response_html_selectors:
            return raw_text

        root = html_tree(raw_text)
        for selector in self.detail_cfg.response_html_selectors:
            values = apply_selector(selector=selector, context=root, html_text=raw_text, as_nodes=True)
            if not values:
                continue
            first = values[0]
            if isinstance(first, str):
                return first
            if isinstance(first, etree._Element):
                return etree.tostring(first, encoding="unicode", method="html")
            return str(first)
        return raw_text

    @staticmethod
    def to_plain_text(content):
        # type: (str) -> str
        tree = html_tree(content)
        if tree is None:
            return normalize_space(content)
        return normalize_space("".join(tree.xpath("//text()")))

    @staticmethod
    def _strip_noise_nodes(node):
        # type: (etree._Element) -> None
        # 剥离 script/style/注释等非正文节点（如详情页把公告元信息写进 <script> 的情况）
        try:
            for bad in node.xpath(".//script | .//style | .//comment()"):
                parent = bad.getparent()
                if parent is not None:
                    parent.remove(bad)
        except Exception:
            pass

    def _extract_title_by_rules(self, tree, html_text):
        # type: (etree._Element, str) -> str
        for selector in self.detail_cfg.title_selectors:
            values = apply_selector(selector=selector, context=tree, html_text=html_text)
            title = first_non_empty(values)
            if title:
                return title
        return ""

    def _extract_date_by_rules(self, tree, html_text):
        # type: (etree._Element, str) -> str
        for selector in self.detail_cfg.date_selectors:
            values = apply_selector(selector=selector, context=tree, html_text=html_text)
            date_value = first_non_empty(values)
            if date_value:
                return date_value
        return ""

    def _extract_content_by_rules(self, tree, html_text):
        # type: (etree._Element, str) -> str
        for selector in self.detail_cfg.content_selectors:
            nodes = apply_selector(selector=selector, context=tree, html_text=html_text, as_nodes=True)
            if nodes:
                node = nodes[0]
                if isinstance(node, etree._Element):
                    self._strip_noise_nodes(node)
                    return etree.tostring(node, encoding="unicode", method="html")
            values = apply_selector(selector=selector, context=tree, html_text=html_text)
            if values:
                raw = first_non_empty(values)
                if "<" in raw and ">" in raw:
                    return raw
                return "<div>%s</div>" % html_lib.escape(raw)
        return ""

    def _extract_content_by_auto(self, tree):
        # type: (etree._Element) -> str
        candidates = tree.xpath("//article|//div|//section|//td")
        best_html = ""
        best_score = -1
        for node in candidates:
            text = normalize_space("".join(node.xpath(".//text()")))
            if len(text) < self.detail_cfg.min_content_length:
                continue
            score = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))
            score += 20 * len(node.xpath(".//p"))
            if score > best_score:
                best_score = score
                self._strip_noise_nodes(node)
                best_html = etree.tostring(node, encoding="unicode", method="html")
        return best_html

    @staticmethod
    def _extract_with_readability(html_text):
        # type: (str) -> str
        try:
            return Document(html_text).summary()
        except Exception:
            return ""

    def _extract_attachments(self, tree, html_text, base_url):
        # type: (etree._Element, str, str) -> tuple
        if not self.attachment_cfg.enabled:
            return [], []

        urls = []  # type: List[str]
        if self.attachment_cfg.selectors:
            for selector in self.attachment_cfg.selectors:
                values = apply_selector(selector=selector, context=tree, html_text=html_text)
                urls.extend(values)
        else:
            urls.extend(tree.xpath("//a/@href"))
            urls.extend(tree.xpath("//iframe/@src"))
            urls.extend(tree.xpath("//embed/@src"))

        names = []  # type: List[str]
        for selector in self.attachment_cfg.filename_selectors:
            values = apply_selector(selector=selector, context=tree, html_text=html_text)
            names.extend(values)

        output = []  # type: List[str]
        output_names = []  # type: List[str]
        seen = set()  # type: Set[str]
        for i, raw in enumerate(urls):
            if not raw:
                continue
            normalized_raw = normalize_space(str(raw)).replace("\\/", "/")
            if self.attachment_cfg.url_template:
                url = self.attachment_cfg.url_template.replace("{value}", normalized_raw)
            else:
                url = resolve_url(base_url, normalized_raw)
            lower = url.lower()
            if lower.startswith("javascript"):
                continue
            if self.attachment_cfg.allowed_extensions and not any(
                lower.endswith(ext.lower()) for ext in self.attachment_cfg.allowed_extensions
            ):
                continue
            if url in seen:
                continue
            seen.add(url)
            output.append(url)
            output_names.append(normalize_space(names[i]) if i < len(names) else "")
        return output, output_names
