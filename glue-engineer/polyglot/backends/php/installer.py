"""PHP package installer (Composer)."""
import sys, os, subprocess


def install(package: str, version: str = "") -> tuple[bool, str]:
    """Install a Composer package. Returns (success, message)."""
    spec = f"{package}:{version}" if version else package
    try:
        result = subprocess.run(
            ["composer", "require", spec],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=os.getcwd(),
        )
        if result.returncode == 0:
            return True, f"Installed {spec}"
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "composer not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "composer install timed out"