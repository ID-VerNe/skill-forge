#!/usr/bin/env python3
"""2x3 对照比对：读两臂 JSON，产出对照表。

用法：python c7_compare.py
预期文件：_arm_A_S06E02.json / _arm_B_S06E02.json / ... （三集）
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EPS = ["S06E02", "S06E03", "S06E04"]


def load(tag, ep):
    p = os.path.join(HERE, "_arm_%s_%s.json" % (tag, ep))
    if not os.path.exists(p):
        return None
    txt = open(p, encoding="utf-8").read().strip()
    # 容错：subagent 可能包 ```json 围栏
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        if txt.lstrip().startswith("json"):
            txt = txt.lstrip()[4:]
    try:
        return json.loads(txt)
    except Exception as e:
        print("  !! %s 解析失败: %s" % (p, e))
        return []


def main():
    rows = []
    for ep in EPS:
        A = load("A", ep)
        B = load("B", ep)
        if A is None or B is None:
            print("%s: 缺文件 A=%s B=%s" % (ep, A is not None, B is not None))
            continue
        ai = {x["idx"] for x in A}
        bi = {x["idx"] for x in B}
        both = ai & bi
        onlyA = ai - bi
        onlyB = bi - ai
        rows.append(dict(ep=ep, na=len(A), nb=len(B),
                         both=len(both), onlyA=len(onlyA), onlyB=len(onlyB),
                         A=A, B=B, both_idx=sorted(both),
                         onlyA_idx=sorted(onlyA), onlyB_idx=sorted(onlyB)))
        print("\n%s  A=%d  B=%d  |  交集=%d  A独有=%d  B独有=%d"
              % (ep, len(A), len(B), len(both), len(onlyA), len(onlyB)))

        byidx = {}
        for x in A + B:
            byidx.setdefault(x["idx"], {})[x.get("_arm", "")] = x
        if both:
            print("  —— 交集行（A 侧 / B 侧说明）——")
            for i in sorted(both):
                a = next(x for x in A if x["idx"] == i)
                b = next(x for x in B if x["idx"] == i)
                print("   #%-4d A:%s | B:%s" % (i, a["issue"][:26], b["issue"][:26]))
        if onlyA:
            print("  —— 仅 A 报出（B 漏了）——")
            for i in sorted(onlyA):
                a = next(x for x in A if x["idx"] == i)
                print("   #%-4d %s | %s" % (i, a["zh"][:30], a["issue"][:34]))
        if onlyB:
            print("  —— 仅 B 报出（A 漏了 / 或 B 多报）——")
            for i in sorted(onlyB):
                b = next(x for x in B if x["idx"] == i)
                flag = "[锚]" if b.get("from_anchor") else ""
                print("   #%-4d %s%s | %s" % (i, flag, b["zh"][:30], b["issue"][:34]))

    if not rows:
        return
    print("\n" + "=" * 70)
    print("%-10s %6s %6s %6s %8s %8s" % ("集", "A条", "B条", "交集", "A独有", "B独有"))
    for r in rows:
        print("%-10s %6d %6d %6d %8d %8d"
              % (r["ep"], r["na"], r["nb"], r["both"], r["onlyA"], r["onlyB"]))
    print("%-10s %6d %6d %6d %8d %8d"
          % ("合计", sum(r["na"] for r in rows), sum(r["nb"] for r in rows),
             sum(r["both"] for r in rows), sum(r["onlyA"] for r in rows),
             sum(r["onlyB"] for r in rows)))

    with open(os.path.join(HERE, "_c7_compare.json"), "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items() if k not in ("A", "B")} for r in rows],
                  f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
