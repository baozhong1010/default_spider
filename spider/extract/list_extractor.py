import re
from dataclasses import dataclass
from typing import Dict, List

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
        item_nodes = []  # type: List[etree._Element]
        if self.cfg.item_selectors:
            for selector in self.cfg.item_selectors:
                nodes = apply_selector(selector=selector, context=tree, html_text=html_text, as_nodes=True)
                item_nodes.extend([n for n in nodes if isinstance(n, etree._Element)])
        else:
            item_nodes = tree.xpath("//a/..")

        result = []  # type: List[ListItem]
        for node in item_nodes:
            title_values = []  # type: List[str]
            link_values = []  # type: List[str]
            date_values = []  # type: List[str]
            for selector in self.cfg.title_selectors:
                title_values.extend(apply_selector(selector=selector, context=node, html_text=html_text))
            for selector in self.cfg.link_selectors:
                link_values.extend(apply_selector(selector=selector, context=node, html_text=html_text))
            for selector in self.cfg.date_selectors:
                date_values.extend(apply_selector(selector=selector, context=node, html_text=html_text))

            title = first_non_empty(title_values)
            link = first_non_empty(link_values)
            date = first_non_empty(date_values)
            if not title and link:
                title = first_non_empty(node.xpath(".//a/@title") + node.xpath(".//a//text()"))
            if not link:
                link = first_non_empty(node.xpath(".//a/@href"))

            title = normalize_space(title)
            if len(title) < self.cfg.min_title_length or not link:
                continue
            if link.lower().startswith("javascript"):
                continue
            result.append(ListItem(title=title, url=resolve_url(base_url, link), date=normalize_space(date), source_url=""))
        return result

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
            result.append(ListItem(title=title, url=resolve_url(base_url, href), date="", source_url=""))
        return result
