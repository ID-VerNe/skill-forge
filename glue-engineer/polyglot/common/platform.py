"""polyglot/common/platform.py — OS detection, venv/path helpers."""

import os
import sys
import subprocess
import shutil


def detect_os() -> str:
    """Returns 'windows', 'macos', or 'linux'."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def venv_python(venv_path: str) -> str:
    """Return the python executable path inside a venv."""
    if detect_os() == "windows":
        return os.path.join(venv_path, "Scripts", "python.exe")
    return os.path.join(venv_path, "bin", "python")


def is_tool_available(name: str) -> bool:
    """Check if CLI tool is in PATH."""
    return shutil.which(name) is not None


def has_npm() -> bool:
    return is_tool_available("npm") or is_tool_available("pnpm") or is_tool_available("yarn")


def has_cargo() -> bool:
    return is_tool_available("cargo")


def has_mvn() -> bool:
    return is_tool_available("mvn") or is_tool_available("gradle")


def has_git() -> bool:
    return is_tool_available("git")


def detect_project_ecosystem(path: str = ".") -> list[dict]:
    """Detect which ecosystems the project at path uses."""
    results = []
    files = os.listdir(path)

    if "pyproject.toml" in files or "requirements.txt" in files or "setup.py" in files:
        results.append({"ecosystem": "python", "confidence": 0.9, "file": "pyproject.toml" if "pyproject.toml" in files else "requirements.txt"})

    if "package.json" in files:
        results.append({"ecosystem": "javascript", "confidence": 0.95, "file": "package.json"})

    if "Cargo.toml" in files:
        results.append({"ecosystem": "rust", "confidence": 0.95, "file": "Cargo.toml"})

    if "pom.xml" in files or "build.gradle" in files or "build.gradle.kts" in files:
        results.append({"ecosystem": "java/kotlin", "confidence": 0.9, "file": "pom.xml" if "pom.xml" in files else "build.gradle"})

    if "CMakeLists.txt" in files or "Makefile" in files or "vcpkg.json" in files:
        results.append({"ecosystem": "c_cpp", "confidence": 0.7, "file": "CMakeLists.txt" if "CMakeLists.txt" in files else "Makefile"})

    return results


def get_registry_for(language: str) -> str:
    registries = {
        "python": "https://pypi.org",
        "javascript": "https://www.npmjs.com",
        "rust": "https://crates.io",
        "java": "https://search.maven.org",
        "kotlin": "https://search.maven.org",
        "c_cpp": "https://vcpkg.io",
    }
    return registries.get(language, "https://github.com")
