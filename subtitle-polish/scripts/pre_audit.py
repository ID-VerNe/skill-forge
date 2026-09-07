# -*- coding: utf-8 -*-
"""三轨预审：gemini-3.1 + glm-5.2 + 规则检查（check_fluency）。

stage 2.7（标点预检后、审计前）的可选预处理。廉价广撒网首轮，给 Claude
子 agent（stage 3 审计）提供总览线索。输出**只是线索**，不进 fixes.json /
audit-report.md，必须经 Claude 独立审计 + verify 后才能进报告。

三轨：
  轨 1  gemini-3.1-flash-lite：N=5 passes，取 intersection。快稳，信达雅强。
  轨 2  glm-5.2：N=5 passes，reasoning=none，取 intersection。慢但抓硬伤。
  轨 3  check_fluency：纯规则翻译腔检查，秒级，召回 100%。

收窄 prompt（禁字符损坏/专名/原文拼写）—— probe 验证过降假阳 82%。

模型可用性：启动时 ping，不可用（404/502/超时）的轨跳过并 log。缺 env
key 的轨跳过，其余照常（不崩）。

用法：
  python pre_audit.py <slice.txt> [--context context.md] [--n 5] \
      [--out .subtitle-polish/reports] [--max-tokens 16000]

环境变量：
  GLM_API_KEY      必填（两 LLM 轨共用），缺则 LLM 轨全跳过
  GLM_API_URL      默认 http://localhost:37183/v1/chat/completions
  GLM_MODEL        默认 glm-5.2
  GEMINI_MODEL     默认 gemini-3.1-flash-lite

详见 references/pre-audit.md（用法/总览字段/安全闸/模型强弱图/带歪风险）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Tuple

import requests

from check_fluency import check_slice as rule_check_slice

DEFAULT_API_URL = "http://localhost:37183/v1/chat/completions"
DEFAULT_GLM_MODEL = "glm-5.2"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
DEFAULT_N = 5

# 字符损坏/异体字/错别字类候选——GLM 这类 82% 假阳，直接丢弃不进高置信。
DISCARD_CATEGORIES = {"字符损坏", "异体字", "错别字", "原文拼写错误", "专名错误", "专名错误/不一致"}

# 专名类候选——标 needs_web_verify，Claude 不得盲信 LLM 建议
PROPER_NOUN_HINTS = {"专名", "车型", "品牌", "人名", "地名"}

_SESSION = requests.Session()
# 本地 LLM API 走 localhost，忽略 HTTP_PROXY 环境变量（避免 clash 代理 7897
# 关掉时连不上）。
_SESSION.trust_env = False


def get_config() -> Dict:
    key = os.environ.get("GLM_API_KEY", "")
    return {
        "api_url": os.environ.get("GLM_API_URL", DEFAULT_API_URL),
        "glm_model": os.environ.get("GLM_MODEL", DEFAULT_GLM_MODEL),
        "gemini_model": os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        "api_key": key,
    }


def ping_model(cfg: Dict, model: str) -> Tuple[bool, str]:
    """tiny ping 探测模型可用性。返回 (ok, reason)。"""
    if not cfg["api_key"]:
        return False, "GLM_API_KEY 未设"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "temperature": 0,
    }
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg['api_key']}"}
    try:
        r = _SESSION.post(cfg["api_url"], json=body, headers=headers, timeout=30)
        if r.status_code == 200:
            return True, ""
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"


def call_llm(cfg: Dict, model: str, prompt: str, reasoning: str = "none",
             max_tokens: int = 16000, retries: int = 4) -> Tuple[str, Dict]:
    """One-shot chat call in JSON output mode. reasoning_effort:
    - glm-5.2: 'none' 关 thinking，全部 token 给 answer
    - gemini-3.1: 不能关 thinking，传 'default'（不设 reasoning_effort）"""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if reasoning != "default":
        body["reasoning_effort"] = reasoning
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg['api_key']}"}
    last_err = ""
    for i in range(retries):
        r = _SESSION.post(cfg["api_url"], json=body, headers=headers, timeout=600)
        if r.status_code == 429:
            w = 10 * (i + 1)
            print(f"  [429] wait {w}s", file=sys.stderr)
            time.sleep(w)
            continue
        if r.status_code != 200:
            last_err = f"HTTP {r.status_code}: {r.text[:120]}"
            time.sleep(5 * (i + 1))
            continue
        j = r.json()
        ch = j["choices"][0]
        content = ch["message"].get("content", "") or ""
        return content, {"finish_reason": ch.get("finish_reason"),
                         "usage": j.get("usage")}
    raise RuntimeError(f"LLM call ({model}) failed: {last_err}")


def build_audit_prompt(slice_text: str, ctx: str = "") -> str:
    """收窄版审计 prompt。只报语义反转/语境错译/信达雅，禁字符损坏/专名/原文拼写。
    probe 验证过降假阳 82%。与 audit.tmpl 的 Claude 版不同。"""
    ctx = ctx or "（无项目背景。基于上下文与领域知识判断。）"
    return f"""你是字幕质量审计员。审计一段双语 ASS 字幕切片，找出翻译问题。

