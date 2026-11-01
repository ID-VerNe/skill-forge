#!/usr/bin/env python3
"""
GREEN tests — verify each bug fix works.
"""
import sys
import os
import glob

SKILL_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "glue-engineer"))
sys.path.insert(0, SKILL_ROOT)

PASS = 0
FAIL = 0

def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  [PASS] {name}")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        FAIL += 1


def _read_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# Bug 1: Stale fallback was dead code (removed) — now always caches,
# so cache_get should return stale data on retry failure
def test_bug1_stale_works():
    from polyglot.common.cache import cache_set, cache_get, cache_get_stale, cache_clean
    import requests

    cache_clean()
    key = "scout:python:test_bug1:3"

    # Set up stale cache
    cache_set(key, {"results": [{"name": "stale"}]}, ttl_seconds=-1)

    # Verify expired
    assert cache_get(key) is None, "cache should be expired"

    # Verify stale fallback works
    stale = cache_get_stale(key)
    assert stale is not None, "stale fallback should return data"
    assert stale["results"][0]["name"] == "stale", "stale data should match"


# Bug 2: 404 no longer retried (RuntimeError removed from retryable_exceptions)
def test_bug2_404_no_retry():
    src = _read_file(os.path.join(SKILL_ROOT, "polyglot", "backends", "python", "scout.py"))

    # Verify RuntimeError is NOT in retryable_exceptions
    retry_section = src.split("retryable_exceptions=")[1].split(")")[0]
    assert "RuntimeError" not in retry_section, (
        f"RuntimeError still in retryable_exceptions: {retry_section}"
    )

    # Verify _fetch_exact_with_retry still raises RuntimeError on None
    assert "raise RuntimeError" in src, "must still raise RuntimeError on 404"


# Bug 3: _ALT_HEADERS is now used in _fetch_html_search
def test_bug3_alt_headers_used():
    src = _read_file(os.path.join(SKILL_ROOT, "polyglot", "backends", "python", "scout.py"))
    assert src.count("_ALT_HEADERS") >= 2, "_ALT_HEADERS should be defined and used"

    # Verify CF retry path uses _ALT_HEADERS
    assert "cf-browser-verification" in src, "CF detection should exist"
    assert "_ALT_HEADERS" in src.split("cf-browser-verification")[1][:200], (
        "_ALT_HEADERS should be used in CF retry path"
    )


# Bug 4: cache_get_or_retry removed
def test_bug4_cache_get_or_retry_removed():
    src = _read_file(os.path.join(SKILL_ROOT, "polyglot", "common", "cache.py"))
    assert "cache_get_or_retry" not in src, "cache_get_or_retry should be removed"


# Bug 5: CF retry uses _ALT_HEADERS
def test_bug5_cf_retry_works():
    src = _read_file(os.path.join(SKILL_ROOT, "polyglot", "backends", "python", "scout.py"))

    # Find _fetch_html_search function
    fn_start = src.index("def _fetch_html_search")
    fn_end = src.index("def _build_result") if "def _build_result" in src[fn_start+1:] else len(src)

    fetch_html = src[fn_start:fn_end]
    assert "_ALT_HEADERS" in fetch_html, "_ALT_HEADERS must be used in _fetch_html_search"
    assert "cf-browser-verification" in fetch_html, "CF detection must be in _fetch_html_search"


# Bug 6: Auto cache cleanup in cache_set
def test_bug6_auto_cleanup():
    src = _read_file(os.path.join(SKILL_ROOT, "polyglot", "common", "cache.py"))

    # Find cache_set function
    fn_start = src.index("def cache_set(")
    fn_end = src.index("def cache_clean(")

    cache_set_src = src[fn_start:fn_end]
    assert "random.random()" in cache_set_src, "cache_set should have probabilistic cleanup"
    assert "DELETE FROM cache" in cache_set_src, "cache_set should delete expired entries"


if __name__ == "__main__":
    print("=" * 60)
    print("GREEN Tests — Verify bug fixes")
    print("=" * 60)
    print()

    tests = [
        ("Bug 1: stale fallback works", test_bug1_stale_works),
        ("Bug 2: 404 no retry", test_bug2_404_no_retry),
        ("Bug 3: _ALT_HEADERS used", test_bug3_alt_headers_used),
        ("Bug 4: cache_get_or_retry removed", test_bug4_cache_get_or_retry_removed),
        ("Bug 5: CF retry with _ALT_HEADERS", test_bug5_cf_retry_works),
        ("Bug 6: auto cache cleanup", test_bug6_auto_cleanup),
    ]

    for name, fn in tests:
        test(name, fn)

    print()
    print("=" * 60)
    print(f"GREEN RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)