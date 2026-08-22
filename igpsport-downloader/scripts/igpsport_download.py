#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iGPSPORT 路书下载器

输入 iGPSPORT 路书编号，自动：
  1. 登录获取 token（带本地缓存，token 未过期则复用，减少登录调用）
  2. 按编号搜索路书
  3. 拉取航点数据
  4. 生成 GPX 文件（可直接导入 OsmAnd/Garmin/两步路等地图软件）

用法:
  python igpsport_download.py --route 123456 --email xxx@x.com --password xxx
  python igpsport_download.py --search "路线名" --email xxx@x.com --password xxx

接口说明（逆向自 app.igpsport.com 网页版，2026-08 验证）:
  POST /service/auth/account/login                           登录，明文 JSON，返回 Bearer token + 过期时间
  GET  /service/web/api/Routes/RouteListForWeb?type=find&key  按编号/关键词搜索路书
  GET  /service/web/api/Routes/DetailsRoutesWeb?routeId=     路书详情（含航点）
"""
import argparse
import base64
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import requests

# iGPSPORT 国际站 API 基础地址。国内连 .com 超时可换 https://prod.zh.igpsport.com
DEFAULT_API_BASE = "https://prod.en.igpsport.com"
APP_ID = "igpsport-web"

# 默认输出目录 = 调用方的当前工作目录（Claude Code / 终端启动位置）
DEFAULT_OUTDIR = os.getcwd()

# token 缓存目录：用户级，跨工作目录复用，避免每次换 cwd 都重新登录
TOKEN_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "igpsport")
# 提前量：token 离过期还剩这么多秒就视为过期，避免临界态请求被打回 401
TOKEN_EXPIRY_MARGIN = 60


class IGPSPORTError(Exception):
    pass


def _b64url_decode(data: str) -> bytes:
    """JWT base64url 解码（自动补 padding）。"""
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _jwt_exp(token: str):
    """从 JWT 的 exp claim 提取过期时间（Unix 秒）。解析失败返回 None。"""
    try:
        payload = token.split(".")[1]
        claims = json.loads(_b64url_decode(payload))
        return claims.get("exp")
    except Exception:
        return None


def _token_cache_path(api_base: str, email: str) -> str:
    """同一 (api, email) 的 token 缓存文件路径。"""
    safe_host = api_base.replace("https://", "").replace("/", "_")
    safe_user = "".join(c if c.isalnum() or c in "-_." else "_" for c in email)
    return os.path.join(TOKEN_CACHE_DIR, f"{safe_host}__{safe_user}.json")


def load_cached_token(api_base: str, email: str):
    """读缓存 token。有效（未过期）返回 (token, exp)，否则返回 None。"""
    path = _token_cache_path(api_base, email)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        token = rec.get("token")
        exp = rec.get("exp") or _jwt_exp(token)
        if not token or not exp:
            return None
        if exp - time.time() > TOKEN_EXPIRY_MARGIN:
            return token, exp
        return None
    except Exception:
        return None


def save_cached_token(api_base: str, email: str, token: str) -> None:
    """落盘 token（600 权限，仅本用户可读）。"""
    os.makedirs(TOKEN_CACHE_DIR, exist_ok=True)
    exp = _jwt_exp(token)
    rec = {"token": token, "exp": exp, "api": api_base, "email": email}
    path = _token_cache_path(api_base, email)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def login(base: str, email: str, password: str) -> str:
    """登录，返回 access_token。"""
    url = f"{base}/service/auth/account/login"
    payload = {"appId": APP_ID, "username": email, "password": password}
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise IGPSPORTError(f"登录失败: {data.get('message') or data}")
    return data["data"].get("access_token") or data["data"].get("token")


def get_token(base: str, email: str, password: str) -> str:
    """优先复用未过期缓存 token；失效或无缓存才登录。"""
    cached = load_cached_token(base, email)
    if cached:
        token, exp = cached
        print(f"[1/3] 复用缓存 token（至 {time.strftime('%Y-%m-%d %H:%M', time.localtime(exp))}）")
        return token
    print("[1/3] 登录...")
    token = login(base, email, password)
    save_cached_token(base, email, token)
    print("      OK")
    return token


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def search_route(base: str, token: str, keyword: str, page: int = 1, size: int = 20) -> list:
    """按编号或关键词搜索路书。"""
    url = f"{base}/service/web/api/Routes/RouteListForWeb"
    params = {"pageIndex": page, "pageSize": size, "type": "find", "key": keyword}
    resp = requests.get(url, params=params, headers=_h(token), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise IGPSPORTError(f"搜索失败: {data.get('message') or data}")
    items = (data.get("data") or {}).get("items") or []
    return [
        {
            "id": it.get("roadBookId"),
            "title": it.get("title"),
            "nickName": it.get("nickName"),
            "cityName": it.get("cityName"),
            "distance": it.get("distance"),
            "totalAscent": it.get("totalAscent"),
        }
        for it in items
    ]


def route_detail(base: str, token: str, route_id: int) -> dict:
    """拉取路书详情，含 tracks（航点列表）。"""
    url = f"{base}/service/web/api/Routes/DetailsRoutesWeb"
    resp = requests.get(url, params={"routeId": route_id}, headers=_h(token), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise IGPSPORTError(f"路书拉取失败: {data.get('message') or data}")
    d = data.get("data") or {}
    route_info = d.get("routeInfo") or {}
    summary = d.get("summary") or {}
    return {
        "id": route_id,
        "title": summary.get("title") or f"route-{route_id}",
        "nickName": summary.get("nickName"),
        "cityName": summary.get("region"),
        "distance": summary.get("distance"),
        "totalAscent": summary.get("totalAscent"),
        "startPoint": route_info.get("startPoint"),
        "endPoint": route_info.get("endPoint"),
        "tracks": route_info.get("tracks") or [],
    }


def to_gpx(route: dict) -> str:
    """组装成 GPX 1.1 字符串。"""
    gpx = ET.Element(
        "gpx",
        version="1.1",
        creator="igpsport-downloader",
        xmlns="http://www.topografix.com/GPX/1/1",
    )
    md = ET.SubElement(gpx, "metadata")
    ET.SubElement(md, "name").text = route["title"]

    for tag, pt in (("start", route.get("startPoint")), ("end", route.get("endPoint"))):
        if pt and pt.get("latitude") is not None:
            wpt = ET.SubElement(gpx, "wpt",
                                lat=str(pt["latitude"]), lon=str(pt["longitute"]))
            ET.SubElement(wpt, "name").text = tag
            ET.SubElement(wpt, "desc").text = pt.get("descr", "")

    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = route["title"]
    seg = ET.SubElement(trk, "trkseg")
    for t in route["tracks"]:
        pt = ET.SubElement(seg, "trkpt",
                           lat=f"{t['latitude']:.8f}", lon=f"{t['longitute']:.8f}")
        if t.get("alt") is not None:
            ET.SubElement(pt, "ele").text = f"{t['alt']:.1f}"

    ET.indent(gpx, space="  ")
    return ET.tostring(gpx, encoding="unicode", xml_declaration=True)


def main():
    p = argparse.ArgumentParser(description="iGPSPORT 路书下载器")
    p.add_argument("--route", type=int, help="路书编号（精确下载）")
    p.add_argument("--search", help="按关键词搜索路书")
    p.add_argument("--email", required=True, help="iGPSPORT 账号邮箱")
    p.add_argument("--password", required=True, help="iGPSPORT 密码")
    p.add_argument("--api", default=DEFAULT_API_BASE, help="API 地址")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR, help="输出目录，默认当前工作目录")
    p.add_argument("--clear-token", action="store_true", help="清除该账号的缓存 token 后退出（用于切换账号/强制重新登录）")
    args = p.parse_args()

    if args.clear_token:
        path = _token_cache_path(args.api, args.email)
        if os.path.exists(path):
            os.remove(path)
            print(f"已清除缓存: {path}")
        else:
            print("无缓存可清")
        return 0

    if not args.route and not args.search:
        p.error("必须指定 --route 或 --search")

    base = args.api
    try:
        token = get_token(base, args.email, args.password)

        targets = []
        if args.route:
            found = search_route(base, token, str(args.route))
            match = [r for r in found if r["id"] == args.route] or found
            if not match:
                print(f"      ! 编号 {args.route} 未找到")
                return 1
            targets = match
        else:
            targets = search_route(base, token, args.search)
            print(f"      关键词搜索到 {len(targets)} 条:")
            for r in targets:
                km = (r["distance"] or 0) / 1000
                print(f"        [{r['id']}] {r['title']}  {km:.1f}km  {r['cityName']}  by {r['nickName']}")
            if not targets:
                return 1

        for t in targets:
            rid = t["id"]
            print(f"[2/3] 拉取路书 {rid} ({t['title']})...")
            route = route_detail(base, token, rid)
            n = len(route["tracks"])
            print(f"      航点数: {n}")
            if n == 0:
                print("      ! 无航点数据，跳过")
                continue

            print("[3/3] 生成 GPX...")
            gpx = to_gpx(route)
            safe = t["title"].replace("/", "_").replace("\\", "_")
            outdir = args.outdir.rstrip("/\\")
            os.makedirs(outdir, exist_ok=True)
            outfile = f"{outdir}/{rid}-{safe}.gpx"
            with open(outfile, "w", encoding="utf-8") as f:
                f.write(gpx)
            km = (route["distance"] or 0) / 1000
            print(f"      已保存: {outfile}")
            print(f"      {route['title']} | {km:.1f}km 爬升{route['totalAscent']}m | {route['nickName']} | {route['cityName']}")

        return 0
    except IGPSPORTError as e:
        print(f"错误: {e}")
        return 1
    except Exception as e:
        print(f"意外错误: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())