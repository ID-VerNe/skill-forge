# -*- coding: utf-8 -*-
"""语义护栏：判一条改动是否「可能改变了原意」。

## 边界（重要）

这里**不做判断**。v1.13 的顶层裁决是「判断归 LLM、脚本只定位」。所以本模块
只做三件廉价、确定、可解释的事，命中就打 `requires_confirm: true`：

1. **否定/反向词新增或消失** —— 「不用」→「用」、「没」→「有」这类改动，
   一字之差把意思反过来，且改完读起来还很通顺，LLM 复核时最容易放过。
2. **编辑距离 > 60% 且原句 < 15 字** —— 短句几乎整句重写，通常不是润色而是
   另起一句；短句里没有足够上下文供 LLM 判断。
3. **新增/删除数字或专名** —— 数字（含阿拉伯、中文数字、时间、金额）和专名
   （连续大写英文、书名号/引号内的词）增删，是事实性改动，不是风格改动。

命中**不等于错**，只等于「必须人工确认」。护栏的价值在于把「静默改错」变成
「排队待确认」。
"""
from __future__ import annotations

import re
from typing import List


# ASS 覆写块：{\be3} {\an8} {\i1} {\pos(1,2)} 等。**必须先剥掉**再比较，
# 否则 {\be3} 里的 3 会被当成「数字」，`{\an8}` 的 8 会被当成十进制数字，
# 连「删去数字：3」这种理由都会被算出来——而观众根本看不到这些字符。
# 唯一不剥的是绘图指令，因为它后面带的是一串坐标而不是台词；但绘图行
# 本身不会进 fixes（是特效行），这里不额外处理。
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")


def strip_ass_tags(s: str) -> str:
    """去掉所有 ASS 覆写块，只留观众看得到的文本。"""
    return _ASS_TAG_RE.sub("", s or "")


NEG_WORDS = (
    "不", "没", "没有", "别", "勿", "非", "未", "无", "莫", "休",
    "禁止", "无需", "不必", "不用", "不要", "不会", "不能", "不是",
    "绝不", "决不", "未必", "并非",
)

NUM_PAT = re.compile(
    r"[0-9]+(?:\.[0-9]+)?%?"                       # 阿拉伯数字 / 小数 / 百分比
    r"|[一二三四五六七八九十百千万亿两半][一二三四五六七八九十百千万亿两半]*"
)
PROPER_PAT = re.compile(r"[《「『“\"]([^》」』”\"]{2,20})[》」』”\"]")
CAPS_PAT = re.compile(r"\b[A-Z][A-Za-z0-9&.\-]{1,}\b")


def _edit_ratio(a: str, b: str) -> float:
    """归一化编辑距离（0..1）。用 Levenshtein，短句上限 15 字，代价可忽略。"""
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (0 if ca == cb else 1)))
        prev = cur
    return prev[lb] / max(la, lb)


def _neg_hits(s: str) -> set:
    """句中命中的否定词集合（最长匹配，避免「不」把「不用」重复计两次）。"""
    hits = set()
    i = 0
    ordered = sorted(NEG_WORDS, key=len, reverse=True)
    while i < len(s):
        for w in ordered:
            if s.startswith(w, i):
                hits.add(w)
                i += len(w)
                break
        else:
            i += 1
    return hits


def _nums(s: str) -> set:
    return set(NUM_PAT.findall(s))


def _propers(s: str) -> set:
    out = set(PROPER_PAT.findall(s))
    out |= set(CAPS_PAT.findall(s))
    return out


def check(old: str, new: str) -> dict:
    """返回 {"requires_confirm": bool, "reasons": [str], "metrics": {...}}

    `old` / `new` 里若带 ASS 覆写块（{\\be3} 等）会先剥掉——判的是可见台词，
    不是排版指令。这一条很关键：`{\\be3}该死！啊！` → `该死！` 本来只是删了个
    语气词，剥标签前会被算成「编辑距离 73% + 删去数字 3」两条误报。
    """
    reasons: List[str] = []
    raw_o, raw_n = (old or ""), (new or "")
    o, n = strip_ass_tags(raw_o), strip_ass_tags(raw_n)
    if not o and not n:
        return {"requires_confirm": False, "reasons": [],
                "metrics": {"edit_ratio": 0.0, "old_len": 0, "new_len": 0,
                            "stripped_only_tag_change": True}}

    # 1. 否定词
    no, nn = _neg_hits(o), _neg_hits(n)
    added, removed = nn - no, no - nn
    if added:
        reasons.append("新增否定/反向词：%s" % "、".join(sorted(added)))
    if removed:
        reasons.append("删去否定/反向词：%s" % "、".join(sorted(removed)))

    # 2. 短句整体重写
    ratio = _edit_ratio(o, n)
    if len(o) < 15 and ratio > 0.60:
        reasons.append("短句重写（编辑距离 %.0f%% > 60%%，原句 %d 字）"
                       % (ratio * 100, len(o)))

    # 3. 数字 / 专名
    nd, nn2 = _nums(o), _nums(n)
    if nn2 - nd:
        reasons.append("新增数字：%s" % "、".join(sorted(nn2 - nd)))
    if nd - nn2:
        reasons.append("删去数字：%s" % "、".join(sorted(nd - nn2)))
    pd, pn = _propers(o), _propers(n)
    if pn - pd:
        reasons.append("新增专名：%s" % "、".join(sorted(pn - pd)))
    if pd - pn:
        reasons.append("删去专名：%s" % "、".join(sorted(pd - pn)))

    return {
        "requires_confirm": bool(reasons),
        "reasons": reasons,
        "metrics": {
            "edit_ratio": round(ratio, 3),
            "old_len": len(o),
            "new_len": len(n),
        },
    }


def annotate(fix: dict) -> dict:
    """给一条 fix 打上护栏结果（原地修改 + 返回）。

    `action` 不是 replace 的（retime/delete/insert/swap）跳过：它们改的不是
    「文本意思」这个层面，另有各自的检查。
    """
    if fix.get("action", "replace") != "replace":
        return fix
    old = fix.get("current") or fix.get("old_text") or ""
    new = fix.get("final_new") or fix.get("suggested_new") or ""
    if not old or not new:
        return fix
    g = check(old, new)
    if g["requires_confirm"]:
        fix["requires_confirm"] = True
        fix["guard"] = g["reasons"]
    else:
        fix.pop("requires_confirm", None)
        fix.pop("guard", None)
    return fix


def summarize(fixes: list) -> dict:
    """批量统计，供报告和 CLI 输出。"""
    flagged = [f for f in fixes if f.get("requires_confirm")]
    return {
        "total": len(fixes),
        "requires_confirm": len(flagged),
        "items": [{"id": f.get("id") or f.get("audit_id", ""),
                   "srt_id": f.get("srt_id"),
                   "reasons": f.get("guard", [])} for f in flagged],
    }
