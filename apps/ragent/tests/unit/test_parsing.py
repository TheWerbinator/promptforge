"""Unit: text extraction per content type."""

import pytest

from promptforge_ragent.models import DocumentContentType
from promptforge_ragent.services import parsing
from promptforge_ragent.services.parsing import extract_text


def test_markdown_strips_syntax_to_text() -> None:
    md = b"# Title\n\nHello **world**, see [docs](http://x).\n\n- one\n- two\n"
    out = extract_text(DocumentContentType.MARKDOWN, md)
    assert "Title" in out
    assert "Hello world" in out
    assert "one" in out
    assert "two" in out
    # Markdown punctuation is gone — it rendered to HTML then flattened to text.
    assert "**" not in out
    assert "#" not in out


def test_html_extracts_visible_text() -> None:
    html = b"<html><body><h1>Hi</h1><p>some <b>bold</b> text</p></body></html>"
    out = extract_text(DocumentContentType.HTML, html)
    assert "Hi" in out
    assert "some" in out
    assert "bold" in out
    assert "<" not in out


def test_text_passthrough_and_normalizes() -> None:
    out = extract_text(DocumentContentType.TEXT, b"line one   \n\n\n\n\nline two\n")
    assert out == "line one\n\nline two"


def test_pdf_joins_page_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _stream: object) -> None:
            self.pages = [FakePage("page one"), FakePage("page two")]

    monkeypatch.setattr(parsing, "PdfReader", FakeReader)
    out = extract_text(DocumentContentType.PDF, b"%PDF-fake")
    assert "page one" in out
    assert "page two" in out


def test_unknown_content_type_raises() -> None:
    with pytest.raises(ValueError, match="unsupported content type"):
        extract_text("xml", b"<x/>")  # type: ignore[arg-type]
