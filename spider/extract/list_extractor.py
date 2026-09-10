import re
from dataclasses import dataclass
from typing import Any, Dict, List

from lxml import etree

from spider.config.models import ListExtractionConfig
from spider.extract.selector_engine import apply_selector, first_non_empty, html_tree
from spider.utils.helpers import normalize_space, resolve_url


@dataclass
class ListItem:
    title: str
    url: str
    date: str
    source_url: str = ""
    raw_url: str = ""
    area: str = ""


class ListExtractor(object):
    def __init__(self, cfg):
        # type: (ListExtractionConfig) -> None
        self.cfg = cfg

    def extract(self, raw_response_text, base_url):
        # type: (str, str) -> List[ListItem]
        list_html = self._resolve_list_html(raw_response_text)
        tree = html_tree(list_html)
        if tree is None:
            return []

        items = self._extract_by_rules(tree, list_html, base_url)
        if not items and self.cfg.fallback_auto:
            items = self._extract_by_auto(tree, base_url)

        dedup = {}  # type: Dict[str, ListItem]
        for item in items:
            if item.url:
                dedup[item.url] = item
        return list(dedup.values())

    def _resolve_list_html(self, raw_response_text):
        # type: (str) -> str
        if not self.cfg.response_html_selectors:
            return raw_response_text

        root = html_tree(raw_response_text)
        for selector in self.cfg.response_html_selectors:
            values = apply_selector(selector=selector, context=root, html_text=raw_response_text)
            candidate = first_non_empty([str(v) for v in values])
            if candidate:
                return candidate
        return raw_response_text

    def _extract_by_rules(self, tree, html_text, base_url):
        # type: (etree._Element, str, str) -> List[ListItem]
        item_nodes = []  # type: List[Any]
        if self.cfg.item_selectors:
            for selector in self.cfg.item_selectors:
                nodes = apply_selector(selector=selector, context=tree, html_text=html_text, as_nodes=True)
                item_nodes.extend([n for n in nodes if isinstance(n, (etree._Element, dict, list))])
        else:
            item_nodes = tree.xpath("//a/..")

        result = []  # type: List[ListItem]
        for node in item_nodes:
            title_values = []  # type: List[str]
            link_values = []  # type: List[str]
            date_values = []  # type: List[str]
            area_values = []  # type: List[str]
            for selector in self.cfg.title_selectors:
                title_values.extend(apply_selector(selector=selector, context=node, html_text=html_text))
            for selector in self.cfg.link_selectors:
                link_values.extend(apply_selector(selector=selector, context=node, html_text=html_text))
            for selector in self.cfg.date_selectors:
                date_values.extend(apply_selector(selector=selector, context=node, html_text=html_text))
            for selector in self.cfg.area_selectors:
                area_values.extend(apply_selector(selector=selector, context=node, html_text=html_text))

            title = first_non_empty(title_values)
            link = first_non_empty(link_values)
            date = first_non_empty(date_values)
            area = first_non_empty(area_values)
            if not title and link and isinstance(node, etree._Element):
                title = first_non_empty(node.xpath(".//a/@title") + node.xpath(".//a//text()"))
            if not link and isinstance(node, etree._Element):
                link = first_non_empty(node.xpath(".//a/@href"))

            title = normalize_space(title)
            link = normalize_space(link)
            raw_link = link
            if self.cfg.detail_url_template and link:
                link = self._format_detail_url(node, link)
            if len(title) < self.cfg.min_title_length or not link:
                continue
            if link.lower().startswith("javascript"):
                continue
            result.append(
                ListItem(
                    title=title,
                    url=resolve_url(base_url, link),
                    raw_url=raw_link,
                    date=normalize_space(date),
                    source_url="",
                    area=normalize_space(area),
                )
            )
        return result

    def _format_detail_url(self, node, value):
        # type: (Any, str) -> str
        if not self.cfg.detail_url_template:
            return value

        fields = {}  # type: Dict[str, Any]
        if isinstance(node, dict):
            fields.update(node)
            categorynum = str(node.get("categorynum", "") or "")
            if categorynum:
                fields.setdefault("categorynum6", categorynum[:6])
            postdate = str(node.get("postdate", "") or "")
            if postdate:
                fields.setdefault("postdate_nodash", postdate.replace("-", ""))
        fields.setdefault("value", value)
        fields.setdefault("fdId", value)
        try:
            return self.cfg.detail_url_template.format(**fields)
        except Exception:
            return value

    def _extract_by_auto(self, tree, base_url):
        # type: (etree._Element, str) -> List[ListItem]
        result = []  # type: List[ListItem]
        for anchor in tree.xpath("//a[@href]"):
            href = normalize_space(anchor.get("href", ""))
            if not href or href.lower().startswith("javascript"):
                continue
            title = normalize_space(anchor.get("title") or "".join(anchor.xpath(".//text()")))
            if len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", title)) < self.cfg.min_title_length:
                continue
            result.append(ListItem(title=title, url=resolve_url(base_url, href), raw_url=normalize_space(href), date="", source_url=""))
        return result
