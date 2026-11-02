# -*- coding: utf-8 -*-
"""scan_inclusive.py — 第 8 类（中立与合规：敏感词 / 性别·政治·法律·歧视）确定性扫描。

只读、不调模型、不写 ASS、不改 log。输出两组：

  hits         L1/L2/L3 候选（带建议替换与子域标签）
  whitelisted  L4 命中——**明确写「已白名单，未改」**

为什么要"确定性"：这类问题的最大风险不是漏改，是**误改**。`母头`/`公头`
是螺接、端子的行业标准词，`处女座` 是星座名，`夫妻肺片` 是菜名——靠 agent
每轮凭感觉判断，迟早会挑一个改掉。清单落在
`references/inclusive-language.md`，改词表只改这一处。

四个子域（A 性别与性 / B 宗教与迷信 / C 政治与主权 / D 法律与其他）共用
L1–L4，但 **C 子域默认只出 flag（`action: "flag"`），永不给可落盘的替换**——
政治内容属判断问题而非词语问题，交人裁是唯一安全解。加 `--politics` 才允许
C 子域的 L1 出建议，且仍需人在门 2 逐条确认。

用法:
  python scan_inclusive.py <ass_or_dir> [--srt <srt_or_dir>]
  python scan_inclusive.py <ass> --layer L1 --json out.json
  python scan_inclusive.py <ass> --domain C          # 只看政治与主权
  python scan_inclusive.py <ass> --politics          # 允许 C 子域 L1 出建议
  python scan_inclusive.py <ass> --md .subtitle-polish/reports/inclusive-report.md

退出码:
  0  扫描完成，无候选
  1  扫描完成，有候选（**不是错误**，是可操作信号）
  2  输入非法 / 清单为空
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ass_srt_pair import (parse_srt, style_to_track, clean_ass_text,
                              TRACK_ZH, TRACK_EN, TRACK_NOTE)

SKILL_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIST_PATH = os.path.join(SKILL_ROOT, "references", "inclusive-language.md")

# ── 内置清单（与 references/inclusive-language.md 同源） ─────────────────────
# 为什么内置一份而不是运行时解析 md：#1 解析 md 表格对格式敏感，改个排版就静默
# 少读几行（静默少读 = 该报的没报，最难发现的那种 bug）；#2 测试要能锁住清单内容。
# 代价是两处要同步——由 tests/test_subtitle_polish_inclusive.py 交叉校验，
# 不一致就红，不会静默漂移。

#: 子域名（报告分段用）
DOMAIN_NAMES = {
    "A": "性别与性",
    "B": "宗教与迷信",
    "C": "政治与主权",
    "D": "法律与其他",
}

#: C 子域：**默认只 flag，永不落盘**。见 references/inclusive-language.md「C 子域为什么零自动改」
POLITICAL = "C"

#: L1 硬替换：词本身即问题，替换后语义完全等同
#: 值为 (替换, 子域)
L1 = {
    "处女航": ("首航", "A"),
    "处女作": ("首部作品", "A"),
    "处女秀": ("首秀", "A"),
    # C 子域（仅 --politics 时才出建议；否则只 flag）
    "中港台": ("中国内地、香港、台湾地区", "C"),
}

#: L2 语境替换：需看原文与上下文，默认建议但不强制
L2 = {
    "天啊": ("天呐", "B"),
    "老天啊": ("天呐", "B"),
    "我的天啊": ("天呐", "B"),
    "上帝啊": ("天呐", "B"),
    "天杀的": ("见鬼", "B"),
    "该死的": ("见鬼", "B"),
    "神经病": ("有病吧", "D"),
    "土著": ("原住民", "D"),
    "老外": ("外国人", "D"),
    "洋人": ("外国人", "D"),
}

#: L3 弱化：原文即贬义，只标注不改
L3 = {
    "娘们": "A",
    "娘娘腔": "A",
    "像个女人": "A",
    "女司机": "A",
    "婆妈": "A",
    "婆婆妈妈": "A",
    "基佬": "D",
    "残废": "D",
    "洋鬼子": "D",
    "死翘翘": "D",
    "死鬼": "D",
}

#: L4 白名单：看着像，改了就是错。**命中即终止，不生成任何建议。**
#: 顺序有讲究：长词在前，避免 `母头` 先命中把 `母螺纹` 的另一半吃掉。
WHITELIST = (
    # A
    "处女座", "处女星号", "处女号", "夫妻肺片",
    # 工业标准词（A 侧女性/男性接插件）
    "母螺纹", "公螺纹", "母座", "公座", "母头", "公头", "母插", "公插",
    # C：地名/术语/专名的正常用法
    "大陆架", "大陆坡", "大陆性气候", "台湾卤肉饭", "台湾地区",
    "西藏高原", "西藏牦牛", "太平天国", "义和团",
)

#: 白名单里的「长词优先」排序（长度倒序，同长按原序）
_WHITELIST_SORTED = tuple(sorted(WHITELIST, key=len, reverse=True))


def _patterns(terms):
    """按长度倒序拼正则，长词优先命中（`处女星号` 不被 `处女` 抢先）。"""
    ordered = sorted(terms, key=len, reverse=True)
    if not ordered:
        return None
    return re.compile("|".join(re.escape(t) for t in ordered))


_WHITELIST_RE = _patterns(_WHITELIST_SORTED)
_L1_RE = _patterns(L1)
_L2_RE = _patterns(L2)

_MASK_RE = re.compile(r"\{[^}]*\}")  # ASS 覆盖标签


def _masked(text: str) -> str:
    """把 ASS 覆盖标签换成等长占位（保持字符位置），避免 `{\\i1}` 之类参与匹配。

    等长替换而不是删掉：删掉会让 span 位置和原文对不上，没法回显上下文。
    """
    return _MASK_RE.sub(lambda m: "\x00" * len(m.group(0)), text or "")


def _spans(regex, masked: str):
    if regex is None:
        return []
    return [(m.start(), m.end()) for m in regex.finditer(masked)]


def _overlaps(a, spans) -> bool:
    s, e = a
    return any(not (e <= s2 or s >= e2) for s2, e2 in spans)


def _table(regex, table, matched: str) -> tuple:
    """返回 (suggestion, domain)。table 形如 {term: (suggestion, domain)}。"""
    hit = table.get(matched)
    if hit is None:
        return "", "A"
    return hit[0], hit[1]


def _c_regex(allow_suggest: bool):
    """C 子域的扫描词。默认（无 --politics）只用来 **发现并 flag**，不给建议。

    为什么默认也扫：不扫就漏检，人根本不知道这集涉及时政表述；
    给了建议则等于让脚本替人做判断。所以「扫到、标出来、不给改法」是唯一稳妥解。
    """
    terms = ["中港台", "大陆", "台湾", "西藏", "新疆", "六四", "光复"]
    return _patterns(terms)


_C_RE = _c_regex(False)


def classify(text: str, *, allow_politics: bool = False) -> dict:
    """对一个可见文本做分层判定。

    返回 `{"hits": [...], "whitelisted": [...]}`。每条 hit 带 `domain`
    （A 性别与性 / B 宗教与迷信 / C 政治与主权 / D 法律与其他）与
    `action`（`fix` 可落盘 / `flag` 只标注）。

    判定顺序**必须是白名单优先**：先算出所有 L4 的 span，再判 L1/L2，
    落在白名单 span 内的一律丢弃。顺序反了，`母头` 里的 `母` 前缀路径
    （以及 `大陆架` 之于 `大陆`）会被误判成问题。
    """
    masked = _masked(text)
    wl_spans = _spans(_WHITELIST_RE, masked)
    out = {"hits": [], "whitelisted": []}

    for s, e in wl_spans:
        out["whitelisted"].append({
            "term": masked[s:e],
            "suggestion": "",      # 白名单不给建议
            "layer": "L4",
            "domain": "",
            "action": "none",
        })

    for layer, regex, table in (("L1", _L1_RE, L1), ("L2", _L2_RE, L2)):
        for s, e in _spans(regex, masked):
            if _overlaps((s, e), wl_spans):
                continue  # 白名单优先
            term = masked[s:e]
            sug, dom = _table(regex, table, term)
            # C 子域：默认把建议抹掉，只留 flag（政治零自动改）
            if dom == POLITICAL and not allow_politics:
                sug = ""
            out["hits"].append({
                "term": term,
                "suggestion": sug,
                "layer": layer,
                "domain": dom,
                # action 只判「这条有没有可用改法」：有建议才能算 fix。
                # C 子域在默认模式下 sug 已被抹空，自然落到 flag，不需要额外分支。
                "action": "fix" if sug else "flag",
            })

    for term, dom in L3.items():
        idx = masked.find(term)
        while idx != -1:
            span = (idx, idx + len(term))
            if not _overlaps(span, wl_spans):
                out["hits"].append({
                    "term": term,
                    "suggestion": "",     # L3 只标注
                    "layer": "L3",
                    "domain": dom,
                    "action": "flag",
                })
            idx = masked.find(term, idx + 1)

    # C 子域兜底发现：清单外但明显涉及时政表述的行，只 flag、不给改法。
    # 这是「发现 + 标注」而非「判定 + 修改」——本 skill 不承担时政立场判定。
    # 层沿用该词在 L1/L2 表里的归属：表里有的按表判，表里没有的按 L2（需看语境）。
    in_l1 = set(L1)
    for s, e in _spans(_C_RE, masked):
        if _overlaps((s, e), wl_spans):
            continue
        term = masked[s:e]
        if any(h["term"] == term and h["domain"] == POLITICAL for h in out["hits"]):
            continue  # L1/L2 已命中，不重复
        out["hits"].append({
            "term": term,
            "suggestion": "",
            "layer": "L1" if term in in_l1 else "L2",
            "domain": POLITICAL,
            "action": "flag",
        })

    return out


def scan_text(text: str, *, layers=("L1", "L2", "L3"), domains=("A", "B", "C", "D"),
              allow_politics: bool = False) -> dict:
    """按层/子域过滤后的判定，供测试与 --layer/--domain 用。"""
    r = classify(text, allow_politics=allow_politics)
    return {
        "hits": [h for h in r["hits"]
                 if h["layer"] in layers and h["domain"] in domains],
        "whitelisted": r["whitelisted"],
    }


# ── 文件扫描 ────────────────────────────────────────────────────────────────

def _collect(target: str, ext: str) -> list:
    """单文件时只在扩展名匹配时才返回——否则调用方按 ext 循环三轮，
    同一个 .ass 会被收三次，候选全部重复三份（fixes.json 也会跟着重复）。"""
    if os.path.isdir(target):
        return sorted(glob.glob(os.path.join(target, "**", "*" + ext), recursive=True))
    return [target] if target.lower().endswith(ext) else []


def _find_srt_for(ass_path: str) -> str:
    """找配对 SRT：优先同名，退化为目录内唯一的那份。

    L2 判语境要用英文原文；找不到英文就等于 L2 只能靠中文猜，误判率飙升。
    所以退化时只要有唯一候选就用——比空手强。
    """
    d = os.path.dirname(os.path.abspath(ass_path))
    stem = os.path.splitext(os.path.basename(ass_path))[0]
    cands = [c for c in glob.glob(os.path.join(d, "*.srt"))
             if not c.lower().endswith(".bak")]
    for cand in cands:
        if os.path.splitext(os.path.basename(cand))[0] == stem:
            return cand
    return cands[0] if len(cands) == 1 else ""


def _srt_blocks(srt_path: str) -> list:
    """读 SRT 块。ASS 混进来时（`--srt` 给错文件、目录里只有 ass）返回空而不是抛异常——
    但这会让英文列全空，下游必须能看出来，所以 main 里会显式提示。"""
    if not srt_path or not os.path.exists(srt_path):
        return []
    if srt_path.lower().endswith((".ass", ".ssa")):
        return []  # parse_srt 吃不了 ASS；静默返回空会把「没英文」伪装成「不需要英文」
    try:
        return parse_srt(srt_path)
    except Exception:
        return []


def _nearest_en(srt_blocks, sec: float) -> str:
    """取时间上最近的 srt 英文块文本，供 L2 判语境（不看英文没法判 `天啊` 该不该留）。

    容差 3s 而非 1s：配对 srt 与 ASS 常有 1–2s 的整体偏移，1s 太紧会让大片 L2 候选
    拿不到原文，看起来像「英文列为空」的 bug。宁可偶尔取到邻句，也不要整列空。
    """
    best, best_d = "", 1e9
    for b in srt_blocks:
        d = abs(float(getattr(b, "start", 0)) - sec)
        if d < best_d:
            best_d, best = d, getattr(b, "text", "") or ""
    if best_d > 3.0:
        return ""
    en_fn = getattr(best, "english_text", None)
    if callable(en_fn):
        try:
            return en_fn()
        except Exception:
            pass
    return best.replace("\n", " ").strip()


def _is_cjk(text: str) -> bool:
    """含汉字即视为中文文本。用于在样式名不可识别时判轨道。"""
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def scan_ass(ass_path: str, srt_path: str = "", layers=("L1", "L2", "L3"),
             domains=("A", "B", "C", "D"), allow_politics: bool = False) -> dict:
    import pysubs2

    subs = pysubs2.load(ass_path, encoding="utf-8-sig")
    blocks = _srt_blocks(srt_path or _find_srt_for(ass_path))
    hits, wl = [], []

    events = list(subs.events)
    # 样式名认不出来（如一律叫 Default）时，按「含汉字」判中文轨兜底。
    # 不兜底的话，整份文件会因为 track != TRACK_ZH 全被 continue 掉，
    # 输出「候选 0 条」——那是**静默漏检**，比误报危险得多：
    # 人看到 0 条会以为这集干净，实际上一句都没扫。
    known = sum(1 for e in events if style_to_track(e.style or "") in
                (TRACK_ZH, TRACK_EN, TRACK_NOTE))
    fallback = bool(events) and known == 0

    # C3：**必须带 srt_id**。以前报表只有「时间」列，下游 `make_fixes` 照着
    # 128.92 当索引去取第 128 行，直接 IndexError；就算不崩，也是靠秒数猜行号，
    # 一旦有同起点/同秒的相邻行就指到别的句子上去。行号在 ASS 里是唯一稳定的定位。
    for idx, e in enumerate(events, 1):
        body = clean_ass_text(e.text or "")
        if fallback:
            if not _is_cjk(body):
                continue
            track = TRACK_ZH
        else:
            track = style_to_track(e.style or "")
            if track != TRACK_ZH:
                continue  # 只扫中文轨：英文轨是源片台词，不是译文
        r = scan_text(body, layers=layers, domains=domains,
                      allow_politics=allow_politics)
        sec = (e.start or 0) / 1000.0
        for h in r["hits"]:
            hits.append(dict(h, file=os.path.abspath(ass_path), track=track,
                             srt_id=idx,
                             start=round(sec, 2), end=round((e.end or 0) / 1000.0, 2),
                             text=body, en=_nearest_en(blocks, sec)))
        for h in r["whitelisted"]:
            wl.append(dict(h, file=os.path.abspath(ass_path), track=track,
                           srt_id=idx, start=round(sec, 2), text=body))
    return {"hits": hits, "whitelisted": wl, "track_fallback": fallback}


def scan_srt(srt_path: str, layers=("L1", "L2", "L3"),
             domains=("A", "B", "C", "D"), allow_politics: bool = False) -> dict:
    """扫 SRT 也用得上：`处女航` 可能出现在还没翻译的英文译稿里。"""
    hits, wl = [], []
    for idx, b in enumerate(_srt_blocks(srt_path), 1):
        text = (getattr(b, "text", "") or "").replace("\n", " ")
        r = scan_text(text, layers=layers, domains=domains,
                      allow_politics=allow_politics)
        for h in r["hits"]:
            hits.append(dict(h, file=os.path.abspath(srt_path), track="srt",
                             srt_id=idx,
                             start=round(float(getattr(b, "start", 0)), 2),
                             text=text, en=text))
        for h in r["whitelisted"]:
            wl.append(dict(h, file=os.path.abspath(srt_path), track="srt",
                           srt_id=idx,
                           start=round(float(getattr(b, "start", 0)), 2), text=text))
    return {"hits": hits, "whitelisted": wl}


# ── 输出 ────────────────────────────────────────────────────────────────────

_LAYER_NOTE = {
    "L1": "硬替换，可进 fixes.json（C 子域除外）",
    "L2": "语境替换，审计 agent 确认后进 fixes.json（C 子域除外）",
    "L3": "原文即贬义，**只标注不改**",
    "L4": "白名单，**绝不改**",
}


def _md_table(rows, header):
    L = ["| " + " | ".join(header) + " |",
         "|" + "---|" * len(header)]
    L += rows
    L.append("")
    return L


def render_md(result: dict, targets: list, allow_politics: bool = False) -> str:
    hits, wl = result["hits"], result["whitelisted"]
    fb = result.get("track_fallback") or []
    n_fix = sum(1 for h in hits if h.get("action") == "fix")
    n_flag = sum(1 for h in hits if h.get("action") == "flag")
    L = ["# 第 8 类扫描：中立与合规（敏感词 / 性别·政治·法律·歧视）", "",
         f"- 扫描对象：{len(targets)} 个文件",
         f"- 候选：{len(hits)} 条（可改 {n_fix} / 仅标注 {n_flag}）| 白名单命中：{len(wl)} 条",
         f"- 政治子域（C）：{'允许出建议（--politics）' if allow_politics else '只标注，不改'}",
         f"- 扫描时间：{datetime.now().isoformat(timespec='seconds')}", ""]

    if fb:
        L += ["> [!] **轨道判定降级**：" + "、".join(os.path.basename(x) for x in fb) +
              " 的样式名认不出轨道（如一律叫 Default），已按「含汉字」兜底判中文轨。",
              "> 兜底是保守方向（不会漏扫），但若该文件英文轨也含汉字注释，那些行会被一起扫到。", ""]

    ns = result.get("no_srt") or []
    if ns:
        L += ["> [!] **没有配对 SRT**：" + "、".join(os.path.basename(x) for x in ns) +
              " 找不到同目录 srt，**英文列全空**。L2/B 类判断缺原文依据，",
              "> `天啊`、`该死的` 这类只能凭中文猜，误判率显著上升。请用 `--srt` 指定。", ""]

    if not hits:
        L += ["## 候选", "", "没有。", ""]
    else:
        # 按子域分段：A/B/D 出「可改」表，C 出 flag 表。
        for dom in ("D", "A", "B", "C"):
            sub = [h for h in hits if h.get("domain") == dom]
            if not sub:
                continue
            title = f"## {dom} {DOMAIN_NAMES[dom]}"
            if dom == POLITICAL:
                title += "（**默认只标注，不改**）" if not allow_politics else "（`--politics`：L1 给建议，L2 仍只标注）"
            L += [title, ""]
            if dom == POLITICAL and not allow_politics:
                L += ["> 政治内容属判断问题而非词语问题：脚本只负责**发现并标出**，",
                      "> 不提供改法，也不落盘。要改请人工处理，或在门 2 逐条确认。",
                      "> 本 skill 不承担时政立场判定。", ""]
                # C3：首列必须是 srt_id。下游拿「时间」当索引会 IndexError；
                # 且同秒相邻行靠秒数根本分不开。
                rows = ["| %s | %s | `%s` | %.2fs | %s | %s |" % (
                    h.get("srt_id", "—"), h.get("layer") or "—", h["term"],
                    h["start"], h["text"][:26],
                    os.path.basename(h["file"])) for h in
                    sorted(sub, key=lambda x: (x["file"], x.get("srt_id") or 0))]
                L += _md_table(rows, ["srt_id", "层", "命中", "时间(秒)", "现译", "文件"])
            else:
                if dom == POLITICAL:
                    L += ["> `--politics` 只放开 L1 的替换建议；L2 仍需语境判断，保持只标注。",
                          "> 落盘前仍须在门 2 逐条确认——C 子域不走批量 accept。", ""]
                rows = []
                for h in sorted(sub, key=lambda x: (x.get("layer"),
                                                    x["file"],
                                                    x.get("srt_id") or 0)):
                    rows.append("| %s | %s | `%s` | %s | %.2fs | %s | %s | %s |" % (
                        h.get("srt_id", "—"), h["layer"], h["term"],
                        h.get("suggestion") or "—",
                        h["start"], h["text"][:22], (h.get("en") or "")[:28],
                        os.path.basename(h["file"])))
                L += _md_table(rows, ["srt_id", "层", "命中", "建议", "时间(秒)",
                                      "现译", "英文", "文件"])

        L += ["> L3 层（只标注）与 C 子域 **不进** `fixes.json`。L1/L2 进之前须过白名单与语义检查。", ""]

    L += ["## 白名单命中（已白名单，未改）", ""]
    if wl:
        rows = ["| %s | `%s` | %.2fs | %s | 行业标准词/专名/正常用法，改动即错 |"
                % (h.get("srt_id", "—"), h["term"], h["start"],
                   h["text"][:26]) for h in
                sorted(wl, key=lambda x: (x["file"], x.get("srt_id") or 0))]
        L += _md_table(rows, ["srt_id", "命中", "时间(秒)", "现译", "说明"])
        L += ["> 这一节存在的意义：防止把「白名单拦住」误读成「漏改」。", ""]
    else:
        L += ["没有。", ""]

    L += ["## 本类硬约束", ""]
    for k, v in _LAYER_NOTE.items():
        L.append(f"- **{k}**：{v}")
    L += ["- **C 子域零自动改**：政治与主权表述一律只 flag，不落盘（`--politics` 也只是放开 L1 建议）。",
          "- 清单外的候选只进本报告，**不进** `fixes.json`。",
          "- 清单唯一来源：`references/inclusive-language.md`。", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description="第 8 类：中立与合规（敏感词/性别·政治·法律·歧视）确定性扫描（只读）")
    ap.add_argument("target", help="ASS 文件或目录；也可直接给 SRT")
    ap.add_argument("--srt", default="", help="配对 SRT（含英文原文，供 L2 判语境）")
    ap.add_argument("--layer", default="",
                    help="只看某几层，逗号分隔：L1,L2,L3（默认全部）")
    ap.add_argument("--domain", default="",
                    help="只看某几个子域，逗号分隔：A,B,C,D（默认全部）"
                         "｜A 性别与性 / B 宗教与迷信 / C 政治与主权 / D 法律与其他")
    ap.add_argument("--politics", action="store_true",
                    help="允许 C 子域（政治与主权）的 L1 出替换建议；默认 C 只标注不改")
    ap.add_argument("--json", default="", help="结果写 json")
    ap.add_argument("--md", default="", help="报告写 md")
    args = ap.parse_args()

    if not os.path.exists(args.target):
        print(f"[!] 不存在：{args.target}", file=sys.stderr)
        return 2

    layers = tuple(x.strip().upper() for x in args.layer.split(",") if x.strip()) \
        or ("L1", "L2", "L3")
    domains = tuple(x.strip().upper() for x in args.domain.split(",") if x.strip()) \
        or ("A", "B", "C", "D")
    bad = [d for d in domains if d not in DOMAIN_NAMES]
    if bad:
        print(f"[!] 未知子域：{bad}（可选 A/B/C/D）", file=sys.stderr)
        return 2

    targets = []
    result = {"hits": [], "whitelisted": [], "track_fallback": [], "no_srt": []}
    seen = set()
    for ext in (".ass", ".ssa", ".srt"):
        for p in _collect(args.target, ext):
            if p.endswith(".bak"):
                continue
            real = os.path.normcase(os.path.abspath(p))
            if real in seen:
                continue
            seen.add(real)
            targets.append(p)

    if not targets:
        print(f"[!] 没找到 ASS/SSA/SRT：{args.target}", file=sys.stderr)
        return 2

    for p in targets:
        low = p.lower()
        if low.endswith((".ass", ".ssa")):
            srt = args.srt if len(targets) == 1 else ""
            if not srt and not _find_srt_for(p):
                result["no_srt"].append(p)
            r = scan_ass(p, srt, layers=layers,
                         domains=domains, allow_politics=args.politics)
            if r.get("track_fallback"):
                result["track_fallback"].append(p)
        else:
            r = scan_srt(p, layers=layers, domains=domains,
                         allow_politics=args.politics)
        result["hits"] += r["hits"]
        result["whitelisted"] += r["whitelisted"]

    md = render_md(result, targets, allow_politics=args.politics)
    if args.md:
        os.makedirs(os.path.dirname(os.path.abspath(args.md)) or ".", exist_ok=True)
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)

    if args.json:
        payload = {
            "scanned": targets,
            "layers": list(layers),
            "domains": list(domains),
            "allow_politics": bool(args.politics),
            "generated": datetime.now().isoformat(timespec="seconds"),
            "list_source": LIST_PATH,
            "track_fallback": result["track_fallback"],
            "no_srt": result["no_srt"],
            "hits": result["hits"],
            "whitelisted": result["whitelisted"],
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"[json] {args.json}", file=sys.stderr)

    if result["track_fallback"]:
        print("[!] 样式名无法识别轨道，已按「含汉字」兜底判中文轨："
              + ", ".join(os.path.basename(x) for x in result["track_fallback"]),
              file=sys.stderr)

    if result["no_srt"]:
        print("[!] 无配对 SRT，英文列全空（L2 判断缺依据）："
              + ", ".join(os.path.basename(x) for x in result["no_srt"]),
              file=sys.stderr)

    n = len(result["hits"])
    print(f"[*] 候选 {n} 条，白名单命中 {len(result['whitelisted'])} 条",
          file=sys.stderr)
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
