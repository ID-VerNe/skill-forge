"""
polyglot/glue/generators/plugin.py — Plugin interface + registry for generators.

Provides:
- `PluginInterface` ABC that all generators must implement
- `GeneratorMetadata` dataclass for plugin metadata
- `PluginRegistry` for discovery and dynamic loading
- Third-party plugin support: any module can register a generator

Usage:
    from polyglot.glue.generators.plugin import PluginInterface, GeneratorMetadata

    @PluginRegistry.register
    class MyGenerator(PluginInterface):
        metadata = GeneratorMetadata(
            mode="custom",
            description="My custom generator",
            source_languages=("python",),
            target_languages=("python",),
        )
        def generate(self, schema, output_dir) -> GlueOutputPackage:
            ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional
import importlib
import pkgutil
import logging

from polyglot.glue.glue_schema import GlueSchema, GlueOutputPackage

logger = logging.getLogger(__name__)


@dataclass
class GeneratorMetadata:
    """Metadata for a generator plugin.

    Fields:
        mode: Strategy mode identifier (e.g. "import", "subprocess_json")
        description: Human-readable description of what this generator does
        source_languages: Tuple of supported source languages (empty = all)
        target_languages: Tuple of supported target languages (empty = all)
        confidence: Confidence tier: "high" | "medium" | "low"
        version: Plugin version string
        license: SPDX license identifier for the plugin code itself
    """
    mode: str
    description: str
    source_languages: tuple[str, ...] = ()
    target_languages: tuple[str, ...] = ()
    confidence: str = "medium"
    version: str = "1.0.0"
    license: str = "MIT"


class PluginInterface(ABC):
    """Abstract base class for all generator plugins.

    Every generator must:
    1. Inherit from PluginInterface
    2. Set a `metadata` ClassVar of type GeneratorMetadata
    3. Implement `generate()`
    4. Decorate with @PluginRegistry.register (or register manually)

    Example:
        @PluginRegistry.register
        class MyGen(PluginInterface):
            metadata = GeneratorMetadata(mode="my_mode", description="...")

            def generate(self, schema, output_dir):
                ...
    """

    metadata: ClassVar[GeneratorMetadata]

    @abstractmethod
    def generate(self, schema: GlueSchema, output_dir: str = "glue-outputs") -> GlueOutputPackage:
        """Generate glue code from a GlueSchema.

        Args:
            schema: The GlueSchema describing the bridge to generate.
            output_dir: Root output directory.

        Returns:
            GlueOutputPackage with paths to all generated files.
        """
        ...

    def get_metadata(self) -> GeneratorMetadata:
        """Return this plugin's metadata (class-level)."""
        return self.metadata


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class PluginRegistry:
    """Registry for generator plugins.

    Supports:
    - Decorator registration: @PluginRegistry.register
    - Manual registration: PluginRegistry.register(MyGen)
    - Discovery: PluginRegistry.discover("polyglot.glue.generators")
    - Lookup: PluginRegistry.get("import") -> ImportGenerator
    - Listing: PluginRegistry.list_plugins() -> [GeneratorMetadata, ...]
    """

    _registry: dict[str, type[PluginInterface]] = {}
    _instance_cache: dict[str, PluginInterface] = {}

    @classmethod
    def register(cls, plugin_cls: type[PluginInterface]) -> type[PluginInterface]:
        """Register a generator plugin class.

        Can be used as a decorator:
            @PluginRegistry.register
            class MyGen(PluginInterface): ...

        Or called directly:
            PluginRegistry.register(MyGen)
        """
        if not issubclass(plugin_cls, PluginInterface):
            raise TypeError(f"{plugin_cls.__name__} must inherit from PluginInterface")

        meta: GeneratorMetadata = getattr(plugin_cls, "metadata", None)
        if meta is None:
            raise AttributeError(
                f"{plugin_cls.__name__} must define a 'metadata' ClassVar of type GeneratorMetadata"
            )
        if not isinstance(meta, GeneratorMetadata):
            raise TypeError(
                f"{plugin_cls.__name__}.metadata must be a GeneratorMetadata instance"
            )

        mode = meta.mode
        if mode in cls._registry:
            logger.warning(
                f"Overwriting existing generator for mode '{mode}': "
                f"{cls._registry[mode].__name__} -> {plugin_cls.__name__}"
            )

        cls._registry[mode] = plugin_cls
        cls._instance_cache.pop(mode, None)  # Clear cached instance
        logger.debug(f"Registered generator plugin: {mode} -> {plugin_cls.__name__}")
        return plugin_cls

    @classmethod
    def get(cls, mode: str) -> PluginInterface:
        """Get an instance of the generator for the given mode.

        Instances are cached once created.
        Raises KeyError if no generator is registered for this mode.
        """
        if mode in cls._instance_cache:
            return cls._instance_cache[mode]

        plugin_cls = cls._registry.get(mode)
        if plugin_cls is None:
            raise KeyError(f"No generator registered for mode: '{mode}'. "
                           f"Available modes: {', '.join(cls._registry.keys()) or '(none)'}")

        instance = plugin_cls()
        cls._instance_cache[mode] = instance
        return instance

    @classmethod
    def list_plugins(cls) -> list[GeneratorMetadata]:
        """List metadata for all registered plugins."""
        return [
            plugin_cls.metadata
            for plugin_cls in cls._registry.values()
        ]

    @classmethod
    def list_modes(cls) -> list[str]:
        """List all registered mode names."""
        return list(cls._registry.keys())

    @classmethod
    def discover(cls, package: str = "polyglot.glue.generators") -> int:
        """Auto-discover generator plugins by scanning a package.

        Iterates over all modules in the given package, importing each one.
        Modules that define PluginInterface subclasses with @PluginRegistry.register
        will be picked up automatically.

        Args:
            package: Dotted package name to scan.

        Returns:
            Number of plugins discovered (newly loaded).

        Note:
            Already-loaded plugins are not double-counted.
        """
        try:
            pkg = importlib.import_module(package)
        except ImportError:
            logger.warning(f"Cannot import package '{package}' for plugin discovery")
            return 0

        count_before = len(cls._registry)

        for importer, modname, is_pkg in pkgutil.iter_modules(pkg.__path__):
            full_name = f"{package}.{modname}"
            try:
                importlib.import_module(full_name)
                logger.debug(f"Discovered plugin module: {full_name}")
            except Exception as e:
                logger.warning(f"Failed to load plugin module '{full_name}': {e}")

        return len(cls._registry) - count_before

    @classmethod
    def reset(cls) -> None:
        """Clear all registered plugins and cached instances.

        Primarily used for testing.
        """
        cls._registry.clear()
        cls._instance_cache.clear()

    @classmethod
    def get_instance_for(cls, schema: GlueSchema) -> PluginInterface:
        """Resolve the correct generator for a schema's strategy mode.

        Args:
            schema: GlueSchema with strategy.mode set.

        Returns:
            PluginInterface instance.

        Raises:
            ValueError if schema has no strategy or mode is unknown.
        """
        if not schema.strategy:
            raise ValueError("GlueSchema has no strategy — cannot select generator")
        mode = schema.strategy.mode
        try:
            return cls.get(mode)
        except KeyError:
            raise ValueError(
                f"Unknown generator mode: '{mode}'. "
                f"Available: {', '.join(cls._registry.keys()) or '(none)'}. "
                f"Did you register a plugin for this mode?"
            )


# ---------------------------------------------------------------------------
# Decorator alias for convenience
# ---------------------------------------------------------------------------

register = PluginRegistry.register