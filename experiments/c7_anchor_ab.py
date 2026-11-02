#!/usr/bin/env python3
"""category7 锚点实测：A(无锚点) vs B(形态锚点) × E02/E03/E04

目的不是评「锚点准不准」（锚点本来就不做判断），而是量化：
  1. B 多列出多少行？（subagent 必须多看多少）
  2. 两臂各自命中多少「第 7 类真问题」？（锚点有没有让人漏看）
  3. 两臂结论冲突处，谁对？（这是唯一能判优劣的指标）

v2 修正（第一版锚点仅 0.8%，且抽样里多为「文言单字」误报）：
  - 文言残留：单字「之其乃亦」→ 词组「颇为/甚为/可谓/不失为/而已/焉/矣」
    （「其实」「之一」是自然汉语，单字匹配等于噪声）
  - 新增「长度比 + 绝对字数差」双判据，比值在短句上不稳
  - 导出每集锚点 TSV，供 B 臂 subagent 直接消费
"""
import os, re, sys, json, random
from collections import Counter

ROOT = r"C:\Users\VerNe\Downloads\修车房测试核对"

CJK = re.compile(r"[\u4e00-\u9fff]")
TAG = re.compile(r"\{[^}]*\}")


def strip_tags(s):
    return TAG.sub("", s)


def load_ass(path):
    lines = open(path, "rb").read().decode("utf-8-sig").splitlines()
    en, zh = [], []
    for l in lines:
        if not l.startswith("Dialogue:"):
            continue
        p = l[len("Dialogue:"):].split(",", 9)
        style, text = p[3], p[9]
        t = p[1]
        h, m, s = t.split(":")
        sec = round(int(h) * 3600 + int(m) * 60 + float(s), 2)
        rec = dict(style=style, t=sec, raw=text, txt=strip_tags(text))
        if "英" in style and "文" in style:
            en.append(rec)
        elif "中" in style and "文" in style:
            zh.append(rec)
    return en, zh


# ────────────────────────────── 锚点（方案 B） ──────────────────────────────

PARTICLES = "的了呢吧啊呀嘛哦噢哈"

# 只保留真正在口语旁白里罕见的书面/文言词组，不用单字
WRITTEN = [
    ("书面连接", r"(则|于是|因此|故而|然而|并且|从而|进而|此外|与此同时|由此可见)"),
    ("文言残留", r"(颇为|甚为|可谓|不失为|而已|焉|矣|之至|尤为)"),
    ("被动欧化", r"(受到|得以|加以|予以|遭到了)"),
    ("系词冗余", r"(是[一个位种名场]|进行的|做出了|产生了)"),
    ("名物化", r"(性|化|度|感)的(问题|工作|事情|东西|过程|状态)"),
]


def anchor_row(zh_rec, en_rec, ratio_high=2.9, diff_min=9, dur_max=1.4,
               zh_len_min=9, min_hits=2):
    """返回 hits 列表，空表示不锚。"""
    zh = zh_rec["txt"]
    en = en_rec["txt"] if en_rec else ""
    hits = []
    nzh = len(CJK.findall(zh))
    nen = len(re.findall(r"[A-Za-z']+", en))

    # 1) 中英严重不匹配：比值离谱 或 绝对字数超出
    if nen >= 5 and nzh >= 4:
        r = nzh / max(1, nen)
        if r > ratio_high or r < 0.45 or (nzh - nen * 1.6) >= diff_min:
            hits.append("长度比:%.1f(%d/%d)" % (r, nzh, nen))

    # 2) 句末语气词堆叠（「的了呢」「吧啊」）
    tail = zh.rstrip("。！？…，、 　~～")
    np = 0
    while tail and tail[-1] in PARTICLES:
        np += 1
        tail = tail[:-1]
    if np >= 2:
        hits.append("语气堆叠:%d" % np)

    # 3) 书面/文言/欧化/名物化（词组级）
    for name, pat in WRITTEN:
        if re.search(pat, zh):
            hits.append(name)

    # 4) 时长极短且字数多（信息密度过高，念不完）
    dur = zh_rec.get("dur")
    if dur and dur < dur_max and nzh >= zh_len_min:
        hits.append("密度:%.1fs/%d字" % (dur, nzh))

    # 5) 中文里残留半角标点
    if re.search(r"[\u4e00-\u9fff][,;:?!]", zh):
        hits.append("半角标点")

    return (hits if len(hits) >= min_hits else [])


