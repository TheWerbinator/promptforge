"""Unit: upload content-type detection."""

from promptforge_ragent.api.v1.corpora import _detect_content_type
from promptforge_ragent.models import DocumentContentType


def test_detect_known_extensions() -> None:
    assert _detect_content_type("a.md") is DocumentContentType.MARKDOWN
    assert _detect_content_type("a.MARKDOWN") is DocumentContentType.MARKDOWN
    assert _detect_content_type("doc.pdf") is DocumentContentType.PDF
    assert _detect_content_type("page.HTML") is DocumentContentType.HTML
    assert _detect_content_type("notes.txt") is DocumentContentType.TEXT


def test_detect_unknown_returns_none() -> None:
    assert _detect_content_type("data.xlsx") is None
    assert _detect_content_type("noext") is None
    assert _detect_content_type(None) is None
