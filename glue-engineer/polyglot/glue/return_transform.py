"""
polyglot/glue/return_transform.py — Return-type transform guessing.

Guesses the TransformRule between two functions' return types across
languages using type-name heuristics.
"""

from polyglot.glue.glue_schema import TransformRule


def guess_return_transform(
    src_return: str,
    dst_return: str,
    src_lang: str,
    dst_lang: str,
) -> TransformRule:
    """Guess the return type transform between two functions.

    Rules:
    - Same type and same language -> identity
    - Both string types -> identity
    - str/bytes <-> json -> type_cast (basic)
    - Different languages -> subprocess_json serialization
    - Default -> identity with review note
    """
    src_low = src_return.lower().strip()
    dst_low = dst_return.lower().strip()

    if not src_low and not dst_low:
        return TransformRule(kind="identity", expr="pass_through")
    if src_low == dst_low:
        return TransformRule(kind="identity", expr="pass_through")

    # Both string-like
    str_types = {"str", "string", "&str", "string?", "string!"}
    if src_low in str_types and dst_low in str_types:
        return TransformRule(kind="identity", expr="pass_through")

    # JSON -> JSON is identity (they meet at JSON)
    if "json" in src_low and "json" in dst_low:
        return TransformRule(kind="identity", expr="pass_through")

    # Bytes <-> String
    if src_low in ("bytes", "vec<u8>", "byte[]") and dst_low in ("str", "string"):
        return TransformRule(kind="type_cast", expr=".decode('utf-8')",
                             params={"from": src_return, "to": dst_return})
    if src_low in ("str", "string") and dst_low in ("bytes", "vec<u8>", "byte[]"):
        return TransformRule(kind="type_cast", expr=".encode('utf-8')",
                             params={"from": src_return, "to": dst_return})

    # Cross-language: JSON serialization
    if src_lang != dst_lang:
        return TransformRule(kind="type_cast",
                             expr="json.dumps/loads bridge",
                             params={"strategy": "subprocess_json",
                                     "from": src_return, "to": dst_return})

    # Generic type cast (same language)
    return TransformRule(kind="type_cast",
                         expr=f"# TODO: manual cast from {src_return} to {dst_return}",
                         params={"from": src_return, "to": dst_return})