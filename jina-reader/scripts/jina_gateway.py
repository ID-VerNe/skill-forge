#!/usr/bin/env python3
"""Jina Reader 匿名多出口轮询网关（服务端）。

设计要点：
- 端点从 config/endpoints.json 读取；该文件被 gitignore，仓库只留占位符模板。
- 日志只记状态码 / 出口名 / 耗时，不记目标 URL（隐私）。
- 匿名调用：按 IP 限流 20 RPM，无 token 池上限；换 IP 才增量。

用法：
    python jina_gateway.py --serve [--config PATH] [--port N]
    python jina_gateway.py --stop
    python jina_gateway.py --state
"""

from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
DEFAULT_CONFIG = SKILL_DIR / "config" / "endpoints.json"
PID_FILE = SKILL_DIR / "config" / "gateway.pid"
WINDOW = 60
COOLDOWN = 62
MARKER = "__JINA_STATUS__"
STATUS_FMT = "\n" + MARKER + "%{http_code}"


# ----------------------------- config -----------------------------

def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    eps = cfg.get("endpoints")
    if not isinstance(eps, list) or not eps:
        raise ValueError("config.endpoints must be a non-empty list")
    for e in eps:
        for key in ("name", "mode", "domain"):
            if not e.get(key):
                raise ValueError(f"endpoint missing '{key}': {e.get('name', '?')}")
        if e["mode"] not in ("direct", "ssh"):
            raise ValueError(f"bad mode for {e['name']}: {e['mode']}")
        if e["mode"] == "ssh" and not e.get("alias"):
            raise ValueError(f"ssh endpoint {e['name']} missing 'alias'")
        if "<" in str(e.get("alias", "")) or "<" in str(e["domain"]):
            raise ValueError("placeholder values left in config; fill local config")
    return cfg


# ----------------------------- endpoint ----------------------------

@dataclass
class Endpoint:
    name: str
    domain: str
    alias: Optional[str]
    cooldown_until: float = 0.0
    remaining: int = 20
    successes: int = 0
    failures: int = 0
    last_status: int = 0
    history: deque = field(default_factory=lambda: deque(maxlen=200))

    def available(self, now: float) -> bool:
        return now >= self.cooldown_until and self.remaining > 0

    def retry_after(self, now: float) -> float:
        return max(0.0, self.cooldown_until - now)


def _base_curl(target: str, domain: str, fmt: str) -> list[str]:
    url = f"https://{domain}/{target}"
    cmd = ["curl", "-sS", "-m", "60", "-D", "-", "-o", "-", "-w", STATUS_FMT]
    if fmt == "json":
        cmd += ["-H", "Accept: application/json"]
    elif fmt == "html":
        cmd += ["-H", "X-Return-Format: html"]
    return cmd + ["--noproxy", "*", url]


def _direct_cmd(target: str, domain: str, fmt: str) -> list[str]:
    """本机直连：显式清代理 + --noproxy，确保出口与代理分离。"""
    return _base_curl(target, domain, fmt)


def _ssh_cmd(target: str, domain: str, alias: str, fmt: str) -> list[str]:
    """远端 curl：target 用 base64 传参，避免多层 shell 注入。"""
    encoded = base64.urlsafe_b64encode(target.encode()).decode()
    extra = ""
    if fmt == "json":
        extra = " -H 'Accept: application/json'"
    elif fmt == "html":
        extra = " -H 'X-Return-Format: html'"
    remote = (
        f"U=$(printf %s {shlex.quote(encoded)} | base64 -d); "
        f"curl -sS -m 60 -D - -o - -w {shlex.quote(STATUS_FMT)}{extra} "
        f"\"https://{domain}/$U\""
    )
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
            "-o", "StrictHostKeyChecking=accept-new", alias, remote]


def _clean_env() -> dict:
    env = os.environ.copy()
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(k, None)
    return env


