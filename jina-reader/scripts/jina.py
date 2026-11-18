#!/usr/bin/env python3
"""Jina Reader 一键客户端：请求即开工（网关不存在则自动后台拉起）。

用法：
    python jina.py <URL> [--format md|json|html] [--save FILE]
    python jina.py --state
    python jina.py --stop

设计：
- 先探 /health；不通则以 DETACHED_PROCESS 后台启动网关，轮询等待就绪。
- 全程只走 127.0.0.1，显式禁用环境代理。
- 不打印、不记录目标 URL 以外的隐私（URL 本身是用户主动传入）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
GATEWAY = HERE / "jina_gateway.py"
CONFIG = SKILL_DIR / "config" / "endpoints.json"
LOG = SKILL_DIR / "config" / "gateway.log"
BOOT_TIMEOUT = 25

# 彻底禁用环境代理（本机残留代理会拦 127.0.0.1）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _port() -> int:
    env = os.environ.get("JINA_GATEWAY_PORT")
    if env:
        return int(env)
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            return int(json.load(f).get("port", 8767))
    except (OSError, ValueError, json.JSONDecodeError):
        return 8767


def _base(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or _port()}"


def _get(path: str, timeout: float = 5, port: int | None = None):
    req = urllib.request.Request(_base(port) + path, headers={"Accept": "*/*"})
    with _OPENER.open(req, timeout=timeout) as r:
        return r.status, r.read(), r.headers.get("Content-Type", "")


def healthy(port: int | None = None) -> bool:
    try:
        status, _, _ = _get("/health", timeout=2, port=port)
        return status == 200
    except (urllib.error.URLError, OSError):
        return False


def _spawn(port: int) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logf = open(LOG, "a", encoding="utf-8")
    logf.write(f"\n=== gateway start {time.strftime('%F %T')} ===\n")
    logf.flush()
    # Windows 优先用 pythonw，避免自启时闪出控制台窗口
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe"):
        candidate = exe[:-1] + "w.exe"
        if Path(candidate).exists():
            exe = candidate
    cmd = [exe, str(GATEWAY), "--serve", "--config", str(CONFIG),
           "--port", str(port)]
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": logf, "stderr": subprocess.STDOUT,
              "cwd": str(SKILL_DIR), "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen(cmd, **kwargs)
    logf.close()


def ensure() -> None:
    if healthy():
        return
    port = _port()
    if not CONFIG.exists():
        print(f"[jina] config missing: {CONFIG}", file=sys.stderr)
        print("[jina] copy endpoints.example.json -> endpoints.json and fill it",
              file=sys.stderr)
        sys.exit(2)
    print("[jina] gateway down, starting...", file=sys.stderr)
    _spawn(port)
    deadline = time.time() + BOOT_TIMEOUT
    while time.time() < deadline:
        time.sleep(0.4)
        if healthy(port):
            print("[jina] gateway ready", file=sys.stderr)
            return
    print(f"[jina] gateway failed to boot in {BOOT_TIMEOUT}s; see {LOG}",
          file=sys.stderr)
    sys.exit(3)


def _quote_target(url: str) -> str:
    # 作为 path 传输，只编码 ? # 等会破坏路由的字符，保留 :// 可读性
    return urllib.parse.quote(url, safe=":/%?=&+~")


def fetch(url: str, fmt: str) -> tuple[int, bytes, str]:
    path = f"/{_quote_target(url)}?format={fmt}"
    status, body, ctype = _get(path, timeout=120)
    return status, body, ctype


def main():
    ap = argparse.ArgumentParser(description="Jina Reader 一键客户端（请求即开工）")
    ap.add_argument("url", nargs="?", help="target URL")
    ap.add_argument("--format", choices=["md", "json", "html"], default="md")
    ap.add_argument("--save", type=Path, help="write body to file instead of stdout")
    ap.add_argument("--state", action="store_true", help="show endpoint states")
    ap.add_argument("--stop", action="store_true", help="stop background gateway")
    args = ap.parse_args()

    if args.stop:
        subprocess.run([sys.executable, str(GATEWAY), "--stop"],
                       check=False)
        return
    if args.state:
        if not healthy():
            print("gateway not running")
            return
        _, body, _ = _get("/state", timeout=10)
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.write(b"\n")
        return
    if not args.url:
        ap.error("provide a URL, or use --state / --stop")

    ensure()
    try:
        status, body, ctype = fetch(args.url, args.format)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
        print(f"[jina] request failed: {e}", file=sys.stderr)
        sys.exit(4)

    if status != 200:
        sys.stderr.write(body.decode("utf-8", "replace") + "\n")
        sys.exit(1)

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes(body)
        print(f"[jina] saved {len(body)} bytes -> {args.save}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(body)
        if not body.endswith(b"\n"):
            sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
