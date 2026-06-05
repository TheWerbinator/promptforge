"""Extract plain text from a document's raw bytes, by content type.

Markdown is rendered to HTML (markdown-it-py) then flattened to text, reusing the
same HTML→text path as raw HTML (selectolax/lexbor) — so `## Heading` becomes
"Heading" instead of literal markdown syntax polluting the embedding. PDFs go
through pypdf page-by-page; plain text passes through. Bytes are decoded with
`errors="replace"` so one bad byte can't abort an otherwise-good document.
"""

from __future__ import annotations

import re
from io import BytesIO

from markdown_it import MarkdownIt
from pypdf import PdfReader
from selectolax.lexbor import LexborHTMLParser

from promptforge_ragent.models import DocumentContentType

_md = MarkdownIt()
_BLANK_LINES = re.compile(r"\n[ \t]*\n[ \t]*(?:\n[ \t]*)+")
_TRAILING_WS = re.compile(r"[ \t]+\n")
_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Trim trailing spaces and collapse 3+ blank lines to a single blank line.

    Used for text/PDF, where paragraph breaks carry meaning worth preserving.
    """
    text = _TRAILING_WS.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _html_to_text(html: str) -> str:
    """Flatten HTML to text. Inline runs are space-joined (so `Hello <b>world</b>`
    stays "Hello world"), then all whitespace collapses to single spaces."""
    tree = LexborHTMLParser(html)
    node = tree.body or tree.root
    if node is None:
        return ""
    return _WHITESPACE.sub(" ", node.text(separator=" ")).strip()


def extract_text(content_type: DocumentContentType, data: bytes) -> str:
    """Return the plain-text content of `data` for embedding."""
    if content_type is DocumentContentType.TEXT:
        return _normalize(data.decode("utf-8", errors="replace"))
    if content_type is DocumentContentType.MARKDOWN:
        rendered = _md.render(data.decode("utf-8", errors="replace"))
        return _html_to_text(rendered)
    if content_type is DocumentContentType.HTML:
        return _html_to_text(data.decode("utf-8", errors="replace"))
    if content_type is DocumentContentType.PDF:
        reader = PdfReader(BytesIO(data))
        pages = (page.extract_text() or "" for page in reader.pages)
        return _normalize("\n\n".join(pages))
    raise ValueError(f"unsupported content type: {content_type!r}")
