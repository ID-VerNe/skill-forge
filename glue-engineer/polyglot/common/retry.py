"""polyglot/common/retry.py — Exponential backoff retry with jitter."""

import time
import random
import sys
import os

# Ensure imports work from any call site
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# @lat: [[common#Key Concepts#Retry]]
def retry_call(
    fn,
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    retryable_exceptions=None,
):
    """Call fn() with exponential backoff + jitter on failure.

    Returns (result, attempts, last_error).
      On success:      (result, attempts, None)
      On all-fail:     (None, max_retries+1, last_exception)

    The function is never raised from — all exceptions are caught and
    the last one is returned as last_error.
    """
    if retryable_exceptions is None:
        retryable_exceptions = (Exception,)

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = fn()
            return result, attempt + 1, None
        except retryable_exceptions as e:
            last_error = e
            if attempt < max_retries:
                # 2^attempt: 1, 2, 4, 8... + jitter up to 0.5s
                delay = min(
                    base_delay * (2 ** attempt) + random.uniform(0, 0.5),
                    max_delay,
                )
                time.sleep(delay)

    return None, max_retries + 1, last_error