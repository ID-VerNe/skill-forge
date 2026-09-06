# 术语表处理原则：第三者审校

## 核心原则

**skill 不带术语表**。不预设 Crown Victoria=皇冠维多利亚、Hennessey=Hennessey（双 e）等基准。

审计 agent 作为"第三者审校"：不依赖预置专名表，而是基于上下文与领域知识判断每个专名是否前后一致、是否拼写正确。

## 为什么不带术语表

1. 专名表是项目级，不是流程级。不同节目/领域的专名完全不同（汽车节目 vs 纪录片 vs 剧情）。
2. 预置基准会把本次（The Grand Tour）的约定误传到其他项目。
3. 第三者审校更鲁棒：agent 能发现"同一专名在文件内前后不一致"（如毒蛇/毒液/毒液号混用），这比查表更有效。
4. 用户可以在项目根 `.subtitle-polish/context.md` 里写项目特定背景（如"这是汽车节目，注意底盘/引擎术语"），但这是背景提示，不是术语映射表。

## 项目背景占位符

prompts 模板里有 `{project_context}` 占位符，来源优先级：
1. 用户调用 prompt 里写的背景（如 `/subtitle-polish 精校：... srt：... 这是汽车节目，注意底盘术语`）
2. 项目根 `.subtitle-polish/context.md`（若存在）
3. **两者都没有时，主 agent 读 SRT 前 50 块 + ASS 样式自动合成一段项目背景**（领域、话题、疑似专名列表），填入 `{project_context}`

prompt 参数 > context.md > 自动合成。背景只是提示 agent 关注领域，不提供专名映射。

## 全局替换脚本的用法

`global_replace.py` 用于跨文件统一专名，但**专名映射由人在 dry-run 阶段或修复阶段提供**，不是 skill 预置。

典型流程：
1. 审计报告发现 EP04 `维多利亚皇冠` 9 处不一致
2. 人决定统一为 `皇冠维多利亚`
3. 人调 `global_replace.py 维多利亚皇冠 皇冠维多利亚 --track 中文 --dry-run`
4. 看 dry-run.md 确认后 `--accept`

脚本支持任意 pattern→replacement，不绑定特定专名表。

## context.md 示例（用户自建，非 skill 生成）

```markdown
# 项目背景

- 类型：汽车节目（The Grand Tour 2026）
- 主持人：Jeremy/James/Richard（原版三剑客）或 Francis/Chris 等
- 注意术语：底盘 undertray、马力 horsepower、年检 MOT、改装厂 Hennessey
- 译名约定：Crown Victoria=皇冠维多利亚、Didcot=迪德科特
```

skill 读这个文件填进 prompt 占位符，但不把它当术语映射表用。
