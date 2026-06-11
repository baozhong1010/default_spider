import html as html_lib
import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from pdfminer.high_level import extract_text

from spider.extract.selector_engine import html_tree
from spider.utils.helpers import normalize_space, resolve_url


@dataclass
class PdfBodyDetectionResult:
    is_pdf_body: bool = False
    pdf_url: Optional[str] = None
    detection_method: Optional[str] = None
    matched_urls: List[str] = field(default_factory=list)


class PdfBodyDetector(object):
    PDFJS_VIEWER_PATTERNS = [
        r"/pdfjs/web/viewer\.html",
        r"/pdfjs/viewer\.html",
        r"/pdf\.js/web/viewer\.html",
        r"viewer\.html\?file=",
    ]

    PDF_URL_PATTERNS = [
        r"\.pdf(?:\?|$)",
        r'method=download(?:[^\s\'\"]*)',
        r"method=readSteam",
        r"downloadAttachment",
        r"downloadFile",
        r"getPdf",
        r"loadPdf",
        r"getFile",
        r"/download/",
    ]

    JS_URL_PATTERNS = [
        r"(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]",
        r"\.attr\(\s*['\"]src['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        r"\.prop\(\s*['\"]src['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        r"['\"]([^'\"]*viewer\.html\?file=[^'\"]+)['\"]",
    ]

    JS_VIEWER_VARIABLE_PATTERN = (
        r"var\s+baseurl\s*=\s*['\"]([^'\"]*viewer\.html\?file=)['\"];"
        r".*?var\s+url\s*=\s*['\"]([^'\"]+)['\"];"
        r".*?\.attr\(\s*['\"]src['\"]\s*,\s*baseurl\s*\+\s*encodeURIComponent\(url\)\s*\)"
    )

    # 部分站点会同时暴露 download 和 readSteam，这里优先提取 readSteam 正文流地址。
    READ_STREAM_URL_PATTERN = r"['\"]([^'\"]*sysAttMain\.do\?method=readSteam&fdId=[^'\"]+)['\"]"
    READ_STREAM_JOIN_PATTERN = r"['\"]([^'\"]*sysAttMain\.do\?method=readSteam&fdId=)['\"]\s*\+\s*['\"]([0-9a-f]+)['\"]"

    def detect(self, page_url, headers=None, html_text=""):
        # type: (str, Optional[Dict[str, str]], str) -> PdfBodyDetectionResult
        headers = headers or {}
        content_type = self._get_header(headers, "Content-Type").lower()

        if "application/pdf" in content_type or (page_url or "").lower().endswith(".pdf"):
            return PdfBodyDetectionResult(
                is_pdf_body=True,
                pdf_url=page_url,
                detection_method="direct_pdf_response",
                matched_urls=[page_url],
            )

        viewer_pdf = self._detect_pdfjs_viewer_url(page_url)
        if viewer_pdf:
            return PdfBodyDetectionResult(
                is_pdf_body=True,
                pdf_url=viewer_pdf,
                detection_method="pdfjs_viewer_url",
                matched_urls=self._unique_urls([page_url, viewer_pdf]),
            )

        tree = html_tree(html_text)
        if tree is not None:
            embed_result = self._detect_embed_pdf(tree, page_url)
            if embed_result is not None:
                return embed_result

        js_result = self._detect_js_pdf(page_url, html_text)
        if js_result is not None:
            return js_result

        return PdfBodyDetectionResult()

    @staticmethod
    def _get_header(headers, name):
        # type: (Dict[str, str], str) -> str
        for key, value in headers.items():
            if key.lower() == name.lower():
                return str(value)
        return ""

    def _is_pdf_url(self, url):
        # type: (str) -> bool
        lower = (url or "").lower()
        if lower.endswith(".pdf"):
            return True
        for pattern in self.PDF_URL_PATTERNS:
            if re.search(pattern, url or "", re.IGNORECASE):
                return True
        return False

    def _detect_pdfjs_viewer_url(self, url):
        # type: (str) -> Optional[str]
        for pattern in self.PDFJS_VIEWER_PATTERNS:
            if re.search(pattern, url or "", re.IGNORECASE):
                parsed = urlparse(url)
                file_param = parse_qs(parsed.query).get("file", [None])[0]
                if file_param:
                    resolved = resolve_url(url, unquote(file_param))
                    return resolved
        return None

    def _detect_embed_pdf(self, tree, page_url):
        # type: (object, str) -> Optional[PdfBodyDetectionResult]
        for tag_name, attr_name in (("iframe", "src"), ("embed", "src"), ("object", "data")):
            for raw in tree.xpath("//%s/@%s" % (tag_name, attr_name)):
                result = self._resolve_candidate(page_url, raw, "html_embed_tag")
                if result is not None:
                    return result
        return None

    def _detect_js_pdf(self, page_url, html_text):
        # type: (str, str) -> Optional[PdfBodyDetectionResult]
        viewer_var_match = re.search(self.JS_VIEWER_VARIABLE_PATTERN, html_text or "", re.IGNORECASE | re.S)
        if viewer_var_match:
            viewer_url = resolve_url(page_url, viewer_var_match.group(1))
            pdf_url = resolve_url(page_url, viewer_var_match.group(2))
            # viewer 中常同时出现 download 地址，若能提取 readSteam 则优先使用。
            stream_url = self._extract_read_stream_url(page_url, html_text)
            preferred_url = stream_url or pdf_url
            if self._is_pdf_url(preferred_url):
                return PdfBodyDetectionResult(
                    is_pdf_body=True,
                    pdf_url=preferred_url,
                    detection_method="js_pdf_viewer_variables",
                    matched_urls=self._unique_urls([viewer_url, pdf_url, stream_url]),
                )

        for pattern in self.JS_URL_PATTERNS:
            for match in re.finditer(pattern, html_text or "", re.IGNORECASE):
                result = self._resolve_candidate(page_url, match.group(1), "js_pdf_reference")
                if result is not None:
                    return result
        return None

    def _extract_read_stream_url(self, page_url, html_text):
        # type: (str, str) -> Optional[str]
        joined_match = re.search(self.READ_STREAM_JOIN_PATTERN, html_text or "", re.IGNORECASE)
        if joined_match:
            return resolve_url(page_url, joined_match.group(1) + joined_match.group(2))

        direct_match = re.search(self.READ_STREAM_URL_PATTERN, html_text or "", re.IGNORECASE)
        if direct_match:
            return resolve_url(page_url, direct_match.group(1))

        return None

    def _resolve_candidate(self, page_url, raw_url, detection_method):
        # type: (str, str, str) -> Optional[PdfBodyDetectionResult]
        candidate = normalize_space(str(raw_url or "")).replace("\\/", "/")
        if not candidate or candidate.lower().startswith("javascript"):
            return None

        resolved = resolve_url(page_url, candidate)
        viewer_pdf = self._detect_pdfjs_viewer_url(resolved)
        if viewer_pdf:
            return PdfBodyDetectionResult(
                is_pdf_body=True,
                pdf_url=viewer_pdf,
                detection_method=detection_method,
                matched_urls=self._unique_urls([resolved, viewer_pdf]),
            )

        if self._is_pdf_url(resolved):
            return PdfBodyDetectionResult(
                is_pdf_body=True,
                pdf_url=resolved,
                detection_method=detection_method,
                matched_urls=[resolved],
            )
        return None

    @staticmethod
    def _unique_urls(urls):
        # type: (List[str]) -> List[str]
        seen = set()
        output = []
        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            output.append(url)
        return output


class PdfBodyConverter(object):
    CID_TOKEN_PATTERN = re.compile(r"\(cid:\d+\)")
    CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

    def convert(self, pdf_bytes, title=None):
        # type: (bytes, Optional[str]) -> str
        text = extract_text(io.BytesIO(pdf_bytes or b""))
        pages = [page for page in text.split("\f") if page.strip()]

        html_parts = [
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>%s</title>" % self._escape(title or "PDF Content"),
            "<style>",
            "body { font-family: Arial, sans-serif; line-height: 1.6; margin: 24px; }",
            ".page { margin-bottom: 24px; }",
            ".page-num { color: #777; font-size: 12px; margin-top: 12px; }",
            "p { margin: 0 0 8px; }",
            "</style>",
            "</head>",
            "<body>",
        ]
        if title:
            html_parts.append("<h1>%s</h1>" % self._escape(title))

        if not pages:
            pages = [text or ""]

        total_pages = len(pages)
        for index, page_text in enumerate(pages, 1):
            html_parts.append('<div class="page" id="page-%s">' % index)
            lines = [normalize_space(line) for line in page_text.splitlines()]
            rendered = False
            for line in lines:
                if not line:
                    continue
                html_parts.append("<p>%s</p>" % self._escape(line))
                rendered = True
            if not rendered:
                html_parts.append("<p></p>")
            html_parts.append('<div class="page-num">Page %s / %s</div>' % (index, total_pages))
            html_parts.append("</div>")

        html_parts.extend(["</body>", "</html>"])
        return "\n".join(html_parts)

    def is_text_corrupted(self, text):
        # type: (str) -> bool
        text = str(text or "")
        if not text:
            return False

        # 某些 PDF 缺少有效的 ToUnicode 映射时，提取结果会出现大量 (cid:123) 垃圾标记。
        cid_tokens = len(self.CID_TOKEN_PATTERN.findall(text))
        if cid_tokens >= 5:
            return True

        # 控制字符大量出现时，通常也说明提取文本已经损坏。
        control_chars = len(self.CONTROL_CHAR_PATTERN.findall(text))
        return control_chars >= 20

    @staticmethod
    def _escape(value):
        # type: (str) -> str
        return html_lib.escape(value or "")
