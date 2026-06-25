"""C/C++ package installer."""
import sys, os, subprocess, shutil
def install(package: str, version: str = "") -> tuple[bool, str]:
    if shutil.which("vcpkg"):
        spec = f"{package}:x64-windows" if os.name == 'nt' else package
        try:
            result = subprocess.run(["vcpkg", "install", spec], capture_output=True, text=True, timeout=120)
            return (True, f"Installed via vcpkg: {spec}") if result.returncode == 0 else (False, result.stderr.strip())
        except: pass
    print(f"[INFO] To install {package}, use: vcpkg install {package}")
    return (True, f"Instructions shown for {package}")