## 输入

切片（一 block 一行），格式：
  <srt_id> | <ass_time> | <英文> | <中文> | <注释>
srt_id 是每行 | 分隔的第一个字段，直接读取，不要数行推算。每行带 ass_time 时间戳，输出里必须照抄，方便人对照视频定位。

{slice_text}

## 项目背景（只放中性领域事实，不放翻译判断结论）

{ctx}

## 检查范围（只报三类，禁字符损坏/专名/原文拼写）

A. **语义反转**（高）：否定/时态/程度/胜负颠倒。如 `can't` 译成肯定、`losing` 译成"输了"实为"甩开"。
B. **语境错译**（中）：词选对字面但场景不符。如 `get to A&E` 译"滚去急诊室"（get lost 贬义）、`勾搭`用于非男女关系语境、`drill`（手电钻）译成"播种机"。
C. **信达雅**（低，谨慎报）：
   - **信**：程度/语气微偏（非硬伤）、情绪标记丢失（Oh/Well/Honestly 没还原）、未说完的半句被补全
   - **达**：翻译腔/书面语（进行/实施/所以/因此）、机翻特征（的的/了了）、欧式句法、冗余连接词
   - **雅**：用词书面不口语（购置→买）、不符合中文语序、俚语/口语梗被译成书面陈述、生造词、机翻音译（heritage line→利涅）

## 严禁报以下（这是你的已知短处，会幻觉）

- ❌ **字符损坏/异体字/错别字**：不要说"X 误写为 Y""生僻异体字""打字错误"。中文行的每个字都以切片文件为准，切片里是什么字就是什么字，你不要纠正任何中文字。你之前多次把正确的"弗""谢""粉""基"误报为损坏，全是错的。
- ❌ **专名纠正**：不要说"车型名应为 X""品牌名拼写错""人名应为 Y"。你对 2026 年新车/冷门型号/品牌名的知识会过时或编造（你曾把真实的 Ferrari Luce、Jaguar Type 01 误判为错误）。专名留给有联网能力的验证 agent 处理。
- ❌ **原文拼写纠正**：不要纠正 ass 英文行里的拼写（如 airs/asks、Lucian/Luce）。srt 与 ass 同源，你不能作权威。

**只报语义、语境、信达雅三类。把判断力集中在这三轴上。**

## 要求

- 只报真实问题，不报"可接受但非最优"的（信达雅类谨慎报）
- 口语化风格（如"压根""破烂""刷一下"）是风格不是问题，不要报
- srt_id 必须准确（这是定位键，错了修复脚本找不到行）
- ass_time 必须从切片行直接照抄
- 拿不准的问题在 problem 字段里标"（存疑）"
- 不要幻觉：没把握就别报，宁可漏报不要误报

## 输出格式（JSON 对象，严格按此 schema）

{{
  "findings": [
    {{
      "srt_id": <整数，切片行第一个字段>,
      "ass_time": "<照抄切片行的时间戳，如 0:01:16.56-0:01:18.00>",
      "category": "<语义反转 | 语境错译 | 信 | 达 | 雅>",
      "severity": "<高 | 中 | 低>",
      "english": "<英文原文>",
      "current": "<当前中文译文>",
      "problem": "<一句话说明>",
      "suggestion": "<建议译文或改法>"
    }}
  ]
}}

