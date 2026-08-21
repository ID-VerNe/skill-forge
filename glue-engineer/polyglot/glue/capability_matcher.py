"""
polyglot/glue/capability_matcher.py — Library capability matching logic.

Computes compatibility alignment between two library capabilities.
Separate from the registry data and the CapabilityRegistry class.
"""

from polyglot.glue.capability_types import LibraryCapability, CapabilityAlignment
from polyglot.glue.license_compat import LICENSE_COMPAT


WEIGHTS = {
    "io_patterns": 0.25,
    "data_formats": 0.25,
    "error_model": 0.15,
    "data_shape": 0.15,
    "runtime_reqs": 0.10,
    "license": 0.10,
}


def match_capabilities(src: LibraryCapability, dst: LibraryCapability) -> CapabilityAlignment:
    """Compute compatibility alignment between two library capabilities.

    Score = weighted intersection of compatible fields:
    - io_patterns: 0.25 weight
    - data_formats_out -> data_formats_in match: 0.25 weight
    - error_model compatibility: 0.15 weight
    - data_shape_constraints compatibility: 0.15 weight
    - runtime_reqs compatibility: 0.10 weight
    - license_compatibility: 0.10 weight
    """
    alignment = CapabilityAlignment()
    warnings = []

    # ── IO patterns ──
    src_io = set(src.io_patterns)
    dst_io = set(dst.io_patterns)
    io_intersection = src_io & dst_io
    io_union = src_io | dst_io
    io_score = len(io_intersection) / max(len(io_union), 1)
    alignment.io_compatible = io_score >= 0.5
    if not alignment.io_compatible and io_union:
        warnings.append(f"No matching I/O pattern: src={src.io_patterns}, dst={dst.io_patterns}")

    # ── Data formats (out -> in) ──
    src_out = set(src.data_formats_out)
    dst_in = set(dst.data_formats_in)
    format_matches = src_out & dst_in
    format_score = len(format_matches) / max(len(src_out), 1) if src_out else 0.5
    alignment.format_compatible = format_score >= 0.3
    if not alignment.format_compatible and src_out:
        warnings.append(f"Data format mismatch: src outputs {src_out}, dst accepts {dst_in}")

    # ── Error model compatibility ──
    src_errs = {e.get("name", "") if isinstance(e, dict) else str(e) for e in src.error_categories}
    dst_errs = {e.get("name", "") if isinstance(e, dict) else str(e) for e in dst.error_categories}
    err_shared = src_errs & dst_errs
    err_score = len(err_shared) / max(max(len(src_errs), len(dst_errs)), 1)
    alignment.error_model_compatible = err_score >= 0.3 or (not src_errs and not dst_errs)
    if not alignment.error_model_compatible:
        warnings.append("Error model mismatch: incompatible error handling patterns")

    # ── Data shape constraints ──
    shape_score = _compare_shape_constraints(
        src.data_shape_constraints,
        dst.data_shape_constraints,
    )
    alignment.shape_compatible = shape_score >= 0.5
    if not alignment.shape_compatible:
        warnings.append("Data shape constraints differ (nan/infinity handling, etc.)")

    # ── Runtime requirements ──
    runtime_score = _compare_runtime(src.runtime_reqs, dst.runtime_reqs)
    alignment.runtime_compatible = runtime_score >= 0.5
    if not alignment.runtime_compatible:
        warnings.append("Runtime requirements differ (async/sync/threadsafe mismatch)")

    # ── License compatibility ──
    license_compat = LICENSE_COMPAT.get(src.license, {}).get(dst.license, 0.3)
    license_score = license_compat
    if license_score < 0.5:
        warnings.append(f"License mismatch: src={src.license}, dst={dst.license} (score={license_score})")

    # ── Overall score ──
    alignment.overall_score = (
        WEIGHTS["io_patterns"] * io_score +
        WEIGHTS["data_formats"] * format_score +
        WEIGHTS["error_model"] * err_score +
        WEIGHTS["data_shape"] * shape_score +
        WEIGHTS["runtime_reqs"] * runtime_score +
        WEIGHTS["license"] * license_score
    )
    alignment.warnings = warnings
    return alignment


def _compare_shape_constraints(src: dict, dst: dict) -> float:
    """Compare data shape constraints between two capabilities. Returns 0.0-1.0."""
    if not src and not dst:
        return 1.0
    if not src or not dst:
        return 0.3

    total_keys = set(src.keys()) | set(dst.keys())
    if not total_keys:
        return 1.0

    matches = 0
    for key in total_keys:
        s_val = src.get(key)
        d_val = dst.get(key)
        if s_val == d_val:
            matches += 1
        elif s_val is None or d_val is None:
            matches += 0.3  # partial credit

    return matches / len(total_keys)


def _compare_runtime(src: dict, dst: dict) -> float:
    """Compare runtime requirements. Returns 0.0-1.0."""
    if not src and not dst:
        return 1.0
    if not src or not dst:
        return 0.5

    # Check key compatibility fields
    score = 1.0
    penalties = 0

    src_async = src.get("async", False)
    dst_async = dst.get("async", False)
    if src_async and not dst_async:
        penalties += 0.5

    src_st = src.get("threadsafe", True)
    dst_st = dst.get("threadsafe", True)
    if not src_st and dst_st:
        penalties += 0.2
    if src_st and not dst_st:
        penalties += 0.2

    return max(0.0, score - penalties)