---
name: Parameter Guide
description: >-
  GPT Image 2.5 (Flare & Sunburst) 的 quality, size, model, background 参数建议。SKILL.md 路由到此。
---

# Parameter Guide

> 由 SKILL.md 引用。最终 Prompt 输出时参考。

## Model Selection

| 模型 | 建议场景 |
|---|---|
| `gpt-image-2.5-flare` | 对速度/延迟敏感、快速草稿、概念探索、低成本批量、多次迭代 |
| `gpt-image-2.5-sunburst` | 最终交付、对细节要求极高、高保真复杂编辑、高清海报、文字渲染要求高 |

## Quality

| 需求 | 建议值 |
|---|---|
| 快速草稿、低成本探索 | `quality: low` |
| 常规图片、社媒图、普通产品图 | `quality: medium` |
| 小字、信息图、UI、海报、密集排版、最终交付 | `quality: high` |
| 极复杂细节、需要极高分辨率细节呈现时 | `quality: xhigh` 或 `max` |
| 不确定时 | `quality: auto` 或先 low 再 high |

## Size（尺寸）

| 用途 | 建议尺寸 |
|---|---|
| 通用方图 | `1024x1024` 或 `2048x2048` |
| 竖版海报 / 手机图 / 人像 | `1024x1536` |
| 横版封面 / 幻灯片 / 网页头图 | `1536x1024` |
| 宽屏演示 / 视频封面 | `2048x1152` |
| 4K 超高清（横/竖） | `3840x2160` / `2160x3840` |

## Constraints on Size
- 边长必须为 **16 的倍数**
- 单边最大不超过 **3840 pixels**
- 长短边比例 **不超过 3:1**
- 总像素须在 **655,360** 到 **8,294,400** 之间
- 超过 3,686,400 像素 (如 2560x1440) 视为实验性输出，最终交付前要**检查文字和细节**

## Background（背景）

| 用途 | 建议值 |
|---|---|
| 默认场景、写实带背景图片 | `background: auto` 或 `opaque` |
| 产品抠图、Logo、贴纸（要求原生透明背景） | `background: transparent` (须搭配 output_format: png/webp，并在 Prompt 中明确提出 crisp silhouette/clean alpha edges 等要求) |