无问题则输出：{{"findings": []}}。只输出 JSON，不要任何额外文字。
"""


SLICE_LINE_RE = re.compile(
    r"^(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|"
)


def parse_slice(path: Path) -> Dict[str, Dict]:
    """ass_time -> {srt_id, english, current} 索引。用于反查权威 srt_id
    + 丢弃幻觉时间戳行。"""
    idx = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\n")
        if not line or line.startswith("#") or line.startswith("slice"):
            continue
        m = SLICE_LINE_RE.match(line)
        if not m:
            continue
        idx[m.group(2).strip()] = {
            "srt_id": int(m.group(1)),
            "english": m.group(3).strip(),
            "current": m.group(4).strip(),
        }
    return idx


def parse_findings(content: str) -> Tuple[List[Dict], str]:
    """解析 JSON 对象。robust to code-fence wrapping；失败则取最外层 {...}。"""
    if not content or not content.strip():
        return [], "empty content"
    s = content.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return [], f"no JSON object found (len={len(content)})"
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return [], f"JSONDecodeError: {e}"
    # 接受两种形状：{"findings": [...]} 或 bare [...]
    if isinstance(obj, list):
        findings = obj
    elif isinstance(obj, dict):
        findings = obj.get("findings")
    else:
        findings = None
    if not isinstance(findings, list):
        return [], (f"no 'findings' array (top-level: "
                    f"{type(obj).__name__})")
    return findings, ""


def run_llm_track(cfg: Dict, model: str, reasoning: str, prompt: str,
                  slice_idx: Dict, n: int, label: str) -> Dict:
    """跑一个 LLM 轨 N passes，返回 {by_sid, intersection, union, vote_ge2, passes_raw}。"""
    print(f"\n--- 轨：{label} ({model}, reasoning={reasoning}, N={n}) ---",
          file=sys.stderr)
    passes = []
    for i in range(n):
        t0 = time.time()
        try:
            content, meta = call_llm(cfg, model, prompt, reasoning=reasoning)
        except RuntimeError as e:
            print(f"  pass {i+1}: ERR {e}", file=sys.stderr)
            continue
        rt = time.time() - t0
        raw_findings, perr = parse_findings(content)
        # 反查 srt_id + 丢弃幻觉时间戳行
        clean = []
        for f in raw_findings:
            at = str(f.get("ass_time") or "").strip()
            if not at or at not in slice_idx:
                continue
            f["srt_id"] = slice_idx[at]["srt_id"]  # 权威覆盖
            f["slice_english"] = slice_idx[at]["english"]
            f["slice_current"] = slice_idx[at]["current"]
            clean.append(f)
        passes.append(clean)
        u = meta.get("usage", {}) or {}
        print(f"  pass {i+1}: rt={rt:.1f}s finish={meta.get('finish_reason')} "
              f"raw={len(raw_findings)} clean={len(clean)}", file=sys.stderr)
        if perr:
            print(f"    parse err: {perr}", file=sys.stderr)
        if meta.get("finish_reason") == "length":
            print(f"    WARN: truncated (finish=length)", file=sys.stderr)
    by_sid = defaultdict(list)
    for findings in passes:
        for f in findings:
            by_sid[f["srt_id"]].append(f)
    n_actual = len(passes) or 1
    counts = {sid: len(v) for sid, v in by_sid.items()}
    return {
        "by_sid": by_sid,
        "intersection": {sid for sid, c in counts.items() if c == n_actual},
        "union": set(by_sid.keys()),
        "vote_ge2": {sid for sid, c in counts.items() if c >= 2},
        "n": n_actual,
    }


def classify_candidate(f: Dict) -> Dict:
    """给候选加安全闸标记。字符损坏类丢弃；专名类标 needs_web_verify。"""
    cat = str(f.get("category", ""))
    # 丢弃：字符损坏/异体字/错别字/原文拼写（GLM 这类 82% 假阳）
    if cat in DISCARD_CATEGORIES:
        return {"discard": True}
    out = {"discard": False}
    # 专名类标 needs_web_verify
    if any(h in cat for h in PROPER_NOUN_HINTS):
        out["needs_web_verify"] = True
    return out


def aggregate(gemini_res: Dict, glm_res: Dict, rule_hits: List[Dict]) -> Dict:
    """三轨聚合。高置信 = gemini intersection ∪ glm intersection ∪ rule。
    中置信 = vote≥3。每条标 source + 轨内稳定性。"""
    candidates = {}  # srt_id -> {sources: [], findings: {}}

    def add(sid, source, f, stability):
        if sid not in candidates:
            candidates[sid] = {"srt_id": sid, "sources": [], "findings": {}}
        candidates[sid]["sources"].append({
            "track": source,
            "stability": stability,
            "category": f.get("category"),
            "severity": f.get("severity"),
            "problem": f.get("problem"),
            "suggestion": f.get("suggestion"),
            "english": f.get("english") or f.get("slice_english"),
            "current": f.get("current") or f.get("slice_current"),
            "ass_time": f.get("ass_time"),
        })

    # gemini intersection（高置信）+ vote_ge2（中置信）
    for sid, findings in gemini_res.get("by_sid", {}).items():
        cnt = len(findings)
        n = gemini_res.get("n", 1)
        if sid in gemini_res.get("intersection", set()):
            add(sid, "gemini-3.1", findings[0], f"{cnt}/{n} (intersection)")
        elif cnt >= 3:
            add(sid, "gemini-3.1", findings[0], f"{cnt}/{n} (vote>=3)")
    # glm intersection + vote_ge2
    for sid, findings in glm_res.get("by_sid", {}).items():
        cnt = len(findings)
        n = glm_res.get("n", 1)
        if sid in glm_res.get("intersection", set()):
            add(sid, "glm-5.2", findings[0], f"{cnt}/{n} (intersection)")
        elif cnt >= 3:
            add(sid, "glm-5.2", findings[0], f"{cnt}/{n} (vote>=3)")
    # rule（全收，高置信）
    for r in rule_hits:
        sid = r["srt_id"]
        for h in r["hits"]:
            add(sid, "rule", {
                "category": h["axis"],
                "severity": h.get("confidence") == "low" and "低" or "中",
                "problem": f"{h['rule']}：{h['detail']}",
                "suggestion": h["suggestion"],
                "english": r["english"],
                "current": r["current"],
                "ass_time": r["ass_time"],
            }, "rule (100%)")

    # 安全闸：分类丢弃/标 needs_web_verify
    high_conf = []
    discarded = []
    for sid, c in candidates.items():
        # 取第一条 finding 的类别做分类判断
        if c["sources"]:
            verdict = classify_candidate(c["sources"][0])
            if verdict.get("discard"):
                discarded.append(c)
                continue
            if verdict.get("needs_web_verify"):
                c["needs_web_verify"] = True
        high_conf.append(c)

    return {"high_confidence": high_conf, "discarded": discarded}


def build_summary(agg: Dict, gemini_res: Dict, glm_res: Dict,
                  rule_hits: List[Dict]) -> str:
    """总览摘要给 subagent 读。"""
    hc = agg["high_confidence"]
    lines = []
    lines.append(f"# 预审总览\n")
    lines.append(f"高置信候选：{len(hc)} 条")
    lines.append(f"已丢弃（字符损坏/专名/原文拼写类）：{len(agg['discarded'])} 条\n")
    # 按类别分布
    from collections import Counter
    cat_counts = Counter()
    for c in hc:
        for s in c["sources"]:
            cat_counts[s["category"]] += 1
    if cat_counts:
        lines.append("## 按类别分布")
        for cat, cnt in cat_counts.most_common():
            flag = ""
            if any(h in cat for h in PROPER_NOUN_HINTS):
                flag = "  ← 需联网核实（不得盲信 LLM 建议）"
            lines.append(f"- {cat}: {cnt}{flag}")
        lines.append("")
    # 专名类强制提示
    propernoun = [c for c in hc if c.get("needs_web_verify")]
    if propernoun:
        lines.append(f"## 专名类候选（{len(propernoun)} 条，必须联网核实）")
        lines.append("GLM 专名建议 100% 是编造（probe 实测：Ferrari Luce→Luxion、Jaguar Type 01→Type 00 全错）。")
        lines.append("Claude 子 agent 必须自己联网核实，不得直接采纳 LLM 建议。\n")
    # 高置信明细
    lines.append("## 高置信候选明细")
    for c in sorted(hc, key=lambda x: x["srt_id"]):
        s0 = c["sources"][0]
        lines.append(f"### srt {c['srt_id']}  [{s0['category']}/{s0['severity']}]")
        lines.append(f"- ass_time: {s0['ass_time']}")
        lines.append(f"- 英文: {s0['english']}")
        lines.append(f"- 现译: {s0['current']}")
        lines.append(f"- 问题: {s0['problem']}")
        lines.append(f"- 建议: {s0['suggestion']}")
        srcs = ", ".join(f"{s['track']}({s['stability']})" for s in c["sources"])
        lines.append(f"- source: {srcs}")
        if c.get("needs_web_verify"):
            lines.append(f"- ⚠ needs_web_verify: true")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slice", help="切片文件（extract_slice.py 输出）")
    ap.add_argument("--context", help="项目背景 .md（中性领域事实）")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="每个 LLM 轨的 pass 数")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--out", help="输出目录（reports/），写 pre-audit-<stem>.json + .summary.md")
    ap.add_argument("--no-gemini", action="store_true", help="跳过 gemini 轨")
    ap.add_argument("--no-glm", action="store_true", help="跳过 glm 轨")
    ap.add_argument("--no-rule", action="store_true", help="跳过规则轨")
    args = ap.parse_args()

    cfg = get_config()
    slice_path = Path(args.slice)
    slice_text = slice_path.read_text(encoding="utf-8")
    slice_idx = parse_slice(slice_path)
    ctx = Path(args.context).read_text(encoding="utf-8") if args.context else ""
    prompt = build_audit_prompt(slice_text, ctx)
    stem = slice_path.stem

    print(f"切片：{slice_path.name}  ({len(slice_text)} chars, {len(slice_idx)} rows)",
          file=sys.stderr)

    gemini_res, glm_res = {}, {}
    rule_hits = []

    # 轨 1：gemini-3.1
    if not args.no_gemini:
        ok, reason = ping_model(cfg, cfg["gemini_model"])
        if ok:
            gemini_res = run_llm_track(
                cfg, cfg["gemini_model"], "default", prompt, slice_idx,
                args.n, f"gemini-3.1 ({cfg['gemini_model']})")
            print(f"  gemini intersection={len(gemini_res.get('intersection', set()))} "
                  f"union={len(gemini_res.get('union', set()))}", file=sys.stderr)
        else:
            print(f"  gemini 轨跳过：{reason}", file=sys.stderr)

    # 轨 2：glm-5.2
    if not args.no_glm:
        ok, reason = ping_model(cfg, cfg["glm_model"])
        if ok:
            glm_res = run_llm_track(
                cfg, cfg["glm_model"], "none", prompt, slice_idx,
                args.n, f"glm-5.2 ({cfg['glm_model']})")
            print(f"  glm intersection={len(glm_res.get('intersection', set()))} "
                  f"union={len(glm_res.get('union', set()))}", file=sys.stderr)
        else:
            print(f"  glm 轨跳过：{reason}", file=sys.stderr)

    # 轨 3：规则检查
    if not args.no_rule:
        print(f"\n--- 轨：check_fluency（规则，无 LLM）---", file=sys.stderr)
        rule_hits = rule_check_slice(slice_path, len_ratio=False)
        print(f"  rule hits={len(rule_hits)} 行", file=sys.stderr)

    if not (gemini_res or glm_res or rule_hits):
        print("所有轨都跳过/无结果，退出。", file=sys.stderr)
        sys.exit(1)

    agg = aggregate(gemini_res, glm_res, rule_hits)
    summary = build_summary(agg, gemini_res, glm_res, rule_hits)

    # 正交性
    g_inter = gemini_res.get("intersection", set())
    l_inter = glm_res.get("intersection", set())
    overlap = g_inter & l_inter
    if g_inter and l_inter:
        total = g_inter | l_inter
        ratio = len(overlap) / len(total) if total else 0
        print(f"\n正交性：gemini∩glm intersection 重叠 {len(overlap)}/{len(total)} "
              f"({ratio:.0%})", file=sys.stderr)
        if ratio > 0.20:
            print(f"  WARN: 重叠 >20%，模型行为可能变了，复查", file=sys.stderr)

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"pre-audit-{stem}.json"
        payload = {
            "slice": str(slice_path),
            "n": args.n,
            "gemini": {"intersection": sorted(g_inter),
                       "union": sorted(gemini_res.get("union", set()))},
            "glm": {"intersection": sorted(l_inter),
                    "union": sorted(glm_res.get("union", set()))},
            "rule_hits": len(rule_hits),
            "high_confidence": agg["high_confidence"],
            "discarded": agg["discarded"],
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        sum_path = out_dir / f"pre-audit-{stem}.summary.md"
        sum_path.write_text(summary, encoding="utf-8")
        print(f"\n写：{json_path}\n     {sum_path}", file=sys.stderr)
    else:
        print(summary)


if __name__ == "__main__":
    main()