def _parse(raw: str) -> tuple[int, dict, str]:
    pos = raw.rfind(MARKER)
    if pos == -1:
        return 0, {}, raw
    body_blob, status_s = raw[:pos], raw[pos + len(MARKER):].strip()
    try:
        status = int(status_s)
    except ValueError:
        status = 0

    headers: dict[str, str] = {}
    body = body_blob
    sep, width = body_blob.find("\r\n\r\n"), 4
    if sep == -1:
        sep, width = body_blob.find("\n\n"), 2
    if sep != -1:
        head, body = body_blob[:sep], body_blob[sep + width:]
        for line in head.replace("\r", "").split("\n")[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
    return status, headers, body


class Router:
    def __init__(self, cfg: dict):
        self.eps = [Endpoint(e["name"], e["domain"],
                             None if e["mode"] == "direct" else e["alias"])
                    for e in cfg["endpoints"]]
        self.cursor = 0
        self.lock = threading.Lock()

    def _call(self, ep: Endpoint, target: str, fmt: str) -> tuple[int, dict, str]:
        cmd = (_direct_cmd(target, ep.domain, fmt) if ep.alias is None
               else _ssh_cmd(target, ep.domain, ep.alias, fmt))
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               env=_clean_env(), timeout=90)
        except subprocess.TimeoutExpired:
            return 0, {}, "timeout"
        if p.returncode != 0 and not p.stdout:
            return 0, {}, (p.stderr or "transport failed").strip()[:200]
        return _parse(p.stdout)

    def fetch(self, target: str, fmt: str = "md") -> tuple[int, dict, str, str]:
        """返回 (status, headers, body, endpoint_name)。"""
        if not target.startswith(("http://", "https://")):
            return 400, {}, "target must be an http(s) URL", "none"

        deadline = time.time() + 75
        while time.time() < deadline:
            now = time.time()
            with self.lock:
                candidates = [e for e in self.eps if e.available(now)]
                if not candidates:
                    wait = min(e.retry_after(now) for e in self.eps)
                    chosen = None
                else:
                    start = self.cursor % len(candidates)
                    chosen = candidates[start]
                    self.cursor = (start + 1) % len(candidates)

            if chosen is None:
                time.sleep(min(max(wait, 0.1), 5.0))
                continue

            status, headers, body = self._call(chosen, target, fmt)
            with self.lock:
                chosen.last_status = status
                chosen.history.append({"t": round(time.time()), "status": status})
                rem = headers.get("x-ratelimit-remaining")
                if rem is not None:
                    try:
                        chosen.remaining = int(rem.split(",")[0].split(";")[0].strip())
                    except ValueError:
                        pass
                if status == 200:
                    chosen.successes += 1
                else:
                    chosen.failures += 1
                if status == 429:
                    chosen.remaining = 0
                    chosen.cooldown_until = time.time() + COOLDOWN
                elif chosen.remaining <= 0:
                    chosen.cooldown_until = time.time() + COOLDOWN
                elif status == 0:
                    chosen.cooldown_until = time.time() + 5

            if status == 200:
                return 200, headers, body, chosen.name

        return 429, {}, "all endpoints cooling down", "none"

    def state(self) -> dict:
        now = time.time()
        with self.lock:
            return {
                "endpoints": [
                    {"name": e.name, "domain": e.domain,
                     "via": "direct" if e.alias is None else "ssh",
                     "remaining": e.remaining,
                     "cooldown_sec": round(e.retry_after(now), 1),
                     "available": e.available(now),
                     "successes": e.successes, "failures": e.failures,
                     "last_status": e.last_status}
                    for e in self.eps
                ],
                "cursor": self.cursor,
            }


# ----------------------------- http -------------------------------

def make_handler(router: Router):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # BaseHTTPRequestHandler: fmt='"%s" %s %s', args=(request_line, code, size)
            # 只记方法与状态码，绝不记 path/query（目标 URL 属隐私）
            req = str(args[0]) if args else ""
            method = req.split()[0] if req.split() else "REQ"
            code = str(args[1]) if len(args) > 1 else "-"
            sys.stderr.write(f"[http] {method} {code}\n")

        def _reply(self, status: int, payload: bytes, ctype: str):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _handle(self, target: str, fmt: str):
            status, _, body, ep = router.fetch(target, fmt)
            ctype = {"json": "application/json", "html": "text/html"}.get(
                fmt, "text/markdown") + "; charset=utf-8"
            self._reply(status, body.encode("utf-8", "replace"), ctype)
            sys.stderr.write(f"[ok] endpoint={ep} status={status}\n")

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") == "/health":
                self._reply(200, b'{"ok":true}', "application/json")
                return
            if parsed.path.rstrip("/") == "/state":
                self._reply(200, json.dumps(router.state(), ensure_ascii=False,
                                            indent=2).encode(),
                            "application/json; charset=utf-8")
                return
            qs = parse_qs(parsed.query)
            target = qs.get("url", [None])[0]
            fmt = qs.get("format", ["md"])[0]
            if not target:
                raw = unquote(parsed.path).lstrip("/")
                if raw.startswith(("http://", "https://")):
                    target = raw
            if not target:
                self._reply(400, b"missing target url", "text/plain; charset=utf-8")
                return
            self._handle(target, fmt if fmt in ("md", "json", "html") else "md")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", "replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {}
            target = data.get("url") or data.get("target") or ""
            fmt = data.get("format", "md")
            if not target:
                self._reply(400, b'{"error":"missing url"}', "application/json")
                return
            self._handle(target, fmt if fmt in ("md", "json", "html") else "md")

    return Handler


# ----------------------------- main -------------------------------

def write_pid():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")


def remove_pid():
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--state", action="store_true")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--port", type=int, default=None,
                    help="override config port (or env JINA_GATEWAY_PORT)")
    args = ap.parse_args()

    if args.stop:
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text(encoding="ascii").strip())
                if os.name == "nt":
                    # os.kill(pid, SIGTERM) 在 Windows 上不支持（WinError 87）
                    subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, check=False)
                else:
                    os.kill(pid, signal.SIGTERM)
                print(f"stopped pid {pid}")
            except (ValueError, ProcessLookupError, PermissionError) as e:
                print(f"stop failed: {e}")
            remove_pid()
        else:
            print("no pid file; nothing to stop")
        return

    if not args.config.exists():
        print(f"config not found: {args.config}", file=sys.stderr)
        print("copy config/endpoints.example.json -> config/endpoints.json and fill it",
              file=sys.stderr)
        sys.exit(2)

    cfg = load_config(args.config)
    port = args.port or int(os.environ.get(
        "JINA_GATEWAY_PORT", cfg.get("port", 8767)))

    if args.state:
        # 由客户端通过 HTTP /state 查询，这里仅提示
        print(f"gateway config={args.config} port={port}")
        return

    if not args.serve:
        ap.error("use --serve / --stop / --state")

    router = Router(cfg)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(router))
    write_pid()
    print(f"listening http://127.0.0.1:{port} with {len(router.eps)} endpoints",
          file=sys.stderr)
    atexit_register(remove_pid)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        remove_pid()


def atexit_register(fn):
    import atexit
    atexit.register(fn)


if __name__ == "__main__":
    main()
