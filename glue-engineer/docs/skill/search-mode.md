# Search Mode — 详细流程

Search Mode（设计/构建/评估系统）的三阶段流程:CLI 自动链收集数据、出完整方案、强制询问是否进入 Deep Mode。

> 何时读：进入 SEARCH 模式（设计/构建/评估系统）后，执行完整流程时。

## 阶段 1: CLI 自动链

依次执行 scout/cross-search/mvp-scope/cap-list/cap-match,用真实数据替代内部知识。

```bash
# 1. 单语言搜索用户需求所需库
python -m polyglot scout <lang> "<keyword>"

# 2. 跨语言搜索（如果涉及多语言）
python -m polyglot cross-search "<keyword>" --languages <langs>

# 3. MVP 功能分级
python -m polyglot mvp-scope <project> --features "功能1,分类" "功能2,分类"

# 4. 能力匹配检查
python -m polyglot cap-list
python -m polyglot cap-match <lang> <lib_a> <lang> <lib_b>
```

## 阶段 2: 出完整方案

基于 CLI 获取的真实数据生成方案，包含：
- 每个推荐库的**版本号、许可证、下载量、数据来源**
- 基于 mvp-scope 的 P0/P1/P2 分级
- 跨语言桥接策略（如果适用）
- 方案中每个库推荐必须标注来源

## 阶段 3: 询问 Deep Mode（强制执行）

方案输出后，**必须**问用户（不可跳过，不可默认确认）：

> 「方案已出。是否需要进入 v4 Deep Mode，用 subagent 对候选库做代码级源码分析？
> （约 3-5 分钟，需等待 subagent 完成）」
>
> - 是 → 执行 Deep Mode 子流程
> - 否 → 结束，输出最终方案