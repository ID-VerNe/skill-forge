# -*- coding: utf-8 -*-
"""规则化翻译腔检查（信达雅之"达"轴）。

纯 Python 规则，无 LLM，秒级。判据照搬 translate_principle pipeline 的
TranslationQualityChecker（`core/quality_checker.py`），但适配 skill 的
切片格式（一 block 一行 `<srt_id> | <ass_time> | <英文> | <中文> | <注释>`）。

检查项：
  - 书面语残留：进行/实施/开展/予以/给予/关于/针对/基于/鉴于/
               显著/充分/有效/积极/此外/因此/所以/然而
                **判据不是「中文出现该词」，而是「中文出现该词，且英文没有
                对应来源」**。比如 `So` → 「所以」是忠实直译（话语标记），
                不算翻译腔；英文是 `Well` 却译成「然而」才报。详见 FORMAL_WORDS
                注释与 issue #7。
  - 机翻特征正则：的的 / 了了 / 重复标点
  - 长度异常比：译文 < 原文×0.4 或 > ×1.5（默认关，需 --len-ratio）

LLM（gemini-3.1 / glm-5.2）对书面语召回仅 6-11%，本脚本配合英文字段来源
对照后召回与精度都可用（S06E04 实测 63 条 → 2 条真阳性）。
软语境/俚语/委婉语抓不到，留给 LLM 两轨。

可独立单跑，也被 pre_audit.py 调用。

用法：
  python check_fluency.py <slice.txt> [--out report.json]
  python check_fluency.py <slice.txt>   # 打印到 stdout
  python check_fluency.py --audit-rules # 只自检规则表，不查字幕
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Dict

# 书面语黑名单（出现在口语对白里 = 翻译腔）
#
# issue #7：纯子串匹配会把「忠实直译」误判成翻译腔。实测 S06E04 一集
# 63 条「书面语残留」命中里 61 条是假阳性——53 条「所以」全部对应英文的
# `So`，是话语标记的忠实翻译，不是翻译腔。精度 3%，规则失去可用性。
#
# 修法：每个词配一份「英文对应来源」正则。只有中文出现该词、而英文**没有**
# 任何对应来源时，才算「英文没这个词，中文却冒出来」= 译者加戏的书面语。
#
# 值为 None 表示「无英文字面对应物」，纯中文语体问题（如「进行」是空动词，
# 英文不会有对应词），这类直接报，但标 confidence=medium 提示需人看语境。
FORMAL_WORDS = {
    "进行": None,
    "实施": None,
    "开展": None,
    "予以": None,
    "给予": None,
    "关于": r"\b(about|regarding|concerning|on|of|for)\b",
    "针对": r"\b(for|against|at|to|targeting)\b",
    "基于": r"\b(based on|on|from)\b",
    "鉴于": r"\b(given|considering|seeing)\b",
    "显著": r"\b(significant|significantly|notable|noticeably|markedly)\b",
    "充分": r"\b(fully|enough|plenty|sufficient|adequate|well)\b",
    "有效": r"\b(effective|effectively|works|work|efficient)\b",
    "积极": r"\b(actively|active|positive|eager)\b",
    "此外": r"\b(also|too|plus|besides|additionally|as well)\b",
    "因此": r"\b(so|therefore|thus|hence|then)\b",
    "所以": r"\b(so|therefore|thus|hence)\b",
    "然而": r"\b(but|however|yet|although|though|while|whereas)\b",
}

# 机翻特征正则
MACHINE_PATTERNS = [
    (r"的\s*的", "的的"),
    (r"了\s*了", "了了"),
    (r"[，。！？]{2,}", "重复标点"),
]


def validate_rules(rules: Dict[str, object] | None = None) -> List[str]:
    """启动自检：FORMAL_WORDS 每个值要么是 ``None``，要么是能编译的正则。

    为什么需要这个函数：注释挡不住手滑。往表里加词时最自然的动作是复制上一行
    再改，很容易留下一个 ``""``。而 ``""`` 在这里是**特别坏的**值：

        if en_pat and re.search(en_pat, en, re.I):   # "" → 假，跳过查源
            continue
        confidence = "medium" if en_pat is None else "high"   # "" is None → False → high

    于是空串会静默退化成「查过英文、确认无来源」并且标成 high —— 把一个忘了写
    来源的词伪装成经过对照的高置信命中。这不是风格问题，是把规则的语义偷偷改了。

    返回问题列表（空 = 通过）。不抛异常，方便测试逐条断言，也方便 main() 决定
    怎么退出。
    """
    table = FORMAL_WORDS if rules is None else rules
    problems: List[str] = []
    for word, pat in table.items():
        if pat is None:
            continue
        if not isinstance(pat, str):
            problems.append(
                f"{word!r}: 值是 {type(pat).__name__}，只接受 None 或正则字符串")
            continue
        if not pat.strip():
            problems.append(
                f"{word!r}: 值是空串/空白。空串是 falsy，check_line 会静默"
                f"退化成「无英文字面对应物」，同时 confidence 仍标 high。"
                f"无来源请显式写 None，有来源请写真正的正则")
            continue
        try:
            re.compile(pat)
        except re.error as e:
            problems.append(f"{word!r}: 正则编译失败（{e}）：{pat}")
    return problems


def _raise_if_rules_invalid() -> None:
    """check_line / check_slice 的入口闸门。

    放在这里而不是只放 main()，是因为 pre_audit.py 直接 import check_slice，
    不经过 main()。规则坏了必须在那条路径上也立刻炸，否则一个空串能让预审
    静默多报一堆假阳性。
    """
    problems = validate_rules()
    if problems:
        raise ValueError("FORMAL_WORDS 配置有误：\n  - " + "\n  - ".join(problems))


def audit_rules(rules: Dict[str, object] | None = None) -> Dict[str, list]:
    """人工审规则用：把「有英文来源」和「只能靠语境判断」分开列。

    只打印不判定。用途是给加词的人一面镜子：如果他新加的词落进了 bare 组，
    说明这条规则只能报 medium，不能当 high 用。
    """
    table = FORMAL_WORDS if rules is None else rules
    bare, sourced = [], []
    for word, pat in table.items():
        (bare if pat is None else sourced).append(word)
    return {"total": len(table), "sourced": sorted(sourced), "bare": sorted(bare)}

# 长度比阈值。
# 注意：ASS 字幕常把一句英文长句按时间轴拆成多行，单行中文看起来"过短"
# 但和相邻行拼起来译文完整。单行长度比在字幕场景精度接近 0%（实测
# Claude 把 21/22 条"译文过短"判为 misreport）。这里**默认关闭**长度比
# 检查，只在 --len-ratio 显式开启时跑，且标 confidence=low（仅辅助线索）。
LEN_MIN_RATIO = 0.25
LEN_MAX_RATIO = 2.0
LEN_MIN_EN = 12

# 切片行格式：<srt_id> | <ass_time> | <英文> | <中文> | <注释>
SLICE_LINE_RE = re.compile(
    r"^(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|"
)


def check_line(en: str, zh: str, len_ratio: bool = False) -> List[Dict]:
    """对单行（英文原文 + 中文译文）跑规则检查，返回 hit 列表。

    len_ratio：是否跑长度比检查（默认 False——字幕单行长度比精度接近 0%，
    ASS 常拆句导致单行中文"过短"但拼起来完整，实测 Claude 把 21/22 条
    "译文过短"判为 misreport）。开启时标 confidence=low（仅辅助线索）。

    每个 hit: {"axis": "达", "rule": ..., "detail": ..., "suggestion": ...}
    """
    # 规则表坏了就立刻炸，不要带着一个空串继续跑出一堆假阳性。
    # 不做「首次校验后缓存」：re.compile 本身有缓存，逐行校验的成本是字典遍历，
    # 而缓存会让「运行中有人改了 FORMAL_WORDS」这种测试场景漏过去。
    _raise_if_rules_invalid()

    hits = []
    # 1. 书面语黑名单（issue #7：先查英文有没有对应来源，避免把忠实直译误判成翻译腔）
    for word, en_pat in FORMAL_WORDS.items():
        if word not in zh:
            continue
        if en_pat and re.search(en_pat, en, re.I):
            continue  # 英文确有对应词 → 忠实直译，不是翻译腔
        reason = (f"英文无对应来源（查 {en_pat}）" if en_pat
                  else "无英文字面对应物，纯中文语体问题")
        hits.append({
            "axis": "达",
            "rule": "书面语残留",
            "detail": f"命中：{word}；{reason}",
            "suggestion": "改为口语化表达",
            "confidence": "medium" if en_pat is None else "high",
        })
    # 2. 机翻特征
    for pat, name in MACHINE_PATTERNS:
        m = re.search(pat, zh)
        if m:
            hits.append({
                "axis": "达",
                "rule": "机翻特征",
                "detail": f"{name}：{m.group(0)!r}",
                "suggestion": "修正重复",
            })
    # 3. 长度比（默认关——ASS 拆句使单行中文普遍"过短"，精度接近 0%）
    if len_ratio and len(en) >= LEN_MIN_EN:
        ratio = len(zh) / len(en)
        if ratio < LEN_MIN_RATIO:
            hits.append({
                "axis": "信",
                "rule": "译文过短",
                "detail": f"ratio={ratio:.2f}（en={len(en)} zh={len(zh)}）",
                "suggestion": "检查是否漏译（长度比仅辅助线索）",
                "confidence": "low",
            })
        elif ratio > LEN_MAX_RATIO:
            hits.append({
                "axis": "达",
                "rule": "译文过长",
                "detail": f"ratio={ratio:.2f}（en={len(en)} zh={len(zh)}）",
                "suggestion": "检查是否冗余/加戏",
                "confidence": "low",
            })
    return hits


def check_slice(slice_path: Path, len_ratio: bool = False) -> List[Dict]:
    """对整个切片文件跑检查，返回 hit 列表（每条带 srt_id/ass_time/hits）。

    只查中文行（英文行是源片台词，不查）。
    """
    results = []
    for line in slice_path.read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\n")
        if not line or line.startswith("#") or line.startswith("slice"):
            continue
        m = SLICE_LINE_RE.match(line)
        if not m:
            continue
        sid = int(m.group(1))
        ass_time = m.group(2).strip()
        en = m.group(3).strip()
        zh = m.group(4).strip()
        if not zh:
            # 中文行为空是漏译，归第 2 类不是信达雅，跳过
            continue
        hits = check_line(en, zh, len_ratio=len_ratio)
        if hits:
            results.append({
                "srt_id": sid,
                "ass_time": ass_time,
                "english": en,
                "current": zh,
                "hits": hits,
            })
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slice", nargs="?", help="切片文件（extract_slice.py 输出）")
    ap.add_argument("--out", help="写 JSON 到此路径（不给则打印到 stdout）")
    ap.add_argument("--summary", action="store_true",
                    help="只打印每类计数摘要，不列明细")
    ap.add_argument("--len-ratio", action="store_true",
                    help="开启长度比检查（默认关——字幕单行精度接近 0%）")
    ap.add_argument("--audit-rules", action="store_true",
                    help="只自检并列出规则表（分「有英文来源」/「只能靠语境」两组），不查字幕")
    args = ap.parse_args()

    # 启动自检：先看规则表，再看字幕。规则坏了查字幕没意义——
    # 空串会静默退化成「无来源 + high」，跑出来的报告是错的但看着像对的。
    problems = validate_rules()
    if problems:
        print("规则自检失败，FORMAL_WORDS 配置有误：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(2)

    if args.audit_rules:
        a = audit_rules()
        print(f"规则自检通过：{a['total']} 个词，"
              f"{len(a['sourced'])} 个有英文来源，{len(a['bare'])} 个无字面对应物")
        print()
        print(f"有英文来源（英文对得上就不报，标 confidence=high）：{len(a['sourced'])} 个")
        print("  " + " / ".join(a["sourced"]))
        print()
        print(f"无英文字面对应物（照报，但只能靠语境判断，**不要当 high 报**）："
              f"{len(a['bare'])} 个")
        print("  " + (" / ".join(a["bare"]) if a["bare"] else "（无）"))
        print()
        print("加词须知：值为 None 表示「英文不会有对应词」（空动词、公文腔虚词）。")
        print("若这个词在英文里其实有说法，就写来源正则——否则会把忠实直译报成翻译腔。")
        return

    if not args.slice:
        ap.error("缺少切片文件（或改用 --audit-rules 只自检规则）")

    slice_path = Path(args.slice)
    if not slice_path.is_file():
        print(f"切片文件不存在：{args.slice}", file=sys.stderr)
        sys.exit(1)

    results = check_slice(slice_path, len_ratio=args.len_ratio)

    if args.summary:
        from collections import Counter
        rule_counts = Counter()
        for r in results:
            for h in r["hits"]:
                rule_counts[h["rule"]] += 1
        print(f"切片：{slice_path.name}")
        print(f"命中行数：{len(results)}")
        for rule, cnt in rule_counts.most_common():
            print(f"  {rule}: {cnt}")
        return

    out = {
        "slice": str(slice_path),
        "total_hits": len(results),
        "results": results,
    }
    payload = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"写 {len(results)} 条命中到 {args.out}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
