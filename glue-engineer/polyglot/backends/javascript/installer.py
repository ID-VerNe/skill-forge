"""JavaScript package installer (npm)."""
import sys, os, subprocess

def install(package: str, version: str = "") -> tuple[bool, str]:
    """Install an npm package. Returns (success, message)."""
    spec = f"{package}@{version}" if version else package
    try:
        result = subprocess.run(["npm", "install", spec], capture_output=True, text=True, timeout=120, cwd=os.getcwd())
        if result.returncode == 0:
            return True, f"Installed {spec}"
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "npm not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "npm install timed out"