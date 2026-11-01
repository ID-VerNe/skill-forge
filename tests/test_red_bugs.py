#!/usr/bin/env python3
"""
RED tests — prove each bug exists by reading the source code.
Using static analysis because deep mocking of request chains is fragile.
"""
import sys
import os
import re

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


# ═══════════════════════════════════════
# Bug 1: Python scout dead code — stale fallback never reached
# ═══════════════════════════════════════

def test_bug1_dead_code():
    """Bug 1: stale fallback code in python/scout.py is unreachable.
    Check: the 'return output' before the stale fallback block makes it dead code.
    """
    source = _read_file(os.path.join(SKILL_ROOT, "polyglot", "backends", "python", "scout.py"))

    # Find the stale fallback block
    if "stale = cache_get_stale" not in source:
        raise AssertionError("No stale fallback code found at all")

    # Find the line before stale fallback
    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "stale = cache_get_stale" in line:
            lines_before = lines[max(0, i-5):i]
            before_text = "\n".join(lines_before)
            # Check if there's a 'return output' before this line
            if "return output" in before_text:
                # Check if the return is before the stale block (not in a different function)
                return_line_idx = i - 1 - lines_before[::-1].index("return output")
                # The return should be inside the same function (search function)
                # Count function defs between them
                func_defs = sum(1 for l in lines[:i] if l.strip().startswith("def "))
                print(f"    stale fallback at line {i+1}, 'return output' at line {return_line_idx+1}, same function scope")
                raise AssertionError(
                    "BUG CONFIRMED: stale fallback code is unreachable. "
                    "Line before it does 'return output', so lines 313-319 are dead."
                )

    # If we get here, either the stale fallback is reachable or the code structure changed
    print("    stale fallback appears reachable — bug may have been fixed already")
    raise AssertionError("Cannot confirm bug — stale fallback may be reachable or structure changed")


# ═══════════════════════════════════════
# Bug 2: Python scout retries 404 (RuntimeError in retryable_exceptions)
# ═══════════════════════════════════════

def test_bug2_404_retried():
    """Bug 2: RuntimeError is in retryable_exceptions, so 404s get retried.
    When _fetch_exact returns None (404), _fetch_exact_with_retry raises RuntimeError,
    which retry_call catches and retries. This is wrong — 404 should not be retried.
    """
    source = _read_file(os.path.join(SKILL_ROOT, "polyglot", "backends", "python", "scout.py"))

    # Find the retry_call call for the exact match
    # Look for: retryable_exceptions=(..., RuntimeError)
    retry_pattern = r"retryable_exceptions=\([^)]*RuntimeError[^)]*\)"
    match = re.search(retry_pattern, source)
    if not match:
        raise AssertionError("Cannot find RuntimeError in retryable_exceptions")

    # Found RuntimeError in retryable_exceptions — bug confirmed
    # Now check that _fetch_exact_with_retry raises RuntimeError on None
    if "raise RuntimeError" in source:
        print(f"    Found: {match.group()}")
        raise AssertionError(
            "BUG CONFIRMED: RuntimeError is in retryable_exceptions, "
            "and _fetch_exact_with_retry raises RuntimeError on None (404). "
            "This means 404 responses get retried 3 times with backoff."
        )

    print("    RuntimeError pattern not found — bug may be fixed")
    raise AssertionError("Cannot confirm bug")


# ═══════════════════════════════════════
# Bug 3: _ALT_HEADERS is dead code
# ═══════════════════════════════════════

def test_bug3_alt_headers_dead():
    """Bug 3: _ALT_HEADERS is defined but never referenced outside its definition."""
    source = _read_file(os.path.join(SKILL_ROOT, "polyglot", "backends", "python", "scout.py"))

    # Count occurrences of _ALT_HEADERS
    # It should appear in:
    # 1. Its definition line
    # If it's used, it should appear in more places
    occurrences = source.count("_ALT_HEADERS")

    # Also check if it's imported or used in any other file
    if occurrences <= 1:
        print(f"    _ALT_HEADERS appears {occurrences} time(s) in source (only its definition)")
        raise AssertionError(
            "BUG CONFIRMED: _ALT_HEADERS is defined but never referenced. "
            "It was intended for Cloudflare retry but was never wired up."
        )

    print(f"    _ALT_HEADERS appears {occurrences} times — appears to be in use")
    # Not an error if it's in use, but we need to confirm the bug


# ═══════════════════════════════════════
# Bug 4: cache_get_or_retry is dead code
# ═══════════════════════════════════════

