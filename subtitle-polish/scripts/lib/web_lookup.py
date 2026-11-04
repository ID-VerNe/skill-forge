"""在线检索核实：唯一的网络出口（issue #30 建议 2 D 部分）。

设计约束（用户拍板）：
  - **可关闭的开关**：默认关闭，`scan_seed.py --web-verify` 才开；
    显式 `--no-web-verify` 可覆盖配置。
  - **失败降级**：网络失败/超时/解析异常统一返回 `status=unavailable`，
    不让主流程失败（scan_seed 退出码不受影响）。
  - **只作提示**：返回值只带检索来源与标题，不给「应该改成什么」，
    不写 ASS，不改任何判定。
  - **便于整块删除**：所有网络调用都收在这个文件里，`scan_seed.py`
    只通过 `verify_term(term, enabled=...)` 使用它。效果不好时删掉本文件
    并移除调用点即可。

当前实现用 Wikipedia 搜索 API（无需密钥）：
  https://en.wikipedia.org/w/api.php?action=query&list=search&...
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

_API = "https://en.wikipedia.org/w/api.php"
_UA = "subtitle-polish/scan_seed (+https://github.com/ID-VerNe/skill-forge)"
_SEARCH_URL = "https://en.wikipedia.org/w/index.php?search="


def _search_url(term: str) -> str:
    return _SEARCH_URL + urllib.parse.quote(term)


def _page_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(
        title.replace(" ", "_"), safe="()_,'-")


def verify_term(term: str, *, enabled: bool = False, timeout: float = 5.0,
                opener=None) -> dict:
    """检索疑似专名的标准拼写线索。

    返回：
      {"status": "disabled"}                         未开启
      {"status": "found", "title", "source_url", ...} 找到页面
      {"status": "no_result", "source_url"}            检索成功但无结果
      {"status": "unavailable", "source_url", "note"}  网络/解析失败

    绝不返回「替换词」。是否采用由人工或审计轮决定。
    """
    if not enabled:
        return {"status": "disabled", "query": term}

    url = _API + "?" + urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": term,
        "format": "json", "srlimit": 3,
    })
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        hits = ((data.get("query") or {}).get("search") or [])
        if not hits:
            return {"status": "no_result", "query": term,
                    "source_url": _search_url(term)}
        first = hits[0]
        title = first.get("title") or term
        return {
            "status": "found",
            "query": term,
            "title": title,
            "snippet": (first.get("snippet") or "").replace("<span class=\"searchmatch\">", "") \
                .replace("</span>", "")[:200],
            "source_url": _page_url(title),
        }
    except Exception as e:  # noqa: BLE001 - 任何网络/解析异常都降级为「未检索」
        return {
            "status": "unavailable",
            "query": term,
            "source_url": _search_url(term),
            "note": ("%s: %s" % (type(e).__name__, e))[:160],
        }
