# -*- coding: utf-8 -*-
"""precheck_punct.py — 标点规范化预检。

对照 translate_principle/subtitle pipeline 的标点预处理流程，检测成品 ASS 里
标点不一致的行（pipeline 产物不应出现的标点残留）。

规则来源（pipeline 三道处理的合并目标态）：
  core/stages/polish_stage.py::postprocess_translation()
  post-process/02-post_process_ass.py::clean_single_line()
  core/srt_utils.py::clean_content()

核心规则（照搬 postprocess_translation，但只对可见文本应用，不动前导 ASS 标签）：
  1. …… → …（全省略号归一为半省略号）
  2. ，。、 → 空格（中文逗号/句号/顿号）
  3. 英文 , . → 空格，仅当左右都不是数字（保护 3.14、1,000）
  4. 多空格 → 单空格
  5. -\\s*-+ → -（连续横杠合并）
  6. （...） (...) 注释括号删除（仅当该行原文无括号时——本脚本只对成品，统一删）

pipeline 保留不动：! ！ ? ？ ; ； ' " ‘ ’ “ ” … 以及数字间的 . ,

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


def normalize_punct(text: str) -> str:
    """对中文行标点做规范化，返回规范化后的文本。只作用于可见文本，保留前导 ASS 标签。"""
    tags, body = extract_leading_tags(text)
    body = _normalize_chinese_body(body)
    return "".join(tags) + body


def _normalize_chinese_body(body: str) -> str:
    """中文可见文本的标点归一（照搬 pipeline postprocess_translation 规则）。"""
    body = body.replace("……", "…")
    body = re.sub(r"[，。、]", " ", body)
    body = re.sub(r"(?<!\d)[.,](?!\d)", " ", body)
    body = re.sub(r" {2,}", " ", body)
    body = re.sub(r"-\s*-+", "-", body)
    body = re.sub(r"[\(（][^\)）]*[\)）]", "", body)
    body = body.strip()
    return body


def find_issues(text: str, is_chinese: bool = True) -> list:
    """检查中文行有哪些标点问题，返回问题描述列表（不改文本）。

    只对中文行调用（英文行源片台词，连续空格/-- 是口语特征，不检查）。
    规则集对应 pipeline postprocess_translation 对中文译文的处理。
    """
    tags, body = extract_leading_tags(text)
    issues = []
    if "……" in body:
        issues.append("残留全省略号 ……（应归一为 …）")
    if re.search(r"[，。、]", body):
        issues.append("残留中文标点 ，。、（应为空格）")
    bad_eng = re.findall(r"(?<!\d)[.,](?!\d)", body)
    if bad_eng:
        issues.append(f"英文标点在非数字间 {bad_eng[:3]}（应为空格）")
    if re.search(r" {2,}", body):
        issues.append("连续空格（应合并为单空格）")
    if re.search(r"-\s*-+", body):
        issues.append("连续横杠（应合并）")
    if re.search(r"[\(（][^\)）]*[\)）]", body):
        issues.append("注释括号 (...)/（...）（应删除）")
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
             "中文行标点归一：……→…、，。、→空格、英文,./非数字→空格、连续空格合并、"
             "连续横杠合并、注释括号删除。前导 ASS 标签（{\\be3} 等）保留。"]
    total_issues = 0
    total_fixed = 0
    batch_id = make_batch_id() if accept else ""

    for ass_path in files:
        subs = pysubs2.load(ass_path, encoding="utf-8-sig")
        file_issues = []
        for e in subs.events:
            if not e.text or not e.text.strip():
                continue
            # 只检查中文行；英文行是源片台词，连续空格/-- 是正常口语特征，不动
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

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[*] 报告写入 {out_path}")
    if accept:
        print(f"[*] batch_id={batch_id}，可 --rollback batch={batch_id} 回滚")
    return out_path


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
