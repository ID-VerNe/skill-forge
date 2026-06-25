"""Java/Maven dependency installer."""
import sys, os, subprocess
def install(package: str, version: str = "") -> tuple[bool, str]:
    """Add to pom.xml or build.gradle. For now: show instructions."""
    print(f"[INFO] To install {package}:{version or 'latest'}, add to pom.xml or build.gradle")
    return (True, f"Instructions shown for {package}")
