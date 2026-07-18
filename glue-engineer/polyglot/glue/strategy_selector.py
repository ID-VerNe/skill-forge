"""
polyglot/glue/strategy_selector.py — Bridge strategy selection for library pairs.

Determines the mechanical bridge strategy based on language pair and available tools.
"""

from polyglot.glue.glue_schema import (
    GlueStrategy,
    LibraryEndpoint,
    FunctionSignature,
    CapabilityAlignment,
)


STRATEGY_RULES = {
    # (src_lang, dst_lang) -> (mode, bridge_lang, host_framework, system_tools)
    ("python", "python"):       ("import", "python", "", []),
    ("python", "javascript"):   ("subprocess_json", "python", "", ["node"]),
    ("python", "rust"):         ("subprocess_json", "python", "", []),
    ("python", "java"):         ("subprocess_json", "python", "", ["java"]),
    ("python", "kotlin"):       ("subprocess_json", "python", "", ["kotlin"]),
    ("python", "c_cpp"):        ("ffi_cffi", "python", "cffi", ["gcc"]),

    ("javascript", "javascript"): ("import", "javascript", "", []),
    ("javascript", "python"):     ("subprocess_json", "javascript", "", []),
    ("javascript", "rust"):       ("subprocess_json", "javascript", "", []),
    ("javascript", "java"):       ("subprocess_json", "javascript", "", ["java"]),
    ("javascript", "kotlin"):     ("subprocess_json", "javascript", "", ["kotlin"]),
    ("javascript", "c_cpp"):      ("subprocess_json", "javascript", "", ["gcc"]),

    ("rust", "rust"):           ("import", "rust", "", ["cargo"]),
    ("rust", "python"):         ("pyo3", "python", "pyo3", ["cargo"]),
    ("rust", "javascript"):     ("subprocess_json", "rust", "", ["node"]),
    ("rust", "java"):           ("subprocess_json", "rust", "", ["java"]),
    ("rust", "kotlin"):         ("subprocess_json", "rust", "", ["kotlin"]),
    ("rust", "c_cpp"):          ("subprocess_json", "rust", "", ["gcc"]),

    ("java", "java"):           ("import", "java", "", ["java"]),
    ("java", "kotlin"):         ("import", "java", "", []),  # JVM interop
    ("java", "python"):         ("subprocess_json", "java", "", []),
    ("java", "javascript"):     ("subprocess_json", "java", "", ["node"]),
    ("java", "rust"):           ("subprocess_json", "java", "", ["cargo"]),
    ("java", "c_cpp"):          ("subprocess_json", "java", "", ["gcc"]),

    ("kotlin", "kotlin"):       ("import", "kotlin", "", []),
    ("kotlin", "java"):         ("import", "kotlin", "", []),  # JVM interop
    ("kotlin", "python"):       ("subprocess_json", "kotlin", "", []),
    ("kotlin", "javascript"):   ("subprocess_json", "kotlin", "", ["node"]),
    ("kotlin", "rust"):         ("subprocess_json", "kotlin", "", ["cargo"]),
    ("kotlin", "c_cpp"):        ("subprocess_json", "kotlin", "", ["gcc"]),

    ("c_cpp", "c_cpp"):         ("import", "c_cpp", "", ["gcc"]),
    ("c_cpp", "python"):        ("ffi_cffi", "python", "cffi", ["gcc"]),
    ("c_cpp", "javascript"):    ("subprocess_json", "c_cpp", "", ["emcc"]),
    ("c_cpp", "rust"):          ("subprocess_json", "c_cpp", "", ["cargo"]),
    ("c_cpp", "java"):          ("subprocess_json", "c_cpp", "", ["java"]),
    ("c_cpp", "kotlin"):        ("subprocess_json", "c_cpp", "", ["kotlin"]),
}


# @lat: [[glue#Strategy Selector]]
def select_strategy(
    src: LibraryEndpoint,
    dst: LibraryEndpoint,
    alignment: CapabilityAlignment = None,
) -> GlueStrategy:
    """Select the best bridge strategy for a library pair.

    Uses the STRATEGY_RULES lookup table. Falls back to subprocess_json
    for unknown language pairs.
    """
    key = (src.language, dst.language)

    if key in STRATEGY_RULES:
        mode, bridge_lang, framework, tools = STRATEGY_RULES[key]
        rationale = f"Best bridge strategy for {key[0]} -> {key[1]}"
    else:
        # Fallback: subprocess/JSON is universal
        mode = "subprocess_json"
        bridge_lang = src.language
        framework = ""
        tools = []
        rationale = f"Fallback strategy for unregistered pair {key[0]} -> {key[1]}"

    # For same-language import mode with low alignment, add docker as fallback
    docker_supported = mode == "subprocess_json"

    return GlueStrategy(
        mode=mode,
        bridge_lang=bridge_lang,
        host_framework=framework,
        required_system_tools=tools,
        docker_supported=docker_supported,
        rationale=rationale,
    )


def list_available_strategies() -> list[dict]:
    """List all registered strategy rules (for CLI display)."""
    result = []
    for (src_lang, dst_lang), (mode, bridge_lang, framework, tools) in sorted(STRATEGY_RULES.items()):
        result.append({
            "from": src_lang,
            "to": dst_lang,
            "mode": mode,
            "bridge_lang": bridge_lang,
            "framework": framework,
            "tools": tools,
        })
    return result
