from __future__ import annotations

import pytest

from search_adapter import (
    _DuckDuckGoResultParser,
    _normalize_duckduckgo_href,
    fetch_web_content,
    search_web_results,
)


def test_normalize_duckduckgo_redirect_href():
    href = "/l/?kh=-1&uddg=https%3A%2F%2Fexample.com%2Fdoc"
    assert _normalize_duckduckgo_href(href) == "https://example.com/doc"


def test_duckduckgo_parser_extracts_result_links():
    html = """
    <html>
      <body>
        <a class=\"result__a\" href=\"https://example.com/a\">Example A</a>
        <a class=\"result-link\" href=\"/l/?uddg=https%3A%2F%2Fexample.com%2Fb\">Example B</a>
      </body>
    </html>
    """
    parser = _DuckDuckGoResultParser()
    parser.feed(html)

    assert len(parser.results) == 2
    assert parser.results[0].url == "https://example.com/a"
    assert parser.results[1].url == "https://example.com/b"


def test_fetch_web_content_rejects_non_http_scheme():
    with pytest.raises(ValueError):
        fetch_web_content(url="file:///tmp/test.txt")


def test_search_web_results_uses_selected_provider(monkeypatch):
    class _FakeProvider:
        name = "fake"

        def query(self, query: str, max_results: int):
            return [
                {
                    "title": "T1",
                    "url": "https://example.com/1",
                    "snippet": "S1",
                    "provider": "fake",
                }
            ]

    def _fake_get_provider(provider: str, brave_api_key=None):
        class _Adapter:
            name = "fake"

            def query(self, query: str, max_results: int):
                from search_adapter import SearchResult

                return [SearchResult(title="T1", url="https://example.com/1", snippet="S1", provider="fake")]

        return _Adapter()

    monkeypatch.setattr("search_adapter.get_search_provider", _fake_get_provider)

    result = search_web_results(query="hello", provider="auto", max_results=3)
    assert result["provider"] == "fake"
    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.com/1"