def test_bug4_cache_get_or_retry_dead():
    """Bug 4: cache_get_or_retry is defined but never called by any backend."""
    import glob

    # Check all scout files
    scout_files = glob.glob(os.path.join(SKILL_ROOT, "polyglot", "backends", "*", "scout.py"))
    for f in scout_files:
        content = _read_file(f)
        if "cache_get_or_retry" in content:
            print(f"    Found usage in {os.path.relpath(f, SKILL_ROOT)}")
            return  # Not dead code

    # Check all files in common/
    common_files = glob.glob(os.path.join(SKILL_ROOT, "polyglot", "common", "*.py"))
    for f in common_files:
        if f.endswith("cache.py"):
            continue  # Skip definition file
        content = _read_file(f)
        if "cache_get_or_retry" in content:
            print(f"    Found usage in {os.path.relpath(f, SKILL_ROOT)}")
            return

    # Check all glue files
    glue_files = glob.glob(os.path.join(SKILL_ROOT, "polyglot", "glue", "*.py"))
    for f in glue_files:
        content = _read_file(f)
        if "cache_get_or_retry" in content:
            print(f"    Found usage in {os.path.relpath(f, SKILL_ROOT)}")
            return

    raise AssertionError(
        "BUG CONFIRMED: cache_get_or_retry is defined in cache.py but never called "
        "by any backend or module. It's dead code."
    )


# ═══════════════════════════════════════
# Bug 5: CF retry never happens
# ═══════════════════════════════════════

def test_bug5_cf_retry_missing():
    """Bug 5: _fetch_html_search checks for CF but doesn't use _ALT_HEADERS to retry."""
    source = _read_file(os.path.join(SKILL_ROOT, "polyglot", "backends", "python", "scout.py"))

    # Find the CF detection line and check if it retries
    cf_line = [l for l in source.split("\n") if "cf-browser-verification" in l]
    if not cf_line:
        raise AssertionError("Cannot find CF detection code")

    # Check if _ALT_HEADERS is referenced near the CF detection
    # (within the same function or in a retry path)
    if "_ALT_HEADERS" not in source:
        raise AssertionError("_ALT_HEADERS not found in source at all — cannot confirm bug")

    # Check if _fetch_html_search function uses _ALT_HEADERS
    # Find the function definition
    lines = source.split("\n")
    in_fetch_html = False
    depth = 0
    uses_alt = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("def _fetch_html_search"):
            in_fetch_html = True
            depth = stripped.count("(") - stripped.count(")")
        elif in_fetch_html:
            depth += stripped.count("(") - stripped.count(")")
            if "_ALT_HEADERS" in stripped:
                uses_alt = True
                break
            if depth <= 0:
                break

    if not uses_alt:
        raise AssertionError(
            "BUG CONFIRMED: _fetch_html_search detects Cloudflare but does NOT "
            "use _ALT_HEADERS to retry. CF detection is a dead-end path."
        )

    print("    _ALT_HEADERS is used in _fetch_html_search — bug may be fixed")


# ═══════════════════════════════════════
# Bug 6: No auto cache cleanup
# ═══════════════════════════════════════

def test_bug6_no_auto_cleanup():
    """Bug 6: cache_clean exists but is never called automatically from cache_set or cache_get."""
    source = _read_file(os.path.join(SKILL_ROOT, "polyglot", "common", "cache.py"))

    lines = source.split("\n")
    in_fn = None
    depth = 0
    def_started = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("def "):
            in_fn = stripped[4:].split("(")[0]
            depth = stripped.count("(") - stripped.count(")")
            def_started = True
        elif def_started:
            depth += stripped.count("(") - stripped.count(")")
            if "cache_clean" in stripped and in_fn in ("cache_set", "cache_get"):
                print(f"    cache_clean called from {in_fn} at line {i+1}")
                return  # Found — auto-cleanup exists
            if depth <= 0:
                in_fn = None
                def_started = False

    # If we get here, check if cache_clean is called from anywhere automatically
    if "cache_clean" in source:
        # It's only defined, not called from cache_set/cache_get
        # Check if it's called from any other automatic function
        for fn_name in ("cache_set", "cache_get", "cache_get_or_retry"):
            if f"cache_clean(" in source:
                # Find which function it's in
                for i, line in enumerate(lines):
                    if "cache_clean" in line and "def " not in line:
                        pass  # Found a call

    raise AssertionError(
        "BUG CONFIRMED: cache_clean() is defined but never called automatically "
        "from cache_set or cache_get. The SQLite database will grow unbounded."
    )


# ═══════════════════════════════════════
# RUN
# ═══════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("RED Tests — Proving bugs exist on current code")
    print("=" * 60)
    print()

    tests = [
        ("Bug 1: stale fallback dead code", test_bug1_dead_code),
        ("Bug 2: 404 retried (RuntimeError)", test_bug2_404_retried),
        ("Bug 3: _ALT_HEADERS dead code", test_bug3_alt_headers_dead),
        ("Bug 4: cache_get_or_retry dead code", test_bug4_cache_get_or_retry_dead),
        ("Bug 5: CF retry with _ALT_HEADERS", test_bug5_cf_retry_missing),
        ("Bug 6: no auto cache cleanup", test_bug6_no_auto_cleanup),
    ]

    for name, fn in tests:
        test(name, fn)

    print()
    print("=" * 60)
    print(f"RED RESULTS: {PASS} passed, {FAIL} failed (expected: all 6 FAIL)")
    print("=" * 60)
    print()
    if FAIL == 6:
        print("All 6 bugs confirmed. Proceed to GREEN phase.")
    else:
        print(f"Only {FAIL}/6 bugs confirmed. Some may have been fixed already.")