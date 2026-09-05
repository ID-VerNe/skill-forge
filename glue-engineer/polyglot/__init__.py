# polyglot — multi-language glue engineer toolkit

# Inject the OS certificate trust store before any HTTP happens, so that MITM
# accelerators (Steam++ / SteamTools, etc.) are trusted exactly the same way
# gh / git / browsers already trust them.  Failure here must NEVER brick
# polyglot, hence the guard.
try:
    from polyglot.common.net import ensure_system_trust
    ensure_system_trust()
except Exception:
    pass
