"""
polyglot/common/proxy_fallback.py — HTTP GET with proxy fallback.

When the environment has HTTP_PROXY / HTTPS_PROXY set (e.g. a local proxy
like 127.0.0.1:7897), requests uses them automatically.  If that proxy is
temporarily unavailable or unreachable, this module retries once without a
proxy before giving up.

Usage:
    from polyglot.common.proxy_fallback import get as proxy_get

    resp, used_no_proxy = proxy_get("https://example.com/api", timeout=10)
    # resp is a normal requests.Response
    # used_no_proxy is True when the first attempt failed and the fallback fired
"""

import requests

from polyglot.common.net import ensure_system_trust  # noqa: F401 — injects OS trust store

_PROXY_RETRYABLE = (
    requests.exceptions.ProxyError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def get(url, *, timeout=10, headers=None, params=None):
    """GET with proxy fallback.

    Returns (response, used_no_proxy: bool).
    On total failure, raises the last exception.
    """
    # First attempt: honour env HTTP_PROXY / HTTPS_PROXY (default requests behaviour)
    try:
        resp = requests.get(url, timeout=timeout, headers=headers, params=params)
        return resp, False
    except _PROXY_RETRYABLE:
        pass

    # Fallback: bypass proxy entirely
    resp = requests.get(
        url,
        timeout=timeout,
        headers=headers,
        params=params,
        proxies={"http": None, "https": None},
    )
    return resp, True