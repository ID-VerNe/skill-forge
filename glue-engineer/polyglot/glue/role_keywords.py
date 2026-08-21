"""
polyglot/glue/role_keywords.py — Semantic role classification keywords.

Classifies functions by semantic role (reader/writer/transform/serialize/
deserialize) using keyword heuristics. Produces candidate roles with
confidence scores.
"""

ROLE_KEYWORDS = {
    "serialize": [
        "dumps", "dump", "encode", "serialize", "to_json", "to_string",
        "to_bytes", "marshal", "pack", "write_json", "jsonify",
    ],
    "deserialize": [
        "loads", "load", "decode", "deserialize", "from_json", "from_string",
        "parse", "unmarshal", "unpack", "read_json",
    ],
    "fetch": [
        "get", "request", "fetch", "download", "read", "query", "select",
        "find", "search", "list", "all", "get_by", "find_by", "first",
    ],
    "send": [
        "post", "put", "patch", "delete", "send", "upload", "write",
        "update", "create", "insert", "save", "store", "submit",
    ],
    "transform": [
        "map", "filter", "reduce", "transform", "convert", "apply",
        "flat_map", "flatten", "sort", "group", "aggregate",
    ],
    "open": [
        "open", "connect", "init", "create", "new", "builder", "build",
        "from_path", "from_file", "from_reader",
    ],
    "close": [
        "close", "disconnect", "shutdown", "stop", "release", "free",
    ],
}


def classify_function_role(name: str) -> tuple[str, float]:
    """Classify a function's semantic role based on its name.

    Returns (role, confidence) where confidence is 0.0-1.0.
    """
    name_lower = name.lower()

    best_role = "unknown"
    best_score = 0.0

    for role, keywords in ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                # Exact match at start/end or after underscore gets higher confidence
                if name_lower == kw:
                    score = 0.95
                elif name_lower.startswith(kw + "_") or name_lower.endswith("_" + kw):
                    score = 0.85
                elif "_" + kw + "_" in name_lower:
                    score = 0.75
                else:
                    score = 0.60  # substring match

                if score > best_score:
                    best_score = score
                    best_role = role

    return best_role, best_score