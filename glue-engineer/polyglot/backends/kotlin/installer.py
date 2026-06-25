"""Kotlin dependency installer."""
import sys, os, subprocess
def install(package: str, version: str = "") -> tuple[bool, str]:
    print(f"[INFO] To install {package}:{version or 'latest'}, add to build.gradle.kts")
    return (True, f"Instructions shown for {package}")