def pair_by_time(zh, en):
    """按时间戳配对中英轨，返回 {zh下标: en记录}。

    E03 的中文轨从第 149 行起多一条零时长碎片（"是的" 与上一行同起点），
    导致后面全部下标错位、最大偏 39.84s。用下标配对会把两个不相关的句子
    拼在一起算「长度比」，制造 100% 假锚点。这里按时间戳就近匹配。
    """
    emap = {}
    for i, z in enumerate(zh):
        best, bestd = None, 1e9
        for e in en:
            d = abs(e["t"] - z["t"])
            if d < bestd:
                best, bestd = e, d
        if best is not None and bestd <= 0.05:
            emap[i] = best
    return emap


def build_anchor_rows(zh, en):
    """给每行算 dur，再判定锚点。返回 [(idx, hits, zh_rec, en_rec, warn)]"""
    for i, r in enumerate(zh):
        nxt = zh[i + 1]["t"] if i + 1 < len(zh) else r["t"] + 2
        r["dur"] = round(nxt - r["t"], 2)
    emap = pair_by_time(zh, en)
    out = []
    for i, r in enumerate(zh):
        # 零时长碎片（与上一行同起点）本身就是结构缺陷，不出锚点
        if i > 0 and r["dur"] <= 0.0:
            continue
        e = emap.get(i)
        h = anchor_row(r, e)
        if h:
            out.append((i + 1, h, r, e))
    return out


def main():
    print("=" * 78)
    print("category7 锚点实测  A=无锚点  B=形态锚点   (v2 词组级)")
    print("=" * 78)

    stats = []
    for ep in ("S06E02实测", "S06E03实测", "S06E04实测"):
        p = os.path.join(ROOT, ep, ep.replace("实测", "") + ".eng.ass")
        en, zh = load_ass(p)
        anchored = build_anchor_rows(zh, en)
        total = len(zh)
        n_anchor_lines = len(anchored)
        n_anchor_items = sum(len(h) for _, h, _, _ in anchored)

        form_counter = Counter()
        for _, hits, _, _ in anchored:
            for f in hits:
                form_counter[f.split(":")[0]] += 1

        nslice = max(1, round(total / 700))
        per_slice = [0] * nslice
        for idx, _, _, _ in anchored:
            per_slice[min(nslice - 1, (idx - 1) * nslice // total)] += 1

        stats.append(dict(ep=ep, total=total, anchor=n_anchor_lines,
                          items=n_anchor_items, forms=form_counter,
                          nslice=nslice, per_slice=per_slice))

        print("\n%s  行数=%d  锚点行=%d (%.1f%%)  锚点项=%d"
              % (ep, total, n_anchor_lines, 100.0 * n_anchor_lines / max(1, total),
                 n_anchor_items))
        print("   形态分布: %s" % dict(form_counter.most_common()))

        random.seed(7)
        smp = random.sample(anchored, min(10, len(anchored)))
        print("   —— 抽样 ——")
        for idx, h, r, e in sorted(smp, key=lambda x: x[0]):
            entxt = (e["txt"] if e else "")[:46]
            print("   #%-4d %-30s %s"
                  % (idx, ",".join(x.split(":")[0] for x in h), r["txt"][:36]))
            print("         EN: %s" % entxt)

        # 导出 B 臂输入（锚点清单），供 subagent 用
        outp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "_anchor_%s.tsv" % ep.replace("实测", ""))
        with open(outp, "w", encoding="utf-8") as f:
            f.write("idx\thits\ttime\tzh\ten\n")
            for idx, h, r, e in anchored:
                f.write("%d\t%s\t%.2f\t%s\t%s\n"
                        % (idx, "|".join(h), r["t"], r["txt"],
                           (e["txt"] if e else "")))

    print("\n" + "=" * 78)
    tot = sum(s["total"] for s in stats)
    anc = sum(s["anchor"] for s in stats)
    print("三集合计 %d 行，方案 B 锚出 %d 行（%.1f%%）"
          % (tot, anc, 100.0 * anc / tot))
    print("方案 A：subagent 通读全部 %d 行，锚点 0" % tot)

    with open("_c7_stats.json", "w", encoding="utf-8") as f:
        json.dump([{k: (dict(v) if isinstance(v, Counter) else v)
                    for k, v in s.items()} for s in stats],
                  f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
