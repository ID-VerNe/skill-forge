# -*- coding: utf-8 -*-
"""polyglot/common/net.py — HTTPS against the OS trust store.

Why this exists
---------------
Steam++/SteamTools (and other MITM accelerators) terminate TLS through their
own root CA that exists *only* in the Windows/macOS system certificate store.
Python's default `requests` stack verifies against a bundled Mozilla CA bundle
(certifi) which does NOT contain those CAs — so every HTTPS call made while the
accelerator is on fails with::

    SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED]
        unable to get local issuer certificate

System cURL (`gh`), browsers, and `git` all already trust the system store, so
they keep working.  This module makes polyglot trust the *same* roots by
injecting a vendored copy of the `truststore` package (pure-python, no C
extensions — safe to ship in the uv-built launcher).

Control
-------
* `POLYGLOT_SYSTEM_TRUST=1` (default) — verify against the OS store.
* `POLYGLOT_SYSTEM_TRUST=0` — fall back to the default certifi bundle.
* If `truststore` fails to import/load, it silently falls back to certifi.

Sources:
    truststore — https://pypi.org/project/truststore/
    vendored under polyglot/vendor/truststore (Apache-2.0)
"""

import os
import sys

_VENDOR_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vendor")
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)


def ensure_system_trust() -> None:
    """Inject the system trust store into ssl/urllib3/requests.

    Safe to call multiple times (idempotent).  Never raises: on any failure we
    keep the default certifi behaviour so the tool still functions.
    """
    if os.environ.get("POLYGLOT_SYSTEM_TRUST", "1") != "1":
        return
    try:
        import truststore  # vendored
        truststore.inject_into_ssl()
    except Exception:
        pass


# Inject at import time so *every* consumer of `common` (or `polyglot.common`)
# gets the patched ssl module before making any request.
ensure_system_trust()
