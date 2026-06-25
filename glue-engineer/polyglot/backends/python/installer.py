"""Python package installer."""
import sys, os, subprocess

def install(package: str, version: str = "", venv: str = "") -> tuple[bool, str]:
    """Install a Python package. Returns (success, message)."""
    python = os.path.join(venv, "Scripts", "python.exe") if venv and os.name == "nt" else (os.path.join(venv, "bin", "python") if venv else sys.executable)
    spec = f"{package}=={version}" if version else package
    try:
        result = subprocess.run([python, "-m", "pip", "install", spec], capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return True, f"Installed {spec}"
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Install timed out"