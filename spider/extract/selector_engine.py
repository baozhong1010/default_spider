import json
import re
from typing import Any, Iterable, List, Optional

from jsonpath_ng import parse as jsonpath_parse
from lxml import etree
from lxml.cssselect import CSSSelector

from spider.config.models import Selector
from spider.utils.helpers import normalize_space


def html_tree(html_text):
    # type: (str) -> Optional[etree._Element]
    try:
        return etree.HTML(html_text)
    except Exception:
        return None


def _to_text(value):
    # type: (Any) -> str
    if isinstance(value, str):
        return normalize_space(value)
    if isinstance(value, bytes):
        return normalize_space(value.decode("utf-8", errors="ignore"))
    if isinstance(value, etree._Element):
        return normalize_space("".join(value.xpath(".//text()")))
    return normalize_space(str(value))


def apply_selector(selector, context, html_text, as_nodes=False):
    # type: (Selector, Optional[etree._Element], str, bool) -> List[Any]
    if selector.kind == "regex":
        return re.findall(selector.expr, html_text, flags=re.S)

    if selector.kind == "jsonpath":
        try:
            payload = json.loads(html_text)
        except Exception:
            return []
        expr = jsonpath_parse(selector.expr)
        return [match.value for match in expr.find(payload)]

    if context is None:
        return []

    if selector.kind == "xpath":
        try:
            values = context.xpath(selector.expr)
        except Exception:
            return []
    elif selector.kind == "css":
        try:
            values = CSSSelector(selector.expr)(context)
        except Exception:
            return []
    else:
        return []

    if as_nodes:
        return list(values)

    output = []  # type: List[str]
    for value in values:
        if isinstance(value, etree._Element):
            if selector.attr:
                attr_value = value.get(selector.attr)
                if attr_value:
                    output.append(normalize_space(attr_value))
            else:
                output.append(_to_text(value))
        else:
            output.append(_to_text(value))
    return [x for x in output if x]


def first_non_empty(values):
    # type: (Iterable[str]) -> str
    for value in values:
        clean = normalize_space(value)
        if clean:
            return clean
    return ""
