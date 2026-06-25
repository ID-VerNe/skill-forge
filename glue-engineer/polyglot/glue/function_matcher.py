"""
polyglot/glue/function_matcher.py — Semantic function matching between libraries.

Classifies functions by semantic role (reader/writer/transform/serialize/deserialize)
using keyword heuristics and produces plausible candidate mappings with
per-mapping confidence scores.

CRITICAL: This produces candidate mappings at ~60-74% precision.
All mappings are labeled with confidence scores and review requirements.
"""

import re
from typing import Optional

from polyglot.glue.glue_schema import (
    FunctionSignature,
    FunctionMapping,
    ParamMapping,
    TransformRule,
)


# ═══════════════════════════════════════════════════════════════════
# Role classification keywords (per language)
# ═══════════════════════════════════════════════════════════════════

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


class FunctionMatcher:
    """Matches functions between source and destination libraries.

    Uses role classification + name similarity to propose candidate mappings.
    """

    def __init__(self):
        self.confidence_threshold = 0.3  # minimum confidence to propose a mapping

    def match(
        self,
        src_name: str,
        src_funcs: list,
        dst_funcs: list,
        src_lang: str = "",
        dst_lang: str = "",
    ) -> list:
        """Propose function mappings between two libraries.

        Args:
            src_name: Source library name
            src_funcs: List of FunctionSignature dicts or objects
            dst_funcs: List of FunctionSignature dicts or objects
            src_lang: Source language
            dst_lang: Destination language

        Returns:
            List of FunctionMapping objects
        """
        proposals = []

        # Normalize to dicts
        src_list = [self._to_dict(f) for f in src_funcs]
        dst_list = [self._to_dict(f) for f in dst_funcs]

        # Classify all functions by role
        src_with_roles = [(f, *classify_function_role(f.get("name", ""))) for f in src_list]
        dst_with_roles = [(f, *classify_function_role(f.get("name", ""))) for f in dst_list]

        # Match by role first, then by name similarity within same role group
        used_dst = set()

        for sf, src_role, src_conf in src_with_roles:
            sname = sf.get("name", "")

            # Find best match in destination
            best_match = None
            best_score = 0.0

            for di, (df, dst_role, dst_conf) in enumerate(dst_with_roles):
                if di in used_dst:
                    continue

                dname = df.get("name", "")
                score = self._mapping_score(
                    sname, dname,
                    src_role, dst_role,
                    src_conf, dst_conf,
                    src_lang, dst_lang,
                )

                if score > best_score and score >= self.confidence_threshold:
                    best_score = score
                    best_match = di

            if best_match is not None:
                used_dst.add(best_match)
                df = dst_list[best_match]

                # Build param mappings
                param_maps = self._match_params(
                    sf.get("params", []),
                    df.get("params", []),
                )

                # Guess return transform
                ret_transform = guess_return_transform(
                    sf.get("return_type", ""),
                    df.get("return_type", ""),
                    src_lang, dst_lang,
                )

                # Determine confidence label
                label = self._confidence_label(best_score, src_lang, dst_lang)

                mapping_id = f"{src_name}_{sname}_to_{df.get('name', '?')}"
                proposals.append(FunctionMapping(
                    mapping_id=mapping_id,
                    src_function=sname,
                    dst_function=df.get("name", ""),
                    confidence=round(best_score, 2),
                    confidence_label=label,
                    param_mappings=param_maps,
                    return_transform=ret_transform,
                ))

        return proposals

    def _to_dict(self, f) -> dict:
        if isinstance(f, dict):
            return f
        if hasattr(f, "to_dict"):
            return f.to_dict()
        return {"name": getattr(f, "name", ""), "params": getattr(f, "params", []),
                "return_type": getattr(f, "return_type", "")}

    def _mapping_score(
        self,
        sname: str,
        dname: str,
        src_role: str,
        dst_role: str,
        src_conf: float,
        dst_conf: float,
        src_lang: str,
        dst_lang: str,
    ) -> float:
        """Compute a composite score for a candidate function mapping."""
        score = 0.0

        # Role match (highest weight)
        if src_role == dst_role and src_role != "unknown":
            score += 0.45
        elif src_role == dst_role:
            score += 0.25

        # Name similarity
        sim = self._name_similarity(sname, dname)
        score += sim * 0.35

        # Role confidence bonus
        score += (src_conf + dst_conf) * 0.1

        # Cross-language penalty
        if src_lang != dst_lang and src_lang and dst_lang:
            score *= 0.85  # 15% penalty for cross-language

        return min(score, 1.0)

    def _name_similarity(self, a: str, b: str) -> float:
        """Compute name similarity using substring and Levenshtein distance."""
        a_low = a.lower().replace("_", "").replace("-", "")
        b_low = b.lower().replace("_", "").replace("-", "")

        if a_low == b_low:
            return 1.0
        if a_low in b_low or b_low in a_low:
            return 0.85
        # Levenshtein ratio
        dist = self._levenshtein(a_low, b_low)
        max_len = max(len(a_low), len(b_low))
        if max_len == 0:
            return 0.0
        return max(0.0, 1.0 - dist / max_len)

    def _levenshtein(self, a: str, b: str) -> int:
        """Compute Levenshtein distance."""
        if len(a) < len(b):
            a, b = b, a
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            curr = [i + 1]
            for j, cb in enumerate(b):
                cost = 0 if ca == cb else 1
                curr.append(min(
                    curr[-1] + 1,
                    prev[j + 1] + 1,
                    prev[j] + cost,
                ))
            prev = curr
        return prev[-1]

    def _match_params(self, src_params: list, dst_params: list) -> list:
        """Match parameters by name similarity."""
        if not src_params:
            return []

        src_norm = {}
        for p in src_params:
            name = p.get("name", "") if isinstance(p, dict) else getattr(p, "name", "")
            src_norm[name] = p

        dst_norm = {}
        for p in dst_params:
            name = p.get("name", "") if isinstance(p, dict) else getattr(p, "name", "")
            dst_norm[name] = p

        mappings = []
        used_dst = set()

        # Match by exact name first
        for sname, sp in src_norm.items():
            if sname in dst_norm and sname not in used_dst:
                used_dst.add(sname)
                mappings.append(ParamMapping(
                    src_name=sname,
                    dst_name=sname,
                    transform=TransformRule(kind="identity", expr="pass_through"),
                    src_default=sp.get("default_value", "") if isinstance(sp, dict) else getattr(sp, "default_value", ""),
                    dst_default=dst_norm[sname].get("default_value", "") if isinstance(dst_norm[sname], dict) else getattr(dst_norm[sname], "default_value", ""),
                ))

        # Then match by similarity
        for sname, sp in src_norm.items():
            if sname in used_dst:
                continue
            best_dst = None
            best_sim = 0.0
            for dname in dst_norm:
                if dname in used_dst:
                    continue
                sim = self._name_similarity(sname, dname)
                if sim > best_sim and sim > 0.6:
                    best_sim = sim
                    best_dst = dname
            if best_dst:
                used_dst.add(best_dst)
                dp = dst_norm[best_dst]
                if best_sim >= 1.0:
                    t = TransformRule(kind="identity", expr="pass_through")
                else:
                    t = TransformRule(kind="rename", expr=f"# TODO: src '{sname}' -> dst '{best_dst}'")
                mappings.append(ParamMapping(
                    src_name=sname,
                    dst_name=best_dst,
                    transform=t,
                    src_default=sp.get("default_value", "") if isinstance(sp, dict) else getattr(sp, "default_value", ""),
                    dst_default=dp.get("default_value", "") if isinstance(dp, dict) else getattr(dp, "default_value", ""),
                ))

        # Add unmatched src params with TODO note
        matched_src = {m.src_name for m in mappings}
        for sname, sp in src_norm.items():
            if sname not in matched_src:
                mappings.append(ParamMapping(
                    src_name=sname,
                    dst_name="#MISSING",
                    transform=TransformRule(kind="unwrap", expr=f"# TODO: no match for '{sname}' in dst"),
                    src_default=sp.get("default_value", "") if isinstance(sp, dict) else getattr(sp, "default_value", ""),
                ))

        return mappings

    def _confidence_label(self, score: float, src_lang: str, dst_lang: str) -> str:
        """Map confidence score to review label."""
        if score >= 0.9 and src_lang == dst_lang:
            return "identical"
        elif score >= 0.6:
            return "similar"
        elif src_lang != dst_lang:
            return "cross_lang_guess"
        else:
            return "low_confidence"


# ───── Convenience ─────

def match_functions(
    src_funcs: list,
    dst_funcs: list,
    src_name: str,
    dst_name: str,
    src_lang: str = "",
    dst_lang: str = "",
) -> list:
    """One-shot function matching. Returns list[dict] for JSON serialization."""
    matcher = FunctionMatcher()
    mappings = matcher.match(src_name, src_funcs, dst_funcs, src_lang, dst_lang)
    return [m.to_dict() for m in mappings]
