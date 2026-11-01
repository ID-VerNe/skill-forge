# EVIDENCE — Hidden Bugs Audit

## Summary

Fixed 6 bugs (3 real bugs, 3 code quality issues) in `glue-engineer/polyglot/`.

## Spec (approved orally)

1. **Bug 1** — Python scout dead code: stale fallback after `cache_set+return` is unreachable → **removed dead code**
2. **Bug 2** — 404 retried 3 times: `RuntimeError` in `retryable_exceptions` causes unnecessary retry on 404 → **removed RuntimeError**
3. **Bug 3** — `_ALT_HEADERS` dead code: defined but never used → **wired into CF retry**
4. **Bug 4** — `cache_get_or_retry` dead code: defined but never called → **removed function**
5. **Bug 5** — CF detection has no retry: `_fetch_html_search` bails on CF without trying alternate UA → **added _ALT_HEADERS retry**
6. **Bug 6** — No auto cache cleanup: SQLite DB grows unbounded → **added probabilistic cleanup (~1%) in cache_set**

## Files Changed

| File | Change |
|------|--------|
| `polyglot/common/cache.py` | Removed `cache_get_or_retry`, added `random` import + probabilistic cleanup in `cache_set` |
| `polyglot/backends/python/scout.py` | Removed `RuntimeError` from retryable_exceptions, removed dead stale fallback code, wired `_ALT_HEADERS` into CF retry path, added `random` import |

## GREEN Tests — 6/6 passed

```
GREEN Tests — Verify bug fixes
  [PASS] Bug 1: stale fallback works
  [PASS] Bug 2: 404 no retry
  [PASS] Bug 3: _ALT_HEADERS used
  [PASS] Bug 4: cache_get_or_retry removed
  [PASS] Bug 5: CF retry with _ALT_HEADERS
  [PASS] Bug 6: auto cache cleanup
GREEN RESULTS: 6 passed, 0 failed
```

## Full E2E Suite — 28/28 passed

```
Common Infrastructure: 5/5 passed
Language Scouts: 6/6 passed (live API calls)
CLI Router: 1/1 passed
Python Backend: 1/1 passed
Probe Templates: 1/1 passed
Backend Metadata: 1/1 passed
v3 Glue Infrastructure: 5/5 passed
v3 Generators: 5/5 passed
v3 CLI Commands: 3/3 passed
Total: 28/28 passed, 0 failed
```

## Mutation Testing — 3/3 killed

| Mutation | What it did | Test result |
|----------|-------------|-------------|
| 1. Remove CF retry | Commented out `_ALT_HEADERS` retry in `_fetch_html_search` | **KILLED** — test_bug5 detected it |
| 2. Add RuntimeError back | Put `RuntimeError` back in `retryable_exceptions` | **KILLED** — test_bug2 detected it |
| 3. Remove auto cleanup | Commented out `random.random() < 0.01` block in `cache_set` | **KILLED** — test_bug6 detected it |

## Git State

No commits made. All changes are on working tree.

## Files

- `tests/test_red_bugs.py` — RED tests (prove bugs existed)
- `tests/test_green_bugs.py` — GREEN tests (verify fixes)