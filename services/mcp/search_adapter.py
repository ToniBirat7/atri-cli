"""Provider abstraction for web search and URL fetch tooling.

This module intentionally uses only Python standard library dependencies.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
"""
Atri Code Search Adapter - Grounding Agent Knowledge.

Provides high-quality web search capabilities using the Tavily API.
Includes optimizations for LLM context management:
- Snippet truncation (1000 chars max)
- Keyword-overlap ranking to prioritize relevance.
- Error handling and source attribution.
"""

import os
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Protocol

DEFAULT_TIMEOUT_SECONDS = 20
MAX_FETCH_CHARS = 50000

# Built-in Tavily API key for web search — provided by Atri Code for all users.
ATRI_TAVILY_API_KEY = "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"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    provider: str


def _normalize_http_url(raw_url: str) -> str:
    text = (raw_url or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""
    cleaned = parsed._replace(fragment="")
    return urllib.parse.urlunparse(cleaned)


def _build_citations(results: list[SearchResult]) -> list[str]:
    citations: list[str] = []
    seen: set[str] = set()
    for result in results:
        normalized = _normalize_http_url(result.url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        citations.append(normalized)
    return citations


class SearchProvider(Protocol):
    name: str

    def query(self, query: str, max_results: int) -> list[SearchResult]:
        ...


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._in_result_link = False
        self._current_href = ""
        self._current_title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return

        attr_map = {k: (v or "") for k, v in attrs}
        href = attr_map.get("href", "")
        css_class = attr_map.get("class", "")
        if "result__a" in css_class or "result-link" in css_class:
            self._in_result_link = True
            self._current_href = href
            self._current_title_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._in_result_link:
            return

        title = " ".join("".join(self._current_title_parts).split())
        resolved = _normalize_duckduckgo_href(self._current_href)
        if title and resolved:
            self.results.append(
                SearchResult(
                    title=title,
                    url=resolved,
                    snippet="",
                    provider="duckduckgo",
                )
            )

        self._in_result_link = False
        self._current_href = ""
        self._current_title_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_result_link and data:
            self._current_title_parts.append(data)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_stack: list[str] = []
        self._chunks: list[str] = []
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_stack.append(tag)
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_stack:
            if self._skip_stack[-1] == tag:
                self._skip_stack.pop()
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_stack:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title = text
            return
        self._chunks.append(text)

    def get_text(self) -> str:
        return "\n".join(self._chunks)


class DuckDuckGoProvider:
    name = "duckduckgo"

    def query(self, query: str, max_results: int) -> list[SearchResult]:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "atri-code/1.0"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            html = response.read().decode("utf-8", errors="replace")

        parser = _DuckDuckGoResultParser()
        parser.feed(html)

        deduped: list[SearchResult] = []
        seen: set[str] = set()
        for result in parser.results:
            if result.url in seen:
                continue
            seen.add(result.url)
            deduped.append(result)
            if len(deduped) >= max_results:
                break
        return deduped


class BraveProvider:
    name = "brave"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def query(self, query: str, max_results: int) -> list[SearchResult]:
        req = urllib.request.Request(
            f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote_plus(query)}&count={max_results}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
                "User-Agent": "atri-code/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))

        results: list[SearchResult] = []
        for item in payload.get("web", {}).get("results", []):
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    snippet=str(item.get("description", "")).strip(),
                    provider="brave",
                )
            )
        return [r for r in results if r.url and r.title][:max_results]


class TavilyProvider:
    name = "tavily"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def query(self, query: str, max_results: int) -> list[SearchResult]:
        body = json.dumps(
            {
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_answer": False,
                "include_images": False,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "atri-code/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))

        results: list[SearchResult] = []
        for item in payload.get("results", []):
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    snippet=str(item.get("content", "")).strip(),
                    provider="tavily",
                )
            )

        return [r for r in results if r.url and r.title][:max_results]


def _normalize_duckduckgo_href(href: str) -> str:
    if not href:
        return ""

    if href.startswith("http://") or href.startswith("https://"):
        return href

    if href.startswith("/"):
        parsed = urllib.parse.urlparse(href)
        params = urllib.parse.parse_qs(parsed.query)
        uddg = params.get("uddg", [""])[0]
        if uddg:
            return urllib.parse.unquote(uddg)

    return ""


def _resolve_tavily_api_key(tavily_api_key: str | None = None) -> str | None:
    if tavily_api_key:
        return tavily_api_key
    env_key = os.getenv("TAVILY_API_KEY")
    if env_key:
        return env_key
    # Fall back to built-in API key
    return ATRI_TAVILY_API_KEY


def get_search_provider(
    provider: str,
    brave_api_key: str | None = None,
    tavily_api_key: str | None = None,
) -> SearchProvider:
    normalized = (provider or "auto").strip().lower()
    resolved_tavily_key = _resolve_tavily_api_key(tavily_api_key)

    if normalized in {"auto", "duckduckgo", "ddg"}:
        if normalized == "auto" and resolved_tavily_key:
            return TavilyProvider(resolved_tavily_key)
        if normalized == "auto" and brave_api_key:
            return BraveProvider(brave_api_key)
        return DuckDuckGoProvider()

    if normalized == "tavily":
        if not resolved_tavily_key:
            raise ValueError("Tavily provider requires TAVILY_API_KEY")
        return TavilyProvider(resolved_tavily_key)

    if normalized == "brave":
        if not brave_api_key:
            raise ValueError("Brave provider requires BRAVE_SEARCH_API_KEY")
        return BraveProvider(brave_api_key)

    raise ValueError(f"Unsupported search provider: {provider}")


def search_web_results(
    *,
    query: str,
    provider: str,
    max_results: int,
    brave_api_key: str | None = None,
    tavily_api_key: str | None = None,
) -> dict[str, object]:
    text = (query or "").strip()
    if not text:
        raise ValueError("query cannot be empty")

    if max_results < 1:
        raise ValueError("max_results must be >= 1")
    max_results = min(max_results, 10)

    adapter = get_search_provider(
        provider,
        brave_api_key=brave_api_key,
        tavily_api_key=tavily_api_key,
    )
    results = adapter.query(text, max_results=max_results)
    sanitized_results = [
        SearchResult(
            title=item.title,
            url=_normalize_http_url(item.url),
            snippet=item.snippet[:1000] if item.snippet else "",
            provider=item.provider,
        )
        for item in results
    ]
    sanitized_results = [item for item in sanitized_results if item.url and item.title]
    
    # Simple re-ranking based on query keyword overlap
    def score_result(res: SearchResult) -> float:
        score = 0.0
        query_words = set(text.lower().split())
        content = (res.title + " " + res.snippet).lower()
        for word in query_words:
            if word in content:
                score += 1.0
        return score

    sanitized_results.sort(key=score_result, reverse=True)
    citations = _build_citations(sanitized_results)

    return {
        "query": text,
        "provider": adapter.name,
        "results": [asdict(item) for item in sanitized_results],
        "count": len(sanitized_results),
        "citations": citations,
    }


def fetch_web_content(*, url: str, max_chars: int = 12000) -> dict[str, object]:
    normalized_url = _normalize_http_url(url)
    if not normalized_url:
        raise ValueError("url cannot be empty and must be a valid http(s) URL")

    parsed = urllib.parse.urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are supported")

    safe_max_chars = max(200, min(max_chars, MAX_FETCH_CHARS))

    req = urllib.request.Request(normalized_url, headers={"User-Agent": "atri-code/1.0"})
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")

    charset_match = re.search(r"charset=([\w\-]+)", content_type, flags=re.IGNORECASE)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    decoded = raw.decode(encoding, errors="replace")

    extractor = _HTMLTextExtractor()
    extractor.feed(decoded)

    text = extractor.get_text().strip()
    title = extractor.title.strip()
    if not text:
        text = decoded.strip()

    text = text[:safe_max_chars]

    return {
        "url": normalized_url,
        "title": title,
        "content": text,
        "content_type": content_type,
        "truncated": len(text) >= safe_max_chars,
        "citation": normalized_url,
        "citations": [normalized_url],
    }
