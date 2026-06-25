"""Dynamic probe for Python package: verify API surface."""
import sys, importlib, inspect, json

PACKAGE = "{package}"
VERSION = "{version}"

try:
    __import__(PACKAGE)
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", f"{PACKAGE}=={VERSION}" if VERSION else PACKAGE])

mod = __import__(PACKAGE)
results = []
for name in dir(mod):
    if name.startswith("_"):
        continue
    obj = getattr(mod, name)
    kind = type(obj).__name__
    try:
        sig = str(inspect.signature(obj)) if callable(obj) else ""
    except (ValueError, TypeError):
        sig = ""
    results.append({
        "symbol": name,
        "resolved": True,
        "return_type": kind,
        "error": "",
        "signature": sig
    })

print(json.dumps({"probed_symbols": results}, indent=2))
