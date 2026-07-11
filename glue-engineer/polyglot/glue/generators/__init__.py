"""
polyglot/glue/generators/__init__.py — Generator dispatcher.

Routes from a GlueSchema to the correct generator based on strategy mode.
Now powered by the PluginRegistry for extensibility.
"""

from polyglot.glue.glue_schema import GlueSchema, GlueOutputPackage, now_iso, SCAFFOLD_DISCLAIMER

# Import all built-in generators to trigger PluginRegistry.register decorators
from polyglot.glue.generators import import_gen       # noqa: F401
from polyglot.glue.generators import subprocess_gen   # noqa: F401
from polyglot.glue.generators import pyo3_gen         # noqa: F401
from polyglot.glue.generators import ffi_gen          # noqa: F401

# Plugin-based dispatch
from polyglot.glue.generators.plugin import PluginRegistry


def _get_generator(mode: str):
    """Get a generator instance by mode name.

    Uses PluginRegistry (supports third-party plugins).
    Falls back to legacy _GENERATORS dict for backward compatibility.
    """
    try:
        return PluginRegistry.get(mode)
    except KeyError:
        raise ValueError(f"Unknown generator mode: '{mode}'. "
                         f"Available: {', '.join(PluginRegistry.list_modes())}")


def generate_glue(schema: GlueSchema, output_dir: str = ".glue/search") -> GlueOutputPackage:
    """Generate glue code from a GlueSchema.

    Routes to the correct generator based on strategy mode.
    Returns a GlueOutputPackage with all generated paths and verification results.
    """
    if not schema.strategy:
        raise ValueError("GlueSchema has no strategy — cannot select generator")

    mode = schema.strategy.mode
    generator = _get_generator(mode)

    package = generator.generate(schema, output_dir)

    # Ensure disclaimer and timestamp are present
    package.disclaimer = SCAFFOLD_DISCLAIMER
    package.generated_at = now_iso()
    return package


def list_generators() -> list[dict]:
    """List available generators with descriptions.

    Uses PluginRegistry for dynamic discovery.
    """
    return [
        {"mode": meta.mode, "description": meta.description}
        for meta in PluginRegistry.list_plugins()
    ]


def discover_plugins(package: str = "polyglot.glue.generators") -> int:
    """Auto-discover generator plugins from a package.

    Scans the given Python package for PluginInterface subclasses
    decorated with @PluginRegistry.register.

    Returns the number of newly discovered plugins.
    """
    return PluginRegistry.discover(package)