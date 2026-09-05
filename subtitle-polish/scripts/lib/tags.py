# -*- coding: utf-8 -*-
"""ASS 标签工具：提取/合并前导标签（{\\be3}{\\an8} 等）。

供 apply_fixes、precheck_punct 共用，保证标签处理逻辑单一定义。
"""
from __future__ import annotations

import re

_TAG_RE = re.compile(r"^\{[^}]*\}")


def extract_leading_tags(text: str):
    """提取文本开头的所有 ASS 标签 {\\be3}{\\an8}...，返回 (tags_list, rest)。

    循环匹配，支持多个连续前导标签。rest 是去掉所有前导标签后的纯可见文本。
    """
    tags = []
    while True:
        m = _TAG_RE.match(text)
        if not m:
            break
        tags.append(m.group(0))
        text = text[m.end():]
    return tags, text


def merge_tags(orig_tags, new_tags):
    """合并两组标签：原行标签在前，new 里多出来的追加，去重保序。"""
    merged = list(orig_tags)
    for t in new_tags:
        if t not in merged:
            merged.append(t)
    return merged
