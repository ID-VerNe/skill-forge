# -*- coding: utf-8 -*-
"""scan_seed.py — 给审计 subagent 出**线索**，不做判断。

⚠ 这个脚本的定位是「索引」，不是「判定器」。它唯一的作用是让并行 subagent
不必把每片都从头读到尾（浪费上下文），同时不因为关键词没命中就整块跳过。

为什么需要它，以及为什么**不能**拿它当判断：

  `处女航` 能被词表抓到，`the first time she's ever taken a boat out`（同样
  该译「首航」）抓不到；`大陆` 能被抓到，`mainland` 译成「中国本土」抓不到；
  一句明显带地域歧视的台词里可能一个敏感词都没有。

  也就是说：**词表扫描的召回上限就是词表本身**。用它当判据，等于宣称
  「词表里没有的问题不存在」。这只在一种情况下成立——问题真的只是词语替换。

  而第 8 类恰恰不是。它是「这句话在这个节目、这个角色、这个语境下会不会
  被拿来指责」，那是判断，只有读上下文的人（LLM）做得了。

所以分工是：

  脚本（本文件）  给出**锚点位置**：命中词、白名单候选、疑似感叹/贬义/称谓行
  subagent        读它负责的那一段**全文**，自己判断有没有问题、要不要改
  主 agent        合并去重，再过白名单核对

本脚本产出的 `seeds` 段里带 `hint_text` 与 `instruction`，是要**原样贴进
subagent prompt** 的（`{seeds}` 占位符）。别只贴 json——json 里的锚点会被
agent 当成待办清单，而真正该做的是读全文。

用法:
  python scan_seed.py <slice.txt> --out .subtitle-polish/reports/seed-e05_p1.json
  python scan_seed.py <ass_or_dir> --srt <srt>   # 直接从 ASS 出种子（不经切片）
  python scan_seed.py <slice.txt> --fmt md       # 人读版

退出码:
  0  正常（**不给「有无问题」的信号**——这是线索器，没有「有候选/无候选」之分；
     拿退出码当门禁会重新引入「词表没命中 = 干净」这个错误）。
  2  输入非法
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

import scan_inclusive as si

# ── 独立的正则：**故意扫得比词表宽** ────────────────────────────────────────
# 词表里的词已经由 scan_inclusive 给出，这里补的是「词表永远追不上」的形态：
# 一个具体的词换了说法就抓不到，但「形态」能抓到。

#: 感叹 / 起誓形态。宗教类问题几乎都长这样，但词表只列了 `天啊`/`上帝啊` 几种。
#: `bloody hell`、`for Christ's sake`、`swear to God` 全在词表外。
_RE_INTERJ = re.compile(
    r"(天啊|老天|我的天|天呐|上帝|神啊|天杀|该死|见鬼|妈的|卧槽|我靠|尼玛|"
    r"老天爷|菩萨|佛祖|耶稣|基督|真主|安拉|阿门|"
    r"bloody|damn|hell|God|Christ|Jesus|gosh|geez|Lord)")

#: 贬义称谓 / 侮辱 / 死亡表达的常见构词。只用来定位，判断交给 agent。
_RE_DEROG = re.compile(
    r"(娘们|娘娘腔|像.{0,2}女人|女司机|婆妈|婆婆妈妈|基佬|同性恋|残废|瘸子|瞎子|聋子|哑巴|"
    r"傻[子逼瓜]|弱智|智障|神经病|精神病|土鳖|乡巴佬|老外|洋人|洋鬼子|鬼子|阿三|棒子|"
    r"黑鬼|老黑|死[了掉翘]|自杀|上吊|割腕|"
    r"fag|faggot|retard|bitch|cunt|chink|nigger|spaz|lame|psycho|crazy)")

#: 主权 / 地域表述。含**词表故意不收**的形态（`两岸`、`大陆人`、`神州`），
#: 因为收进词表就变成「判定」，而这里只负责「指出这一行在谈这个」。
_RE_GEO = re.compile(
    r"(大陆|内地|台湾|香港|澳门|中港台|两岸|西藏|新疆|藏区|疆|神州|我国|祖国|"
    r"台独|港独|疆独|藏独|光复|六四|"
    r"mainland|Taiwan|Hong ?Kong|Macau|Macao|Tibet|Xinjiang|China)")

#: 敏感词**附近**要给的上下文行数：judge 需要看前后文才判得准
_CTX_LINES = 4


def _mask(text: str) -> str:
    """抹掉 ASS 覆盖标签，保持字符位置不变。"""
    return si._masked(text)


def _scan_line(text: str) -> dict:
    """对一行可见文本出锚点。只给位置与形态，不给判断。"""
    m = _mask(text)
    return {
        "lexicon": [h["term"] for h in si.classify(text)["hits"]],
        "whitelist_hits": [h["term"] for h in si.classify(text)["whitelisted"]],
        "interjection": sorted(set(_RE_INTERJ.findall(m))),
        "derogatory": sorted(set(_RE_DEROG.findall(m))),
        "geo_political": sorted(set(_RE_GEO.findall(m))),
    }


# ── 切片输入（主路径：R11 用切片，和 1–7 类共用同一批切片文件） ──────────────

_SLICE_LINE = re.compile(r"^(\d+)\s*\|\s*([^|]*)\|(.*)$")


def read_slice(path: str) -> list:
    """读 extract_slice 产出的切片。

    切片一行一 block：`<srt_id> | <ass_time> | <英文> | <中文> | <注释>`
    但中文字段里可能有 `|`（译者加的分隔），所以只按前两个 `|` 切，剩下整体算正文。
    """
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.startswith("#") or line.startswith(">"):
                continue
            m = _SLICE_LINE.match(line)
            if not m:
                continue
            sid, when, rest = m.group(1), m.group(2).strip(), m.group(3)
            parts = [p.strip() for p in rest.split("|")]
            en = parts[0] if len(parts) > 0 else ""
            zh = parts[1] if len(parts) > 1 else ""
            rows.append({"srt_id": int(sid), "ass_time": when, "en": en, "zh": zh,
                         "raw": line})
    return rows


# ── ASS/SRT 直读（备用路径：手上没有切片时） ────────────────────────────────

def read_ass(ass_path: str) -> list:
    import pysubs2

    subs = pysubs2.load(ass_path, encoding="utf-8-sig")
    events = list(subs.events)
    known = sum(1 for e in events
                if si.style_to_track(e.style or "") in (si.TRACK_ZH, si.TRACK_EN))
    fallback = bool(events) and known == 0
    rows = []
    for i, e in enumerate(events, 1):
        body = si.clean_ass_text(e.text or "")
        track = si.TRACK_ZH if fallback and si._is_cjk(body) \
            else si.style_to_track(e.style or "")
        if track != si.TRACK_ZH:
            continue
        sec = (e.start or 0) / 1000.0
        rows.append({
            "srt_id": i,
            "ass_time": "%.2f-%.2f" % (sec, (e.end or 0) / 1000.0),
            "en": "", "zh": body, "raw": body,
        })
    return rows


# ── 种子构造 ────────────────────────────────────────────────────────────────

def build_seeds(rows: list, *, base: str = "") -> dict:
    """把行 + 锚点 + 上下文行打包成给 subagent 的种子。

    返回结构里同时有：
      - `anchors`：机器读，每条锚点带 srt_id / 类别 / ass_time / 现译 / 附近英文
      - `segments`：人读，把锚点按**段**归并（相距 ≤ _CTX_LINES 的合成一段），
        每段给一段连续上下文。subagent 按段读，不要按锚点读——
        单看一行判不出「这句是角色在骂人还是复述别人的偏见」。
      - `hint_text` / `instruction`：原样贴进 prompt 的说明段
    """
    anchors = []
    for idx, r in enumerate(rows):
        a = _scan_line(r["zh"])
        if not any(a.values()):
            continue
        for kind in ("lexicon", "whitelist_hits", "interjection",
                     "derogatory", "geo_political"):
            for term in a[kind]:
                anchors.append({
                    "srt_id": r["srt_id"],
                    "ass_time": r["ass_time"],
                    "form": kind,       # lexicon=词表命中 / whitelist_hits=白名单候选
                                        # interjection=感叹起誓 / derogatory=贬义称谓
                                        # geo_political=主权地域
                    "term": term,
                    "zh": r["zh"],
                    "en": r["en"],
                    "row_index": idx,
                })

    # 按 srt_id 归并成段，每段带上下 _CTX_LINES 行
    by_row: dict = {}
    for a in anchors:
        by_row.setdefault(a["row_index"], []).append(a)
    segments = []
    hit_idx = sorted(by_row)
    if hit_idx:
        start = hit_idx[0]
        prev = hit_idx[0]
        groups = []
        for i in hit_idx[1:]:
            if i - prev <= _CTX_LINES:
                prev = i
                continue
            groups.append((start, prev))
            start = prev = i
        groups.append((start, prev))

        for lo, hi in groups:
            ctx_lo = max(0, lo - _CTX_LINES)
            ctx_hi = min(len(rows) - 1, hi + _CTX_LINES)
            seg_anchors = [a for i in range(lo, hi + 1) for a in by_row.get(i, [])]
            segments.append({
                "srt_id_from": rows[lo]["srt_id"],
                "srt_id_to": rows[hi]["srt_id"],
                "context_from": rows[ctx_lo]["srt_id"],
                "context_to": rows[ctx_hi]["srt_id"],
                "anchors": seg_anchors,
                "context": [{"srt_id": rows[i]["srt_id"],
                             "ass_time": rows[i]["ass_time"],
                             "en": rows[i]["en"], "zh": rows[i]["zh"]}
                            for i in range(ctx_lo, ctx_hi + 1)],
            })

    return {
        "base": base,
        "n_rows": len(rows),
        "anchors": anchors,
        "segments": segments,
        "instruction": (
            "下面是**线索**，不是待办清单。每条锚点只表示「这里出现了某种形态」，"
            "不表示「这里是问题」，更不表示「这里该改成什么」。\n"
            "1. 你负责的这一片必须**整片读完**，不许只看 anchors 列出的行；"
            "anchors 只帮你定位，漏掉的敏感表述照样要报。\n"
            "2. 每条锚点自己判断：这行在这个语境下是不是问题？是 L1（换词即可）/ "
            "L2（要改但需看原文）/ L3（原文即如此，只标注）/ 不是问题？\n"
            "3. 位于白名单（form=whitelist_hits）的行，默认判「不是问题」。"
            "若你认为确实该改，写 L3 并给理由——不要直接给替换词。\n"
            "4. 锚点之外你也可以报（清单与正则都追不上的敏感问题），"
            "但必须写清「为什么这算问题」以及「为什么现有清单没收它」。"
        ),
    }


# ── 输出 ────────────────────────────────────────────────────────────────────

_FORM_NOTE = {
    "lexicon": "词表命中",
    "whitelist_hits": "白名单候选（默认不改）",
    "interjection": "感叹/起誓形态",
    "derogatory": "贬义/侮辱/死亡形态",
    "geo_political": "主权/地域表述",
}


def render_md_seed(seed: dict) -> str:
    L = ["# 第 8 类线索（scan_seed）", "",
         f"- 来源：{seed['base'] or '（未标注）'}",
         f"- 行数：{seed['n_rows']}",
         f"- 锚点：{len(seed['anchors'])} 条 / 归并成 {len(seed['segments'])} 段",
         f"- 生成：{datetime.now().isoformat(timespec='seconds')}", "",
         "> **这是线索，不是结论。** 锚点只说明「这里出现了某种形态」，",
         "> 不说明这里有问题，更不说明该怎么改。判断由读全文的 agent 做。", "",
         "## 判定规则（贴进 prompt）", "", "```", seed["instruction"], "```", ""]

    if not seed["segments"]:
        L += ["## 锚点", "", "无。注意：**这不等于这一片没有敏感问题**——",
              "词表与正则都追不上的表述（换了说法的首次/主权/歧视）本来就不会出现在这里。", ""]
        return "\n".join(L)

    for i, seg in enumerate(seed["segments"], 1):
        L += [f"## 段 {i}（锚点 {seg['srt_id_from']}–{seg['srt_id_to']}，"
              f"上下文 {seg['context_from']}–{seg['context_to']}）", ""]
        L += ["| 形态 | 命中 | srt_id |", "|---|---|---|"]
        for a in seg["anchors"]:
            L.append(f"| {_FORM_NOTE.get(a['form'], a['form'])} | `{a['term']}` "
                     f"| {a['srt_id']} |")
        L += ["", "上下文：", "", "| srt_id | ass_time | 英文 | 中文 |",
              "|---|---|---|---|"]
        for c in seg["context"]:
            L.append(f"| {c['srt_id']} | {c['ass_time']} | "
                     f"{(c['en'] or '')[:48]} | {(c['zh'] or '')[:48]} |")
        L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="第 8 类线索（给 subagent 定位用，不做判断）")
    ap.add_argument("target", help="切片 .txt / ASS / SSA / SRT / 目录")
    ap.add_argument("--srt", default="", help="配对 SRT（补英文列，ASS 输入时用）")
    ap.add_argument("--out", default="", help="写 json")
    ap.add_argument("--fmt", default="json", choices=("json", "md"),
                    help="json（贴 prompt）或 md（人读）")
    args = ap.parse_args()

    if not os.path.exists(args.target):
        print(f"[!] 不存在：{args.target}", file=sys.stderr)
        return 2

    low = args.target.lower()
    if low.endswith(".txt"):
        rows = read_slice(args.target)
        base = args.target
    elif low.endswith((".ass", ".ssa")):
        rows = read_ass(args.target)
        base = args.target
    elif low.endswith(".srt"):
        print("[!] 直接扫 SRT 没有意义：本类判的是中文译文，SRT 是英文源。"
              "请给 ASS 或切片。", file=sys.stderr)
        return 2
    else:
        print(f"[!] 认不出输入类型：{args.target}", file=sys.stderr)
        return 2

    if not rows:
        print("[!] 一行都没读出来。切片格式对不上，或 ASS 的中文轨一行都没有——"
              "**这不是「干净」，是没扫到**，请先查切片。", file=sys.stderr)
        return 2

    seed = build_seeds(rows, base=base)
    text = render_md_seed(seed) if args.fmt == "md" else \
        json.dumps(seed, ensure_ascii=False, indent=1)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[out] {args.out}", file=sys.stderr)
    else:
        print(text)

    print(f"[*] {len(rows)} 行 → {len(seed['anchors'])} 锚点 / "
          f"{len(seed['segments'])} 段（线索，非结论）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
