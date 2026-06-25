"""Rust crate installer (cargo add)."""
import sys, os, subprocess

def install(package: str, version: str = "") -> tuple[bool, str]:
    """Add a Rust crate dependency. Returns (success, message)."""
    spec = f"{package}@{version}" if version else package
    try:
        result = subprocess.run(["cargo", "add", spec], capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return True, f"Added {spec}"
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "cargo not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "cargo add timed out"