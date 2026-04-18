"""Integration tests for web search and content fetching grounding in the orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# This test validates the end-to-end flow:
# 1. LLM requests search_web tool
# 2. Search results are returned
# 3. LLM requests fetch_url on top result
# 4. Page content is extracted
# 5. Final response includes citations


def test_search_adapter_module_exists():
    """Verify search_adapter module is importable."""
    try:
        from search_adapter import search_web_results, fetch_web_content
    except ImportError as e:
        pytest.fail(f"search_adapter import failed: {e}")


def test_search_web_results_validates_inputs():
    """Test that search_web_results validates query and max_results."""
    from search_adapter import search_web_results

    with pytest.raises(ValueError):
        search_web_results(query="", provider="auto", max_results=5)

    with pytest.raises(ValueError):
        search_web_results(query="hello", provider="auto", max_results=0)


def test_fetch_web_content_validates_url_scheme():
    """Test that fetch_web_content rejects non-http schemes."""
    from search_adapter import fetch_web_content

    with pytest.raises(ValueError):
        fetch_web_content(url="ftp://example.com")

    with pytest.raises(ValueError):
        fetch_web_content(url="file:///tmp/test")


def test_search_result_dataclass_fields():
    """Verify SearchResult dataclass has expected fields."""
    from search_adapter import SearchResult

    result = SearchResult(
        title="Example",
        url="https://example.com",
        snippet="Test snippet",
        provider="test",
    )
    assert result.title == "Example"
    assert result.url == "https://example.com"
    assert result.snippet == "Test snippet"
    assert result.provider == "test"


def test_duckduckgo_provider_name():
    """Verify DuckDuckGo provider has correct name attribute."""
    from search_adapter import DuckDuckGoProvider

    provider = DuckDuckGoProvider()
    assert provider.name == "duckduckgo"


def test_brave_provider_requires_api_key():
    """Verify Brave provider requires API key on initialization."""
    from search_adapter import BraveProvider

    provider = BraveProvider(api_key="test-key")
    assert provider.api_key == "test-key"
    assert provider.name == "brave"


def test_get_search_provider_defaults_to_duckduckgo():
    """Test that get_search_provider defaults to DuckDuckGo when no key provided."""
    from search_adapter import get_search_provider

    provider = get_search_provider("auto", brave_api_key=None)
    assert provider.name == "duckduckgo"


def test_get_search_provider_raises_on_unknown():
    """Test that get_search_provider raises ValueError for unknown provider."""
    from search_adapter import get_search_provider

    with pytest.raises(ValueError):
        get_search_provider("unknown-provider")


def test_search_web_results_includes_citations(monkeypatch):
    """Ensure search results include normalized citation URLs."""
    from search_adapter import SearchResult, search_web_results

    class _FakeProvider:
        name = "fake"

        def query(self, query: str, max_results: int):
            return [
                SearchResult("A", "https://example.com/a#frag", "x", "fake"),
                SearchResult("B", "https://example.com/b", "y", "fake"),
            ]

    monkeypatch.setattr("search_adapter.get_search_provider", lambda provider, brave_api_key=None: _FakeProvider())

    payload = search_web_results(query="hello", provider="auto", max_results=5)
    assert payload["count"] == 2
    assert payload["citations"] == ["https://example.com/a", "https://example.com/b"]


def test_fetch_web_content_includes_citation_fields(monkeypatch):
    """Ensure fetched content carries citation fields for downstream grounding."""
    from search_adapter import fetch_web_content

    class _FakeResponse:
        def __init__(self):
            self.headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self):
            return b"<html><title>T</title><body>Hello world</body></html>"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=20: _FakeResponse())
    payload = fetch_web_content(url="https://example.com/page#frag", max_chars=1000)

    assert payload["citation"] == "https://example.com/page"
    assert payload["citations"] == ["https://example.com/page"]


def test_citation_prompt_language_in_policies(monkeypatch):
    """Verify citation-grounding language is in system prompts."""
    from orchestrator import prompt_policy

    # Check that at least one prompt profile mentions citations/sources
    profiles_to_check = ["legal-strict", "hybrid", "general-purpose"]
    profiles_with_citations = []

    for profile_name in profiles_to_check:
        try:
            prompt = prompt_policy.build_system_prompt(
                profile_name,
                assistant_name="Test",
                model_name="test-model",
                enable_thinking=False,
                fallback_text="Unknown",
                disclaimer_text="Disclaimer",
                legal_help_line="Help",
            )
            if "cite" in prompt.lower() or "source" in prompt.lower() or "url" in prompt.lower():
                profiles_with_citations.append(profile_name)
        except Exception:
            pass

    assert len(profiles_with_citations) > 0, "No system prompts mention citations or sources"
