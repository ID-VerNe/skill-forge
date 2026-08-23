"""Tests for discover command, Go lookup, and proxy fallback."""

import os
import sys

SKILL_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SKILL_ROOT)

import pytest
import requests

from polyglot.commands.discover import _map_gh_language_to_backend
from polyglot.backends.go.scout import lookup


class TestMapLanguageToBackend:
    """_map_gh_language_to_backend maps GitHub repo languages correctly."""

    def test_go(self):
        assert _map_gh_language_to_backend("go") == "go"
        assert _map_gh_language_to_backend("golang") == "go"

    def test_python(self):
        assert _map_gh_language_to_backend("python") == "python"
        assert _map_gh_language_to_backend("py") is None  # not in mapping

    def test_typescript_js(self):
        assert _map_gh_language_to_backend("typescript") == "javascript"
        assert _map_gh_language_to_backend("javascript") == "javascript"
        assert _map_gh_language_to_backend("js") == "javascript"

    def test_rust(self):
        assert _map_gh_language_to_backend("rust") == "rust"

    def test_java_kotlin(self):
        assert _map_gh_language_to_backend("java") == "java"
        assert _map_gh_language_to_backend("kotlin") == "kotlin"

    def test_c_cpp_family(self):
        assert _map_gh_language_to_backend("c") == "c_cpp"
        assert _map_gh_language_to_backend("c++") == "c_cpp"
        assert _map_gh_language_to_backend("c#") == "c_cpp"
        assert _map_gh_language_to_backend("cpp") == "c_cpp"

    def test_short_aliases_not_in_mapping(self):
        # GitHub's detected language names are full forms; short aliases
        # like "py", "kt" are NOT in _map_gh_language_to_backend (but "ts"
        # is, since it collides with "typescript" abbreviation in the map).
        assert _map_gh_language_to_backend("py") is None
        assert _map_gh_language_to_backend("kt") is None

    def test_unknown(self):
        assert _map_gh_language_to_backend("zig") is None
        assert _map_gh_language_to_backend("nim") is None
        assert _map_gh_language_to_backend("") is None
        assert _map_gh_language_to_backend("  ") is None


class TestGoLookup:
    """Go module proxy exact version lookup."""

    def test_known_module(self):
        """A well-known Go module returns version + last_commit."""
        result = lookup("github.com/gin-gonic/gin")
        assert result is not None
        assert result["version"].startswith("v")
        assert "T" in result["last_commit"]  # ISO 8601 timestamp

    def test_nonexistent_module(self):
        """A non-existent Go module returns None."""
        result = lookup("github.com/ID-VerNe/nonexistent-repo-xyz-99999")
        assert result is None

    def test_cache_negative(self):
        """A 404 is cached as negative, so a second call also returns None."""
        path = "github.com/ID-VerNe/nonexistent-repo-xyz-99999"
        r1 = lookup(path)
        r2 = lookup(path)
        assert r1 is None
        assert r2 is None


class TestProxyFallback:
    """proxy_fallback.get retries without proxy on ProxyError."""

    def test_happy_path(self):
        """When the first request succeeds, no fallback is used."""
        from polyglot.common.proxy_fallback import get as proxy_get

        resp, used_no_proxy = proxy_get("https://example.com", timeout=5)
        assert resp.status_code in (200, 404)  # 200 OK or 404 redirect
        assert used_no_proxy is False

    def test_fallback_on_proxy_error(self, monkeypatch):
        """When the first request raises ProxyError, fallback retries."""
        from polyglot.common.proxy_fallback import get as proxy_get

        call_count = 0

        def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.exceptions.ProxyError("proxy down")
            # Second call (no proxy) succeeds
            resp = requests.Response()
            resp.status_code = 200
            resp._content = b'{"ok": true}'
            resp.encoding = "utf-8"
            return resp

        monkeypatch.setattr(requests, "get", _fake_get)
        resp, used_no_proxy = proxy_get("https://example.com", timeout=5)
        assert resp.status_code == 200
        assert used_no_proxy is True
        assert call_count == 2


class TestGoLookupWithProxy:
    """Go lookup adapts to proxy environment automatically."""

    def test_known_module_via_proxy(self):
        """lookup itself works end-to-end (implicitly tests proxy_fallback inside)."""
        result = lookup("github.com/gin-gonic/gin")
        assert result is not None
        assert result["version"].startswith("v")
        assert result["last_commit"] != ""