---
name: Parameter Guide
description: >-
  GPT Image 2 的 quality 和 size 参数建议。SKILL.md 路由到此。
---

# Parameter Guide

> 由 SKILL.md 引用。最终 Prompt 输出时参考。

## Quality

| 需求 | 建议值 |
|---|---|
| 快速草稿、概念探索、低成本批量 | `quality: low` |
| 常规图片、社媒图、普通产品图 | `quality: medium` |
| 小字、信息图、UI、海报、密集排版、最终交付 | `quality: high` |
| 不确定时 | `quality: auto` 或先 low 再 high |

## Size（尺寸）

| 用途 | 建议尺寸 |
|---|---|
| 通用方图 | `1024x1024` |
| 竖版海报 / 手机图 / 人像 | `1024x1536` |
| 横版封面 / 幻灯片 / 网页头图 | `1536x1024` |
| 高保真方图 | `2048x2048` |
| 宽屏演示 / 视频封面 | `2048x1152` 或接近 16:9 的合法尺寸 |

## Constraints on Size

- 边长必须为 **16 的倍数**
- 长短边比例 **不超过 3:1**
- 总像素不低于 **655,360** 且不超过 **8,294,400**
- 超过 2K 的输出应视为实验性选择，最终交付前要**检查文字、细节和布局**
