"""polyglot/deep/license.py — License compatibility helper for reuse decisions.

Provides deterministic license checks for code reuse recommendations.
References the LICENSE_COMPAT matrix in glue/capability_ontology.py where available.
"""

# SPDX identifier → category mapping
# Categories determine compatibility rules:
#   permissive: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, CC0-1.0, Unlicense, ISC
#   weak_copyleft: LGPL-2.1, LGPL-3.0, MPL-2.0
#   strong_copyleft: GPL-2.0, GPL-3.0, AGPL-3.0
#   proprietary: All others

LICENSE_CATEGORIES = {
    # Permissive
    "MIT": "permissive",
    "Apache-2.0": "permissive",
    "BSD-2-Clause": "permissive",
    "BSD-3-Clause": "permissive",
    "CC0-1.0": "permissive",
    "Unlicense": "permissive",
    "ISC": "permissive",
    "MIT-0": "permissive",
    "BSL-1.0": "permissive",
    # Weak copyleft
    "LGPL-2.1": "weak_copyleft",
    "LGPL-2.1-only": "weak_copyleft",
    "LGPL-2.1-or-later": "weak_copyleft",
    "LGPL-3.0": "weak_copyleft",
    "LGPL-3.0-only": "weak_copyleft",
    "LGPL-3.0-or-later": "weak_copyleft",
    "MPL-2.0": "weak_copyleft",
    # Strong copyleft
    "GPL-2.0": "strong_copyleft",
    "GPL-2.0-only": "strong_copyleft",
    "GPL-2.0-or-later": "strong_copyleft",
    "GPL-3.0": "strong_copyleft",
    "GPL-3.0-only": "strong_copyleft",
    "GPL-3.0-or-later": "strong_copyleft",
    "AGPL-3.0": "strong_copyleft",
    "AGPL-3.0-only": "strong_copyleft",
    "AGPL-3.0-or-later": "strong_copyleft",
}

# Deterministic reuse_mode recommendations
# (source_category, target_category) → reuse_mode
_REUSE_RULES = {
    # Permissive → anything: safe to copy
    ("permissive", "permissive"): "copy",
    ("permissive", "weak_copyleft"): "copy",
    ("permissive", "strong_copyleft"): "copy",
    ("permissive", "proprietary"): "copy",
    # Weak copyleft → permissive or weak: port with care
    ("weak_copyleft", "permissive"): "port",
    ("weak_copyleft", "weak_copyleft"): "port",
    # Weak copyleft → strong: safe
    ("weak_copyleft", "strong_copyleft"): "copy",
    ("weak_copyleft", "proprietary"): "reference_only",
    # Strong copyleft → strong: safe but inherits copyleft
    ("strong_copyleft", "strong_copyleft"): "copy",
    # Strong copyleft → permissive or weak: cannot copy
    ("strong_copyleft", "permissive"): "reference_only",
    ("strong_copyleft", "weak_copyleft"): "reference_only",
    ("strong_copyleft", "proprietary"): "avoid",
    # Proprietary → anything: cannot use
    ("proprietary", "permissive"): "avoid",
    ("proprietary", "weak_copyleft"): "avoid",
    ("proprietary", "strong_copyleft"): "avoid",
    ("proprietary", "proprietary"): "avoid",
    # Unknown → anything: cannot assume
    ("unknown", "permissive"): "reference_only",
    ("unknown", "weak_copyleft"): "reference_only",
    ("unknown", "strong_copyleft"): "reference_only",
    ("unknown", "proprietary"): "avoid",
    ("unknown", "unknown"): "reference_only",
}


def get_category(license_id: str) -> str:
    """Get the category of a license.

    Args:
        license_id: SPDX identifier (e.g. "MIT", "GPL-3.0", "")

    Returns:
        One of: "permissive", "weak_copyleft", "strong_copyleft", "proprietary", "unknown"
    """
    if not license_id or license_id.strip() == "":
        return "unknown"
    license_id = license_id.strip()
    return LICENSE_CATEGORIES.get(license_id, "proprietary")


def is_copyleft(license_id: str) -> bool:
    """Check if a license has copyleft provisions."""
    cat = get_category(license_id)
    return cat in ("weak_copyleft", "strong_copyleft")


def is_strong_copyleft(license_id: str) -> bool:
    """Check if a license has strong copyleft (GPL/AGPL)."""
    return get_category(license_id) == "strong_copyleft"


# @lat: [[deep#License Compatibility Engine]]
def reuse_mode_for_license(source_license: str, target_license: str) -> str:
    """Determine the recommended reuse mode based on source and target licenses.

    Args:
        source_license: SPDX identifier of the source code
        target_license: SPDX identifier of the target project

    Returns:
        One of: "copy", "port", "wrap", "reference_only", "avoid"
    """
    src_cat = get_category(source_license)
    dst_cat = get_category(target_license)
    return _REUSE_RULES.get((src_cat, dst_cat), "reference_only")


def is_compatible(source_license: str, target_license: str) -> bool:
    """Check if source license is compatible with target license for direct copying.

    Args:
        source_license: SPDX identifier of the source code
        target_license: SPDX identifier of the target project

    Returns:
        True if direct copying is allowed
    """
    mode = reuse_mode_for_license(source_license, target_license)
    return mode == "copy"


def explain_compatibility(source_license: str, target_license: str) -> str:
    """Generate a human-readable explanation of license compatibility.

    Args:
        source_license: SPDX identifier of the source code
        target_license: SPDX identifier of the target project

    Returns:
        Human-readable explanation string
    """
    src_cat = get_category(source_license)
    dst_cat = get_category(target_license)
    mode = reuse_mode_for_license(source_license, target_license)

    if mode == "copy":
        if src_cat == "permissive":
            return f"Permissive license ({source_license}) — safe to copy into {target_license} project"
        elif src_cat == "weak_copyleft" and dst_cat == "strong_copyleft":
            return f"Weak copyleft ({source_license}) → strong copyleft ({target_license}): compatible"
        elif src_cat == "strong_copyleft":
            return f"Strong copyleft ({source_license}) — can copy but target must be {source_license}"
        else:
            return f"License compatibility: {source_license} → {target_license}"
    elif mode == "port":
        return f"{source_license} (weak copyleft) → {target_license}: Port with care, keep modification notices"
    elif mode == "reference_only":
        if src_cat == "strong_copyleft":
            return f"{source_license} (strong copyleft) cannot be copied into {target_license} project. Study design only."
        return f"{source_license} → {target_license}: Reference only, do not copy directly"
    elif mode == "avoid":
        return f"License conflict: {source_license} → {target_license}. Do NOT reuse this code."
    return f"License compatibility unknown: {source_license} → {target_license}. Exercise caution."