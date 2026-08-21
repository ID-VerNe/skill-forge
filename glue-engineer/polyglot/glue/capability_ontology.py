"""
polyglot/glue/capability_ontology.py — Library capability registry + matching.

Provides a structured, machine-readable description per library that enables
real functional matching (unlike FEATURES.json which only describes tooling ops).

This file is a thin re-export layer over the sectioned ontology modules:
  - polyglot.glue.registry_data        STARTER_REGISTRY
  - polyglot.glue.license_compat       LICENSE_COMPAT
  - polyglot.glue.capability_matcher   match_capabilities, _compare_*
"""

from polyglot.glue.capability_types import LibraryCapability, CapabilityAlignment
from polyglot.glue.registry_data import STARTER_REGISTRY
from polyglot.glue.capability_matcher import match_capabilities


class CapabilityRegistry:
    """Registry of library capabilities.

    Provides lookup and matching. Loads from built-in STARTER_REGISTRY
    and can merge additional entries from disk.
    """

    def __init__(self):
        self._entries: dict[str, LibraryCapability] = {}
        self._load_starter()

    def _load_starter(self):
        for key, cap in STARTER_REGISTRY.items():
            self._entries[key] = cap

    def get(self, library: str, language: str) -> LibraryCapability | None:
        """Look up a library's capability by name and language."""
        key = f"{language}:{library}"
        return self._entries.get(key)

    def register(self, cap: LibraryCapability):
        """Register or update a capability entry."""
        key = f"{cap.language}:{cap.library}"
        self._entries[key] = cap

    def save_to_file(self, path: str):
        """Persist registry to JSON file."""
        import json
        data = {}
        for key, cap in self._entries.items():
            data[key] = cap.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_from_file(self, path: str):
        """Load additional entries from a JSON file."""
        import json
        import os
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, d in data.items():
            self._entries[key] = LibraryCapability(**d)

    def list_available(self) -> list[dict]:
        """List all registered libraries (for CLI display)."""
        result = []
        for key, cap in sorted(self._entries.items()):
            result.append({
                "key": key,
                "library": cap.library,
                "language": cap.language,
                "io_patterns": cap.io_patterns,
                "license": cap.license,
            })
        return result

    def match(self, src_cap: LibraryCapability, dst_cap: LibraryCapability) -> CapabilityAlignment:
        """Compute compatibility alignment between two library capabilities."""
        return match_capabilities(src_cap, dst_cap)


# ───── Convenience ─────

def get_registry() -> CapabilityRegistry:
    """Get the global capability registry (singleton)."""
    return CapabilityRegistry()