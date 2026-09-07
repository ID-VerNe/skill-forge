# -*- coding: utf-8 -*-
"""precheck_punct.py — 标点规范化预检。

对照 translate_principle/subtitle pipeline 的标点预处理流程，检测成品 ASS 里
标点不一致的行（pipeline 产物不应出现的标点残留）。

规则来源（pipeline 三道处理的合并目标态）：
  core/stages/polish_stage.py::postprocess_translation()
  post-process/02-post_process_ass.py::clean_single_line()
  core/srt_utils.py::clean_content()

核心规则（在 pipeline 基础上加了省略号感知/注释括号收窄/缩写点保护，见
references/punct-rules.md）：
  0. 省略号感知：CJK 邻接的 ... → …（尾 CJK...、首 ...CJK、数字间 37...37403），
     不当英文点删空格
  1. …… → …（全省略号归一为半省略号）
  2. ，。、 → 空格（中文逗号/句号/顿号）
  3. 英文 , . → 空格，仅当左右都不是数字（保护 3.14、1,000）；
     缩写点保护：字母.字母（如 J.R.）的点不删
  4. 多空格 → 单空格
  5. 连续横杠 -\\s*-+ → - 合并
  6. 注释括号删除（收窄）：只删中文注释括号 （注：…）/（旁白…），保留
     (EMU)/(机务段)/纯数字括号（主修有意加的译注）

pipeline 保留不动：! ！ ? ？ ; ； ' " ' ' " " … 以及数字间的 . ,

用法:
  python precheck_punct.py <ass_or_dir> [--out .subtitle-polish/reports] [--accept]
  --dry-run（默认）：只出报告，不改文件
  --accept：按规则修复并写回（写 log.jsonl）
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pysubs2

from lib.tags import extract_leading_tags
from lib.log import append_log, make_batch_id
from lib.paths import resolve_work_dir

# CJK 范围（基本汉字）
CJK = "[一-鿿]"


def _normalize_ellipsis(body: str) -> str:
    """省略号感知：CJK 邻接的 ... → …（在点号删除规则之前跑）。

    避免后续 (?<!\\d)[.,](?!\\d) 把 ... 当 3 个英文点删成空格。
    """
    # CJK 后接 ...（尾）：CJK... → CJK…
    body = re.sub(rf"({CJK})\.\.\.", r"\1…", body)
    # 行首 ... 紧跟 CJK：...CJK → …CJK
    body = re.sub(rf"^\.\.\.(?={CJK})", "…", body)
    # 数字间 37... 37403（车号口误自纠）：37...37403 → 37… 37403
    body = re.sub(r"(\d)\.\.\.\s*(?=\d)", r"\1… ", body)
    return body


def _delete_note_parens(body: str) -> str:
    """删中文注释括号（收窄版）：只删 （注：…）/（旁白…） 这类泄漏进正文的注释。

    保留 (EMU)/(机务段)/纯数字括号 —— 主修有意加的译注。
    pipeline 原规则 [\\(（][^\\)）]*[\\)）] 删所有括号，太宽。
    """
    body = re.sub(r"[（(]\s*注[：:].*?[）)]", "", body)
    body = re.sub(r"[（(]\s*旁白.*?[）)]", "", body)
    return body


def normalize_punct(text: str) -> str:
    """对中文行标点做规范化，返回规范化后的文本。只作用于可见文本，保留前导 ASS 标签。"""
    tags, body = extract_leading_tags(text)
    body = _normalize_chinese_body(body)
    return "".join(tags) + body


def _normalize_chinese_body(body: str) -> str:
    """中文可见文本的标点归一（pipeline postprocess_translation + 修正）。"""
    # 0. 省略号感知（先于点号删除，避免 ... 被删成空格）
    body = _normalize_ellipsis(body)
    # 1. 全省略号归一
    body = body.replace("……", "…")
    # 2. 中文标点删空格
    body = re.sub(r"[，。、]", " ", body)
    # 3. 非数字间英文点删空格（缩写点 J.R. 保护）
    body = _delete_non_digit_eng_punct(body)
    # 4. 多空格合并
    body = re.sub(r" {2,}", " ", body)
    # 5. 连续横杠合并
    body = re.sub(r"-\s*-+", "-", body)
    # 6. 注释括号删除（收窄）
    body = _delete_note_parens(body)
    body = body.strip()
    return body


def _delete_non_digit_eng_punct(body: str) -> str:
    """删非数字间的英文 , .（保护 3.14、1,000 与缩写 J.R.）。

    pipeline 规则 (?<!\\d)[.,](?!\\d) 会删 J.R. 的点。这里加缩写保护：
    字母 . 字母 模式中的点保留。
    """
    out = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch in ".,.":
            # 缩写点保护：字母.字母（前后都是字母则保留）
            prev = body[i - 1] if i > 0 else ""
            nxt = body[i + 1] if i + 1 < n else ""
            if prev.isalpha() and nxt.isalpha():
                out.append(ch)
                i += 1
                continue
            # 数字间保留（pipeline 原 (?<!\d)(?!\d)）
            if prev.isdigit() or nxt.isdigit():
                out.append(ch)
                i += 1
                continue
            # 否则删成空格
            out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def find_issues(text: str, is_chinese: bool = True) -> list:
    """检查中文行有哪些标点问题，返回问题描述列表（不改文本）。

    只对中文行调用（英文行源片台词，连续空格/-- 是口语特征，不检查）。
    规则集对应 pipeline postprocess_translation 对中文译文的处理。
    """
    tags, body = extract_leading_tags(text)
    issues = []
    if "……" in body:
        issues.append("残留全省略号 ……（应归一为 …）")
    # ... 在 CJK 上下文应转 …（不当英文点）。检测原始 body（未归一）里的 ... 模式。
    cjk_ellipsis = re.findall(rf"(?:{CJK}\.\.\.|\.\.\.{CJK}|\d\.\.\.\s*\d)", body)
    if cjk_ellipsis:
        issues.append(f"省略号用 ... 应为 …（{len(cjk_ellipsis)} 处）")
    if re.search(r"[，。、]", body):
        issues.append("残留中文标点 ，。、（应为空格）")
    # 英文标点：只在归一化后的 body 上检测（省略号已转 …，不再算 ... 的点）。
    # 缩写点 J.R. 保护：字母.字母 不算。
    normalized_body = _normalize_ellipsis(body)
    bad_eng = re.findall(r"(?<!\d)[.,](?!\d)", normalized_body)
    abbrev = re.findall(r"[A-Za-z]\.[A-Za-z]", normalized_body)
    real_bad = len(bad_eng) - len(abbrev)
    if real_bad > 0:
        issues.append(f"英文标点在非数字间 {real_bad} 处（应为空格）")
    if re.search(r" {2,}", body):
        issues.append("连续空格（应合并为单空格）")
    if re.search(r"-\s*-+", body):
        issues.append("连续横杠（应合并）")
    # 注释括号（只标中文注释括号，不标 (EMU) 这类译注）
    note_parens = re.findall(r"[（(]\s*(?:注[：:]|旁白)", body)
    if note_parens:
        issues.append(f"注释括号泄漏（{len(note_parens)} 处，应删除）")
    return issues


def collect_files(target: str) -> list:
    if os.path.isdir(target):
        return sorted(os.path.join(target, f) for f in os.listdir(target)
                      if f.lower().endswith(".ass"))
    return [target] if os.path.isfile(target) and target.lower().endswith(".ass") else []


def run(target: str, work_dir: str, accept: bool) -> str:
    files = collect_files(target)
    if not files:
        print("[!] 无 .ass 文件", file=sys.stderr)
        return ""
    out_path = os.path.join(work_dir, "reports", "precheck-punct.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    lines = ["# 标点规范化预检报告", "",
             "规则：只检查中文行（英文行是源片台词，连续空格/-- 是口语特征，不动）。"
             "中文行标点归一：省略号 ... → …（CJK 邻接）、……→…、，。、→空格、英文,./非数字"
             "→空格（缩写 J.R. 保护）、连续空格合并、连续横杠合并、中文注释括号删除"
             "（(EMU) 译注保留）。前导 ASS 标签保留。"]
    total_issues = 0
    total_fixed = 0
    batch_id = make_batch_id() if accept else ""

    for ass_path in files:
        subs = pysubs2.load(ass_path, encoding="utf-8-sig")
        file_issues = []
        for e in subs.events:
            if not e.text or not e.text.strip():
                continue
            is_zh = "中" in (e.style or "")
            if not is_zh:
                continue
            issues = find_issues(e.text, is_chinese=True)
            if issues:
                normalized = normalize_punct(e.text)
                file_issues.append((e, issues, e.text, normalized, True))

        lines.append(f"## {os.path.basename(ass_path)}")
        lines.append("")
        if not file_issues:
            lines.append("无标点问题。")
            lines.append("")
            continue

        lines.append(f"发现 {len(file_issues)} 行中文行有标点问题：")
        lines.append("")
        for e, issues, old, new, is_zh in file_issues:
            lines.append(f"### start={e.start/1000:.2f}s")
            lines.append(f"- 问题: {'; '.join(issues)}")
            lines.append(f"- 现: `{old}`")
            lines.append(f"- 规范化后: `{new}`")
            lines.append("")
            total_issues += 1
        lines.append("")

        if accept:
            for e, issues, old, new, is_zh in file_issues:
                cur = e.text
                e.text = new
                if e.text != cur:
                    append_log(work_dir, batch_id, "precheck_punct", ass_path, 0,
                               "中文", cur, e.text, "标点规范化",
                               "; ".join(issues))
                    total_fixed += 1
            subs.save(ass_path, encoding="utf-8")
            fixed = sum(1 for fi in file_issues if fi[2] != fi[3])
            print(f"[*] {os.path.basename(ass_path)}: 修复 {fixed} 行")

    lines.insert(2, f"共 {len(files)} 文件，{total_issues} 行有标点问题" +
                 (f"，已修复 {total_fixed} 行" if accept else "（dry-run，未修改）"))

    # accept 模式不覆盖 dry-run 报告：dry-run 写 precheck-punct.md，
    # accept 写 precheck-punct-accept.md（或若 dry-run 报告不存在才写）。
    if accept:
        accept_path = os.path.join(work_dir, "reports", "precheck-punct-accept.md")
        with open(accept_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[*] accept 报告写入 {accept_path}（不覆盖 dry-run 的 precheck-punct.md）")
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[*] 报告写入 {out_path}")
    if accept:
        print(f"[*] batch_id={batch_id}，可 --rollback batch={batch_id} 回滚")
    return out_path if not accept else os.path.join(work_dir, "reports", "precheck-punct-accept.md")


def main():
    ap = argparse.ArgumentParser(description="ASS 标点规范化预检")
    ap.add_argument("target", help=".ass 文件或目录")
    ap.add_argument("--out", default=".subtitle-polish", help="work dir")
    ap.add_argument("--accept", action="store_true", help="执行修复并写回（默认 dry-run）")
    args = ap.parse_args()
    wd = resolve_work_dir(args.out)
    run(args.target, wd, args.accept)


if __name__ == "__main__":
    main()

