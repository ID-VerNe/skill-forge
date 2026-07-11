---
name: multi-lens-research
version: 3.0.0
description: "基于斯坦福STORM方法的多视角深度研究Skill。通过多团队Agent架构(11个专业团队+自定义)消除单线程思维盲点，执行4步研究流程。当用户需要深度研究话题、评审论文草稿、做Code Review、评估方向、投资研究、谈判策略、面试准备、安全审计、架构评估、产品设计评审、创业建议时使用。注意：这是一个通用思维框架而非信息检索工具——它通过多角色视角碰撞产生洞见，不保证外部信息的最新性。"
metadata:
  requires: []
---

# multi-lens-research v3

> 基于斯坦福 STORM 方法的多视角深度研究 Skill。
>
> **核心理念**：不是让一个人在脑子里模拟 N 种角色——而是真的派出 **N 个独立的 agent** 各担任一种角色，并行分析，再让另一个 agent 合成他们的输出。
>
> **v3 新特性**：多团队架构。根据场景自动选择最合适的专家团队，角色定义从 `teams/` 目录按需加载，不再所有场景共用同一套角色。

---

## ⚡ 团队选择机制

根据用户输入中的关键词，自动选择匹配的专家团队：

| 关键词 | 团队 | 角色 |
|--------|------|------|
| 研究/话题/深度分析/默认 | `teams/default/` | 实践者/学者/怀疑论者/经济学家/历史学家 |
| 论文/审阅/投稿 | `teams/paper-review/` | 支持性审稿人/反对性审稿人/方法论审稿人/竞争性审稿人/跨学科桥梁 |
| 代码/功能/PR | `teams/code-review/` | 架构师/用户倡导者/极简主义者/安全性能工程师/业务分析师 |
| 方向/值不值得/评估 | `teams/direction-judge/` | 乐观者/悲观者/发表策略师/资源现实主义者/模式匹配者 |
| 股票/投资/买入 | `teams/investing/` | 价值投资者/宏观分析师/技术分析者/风险管理师/行业内部视角 |
| 谈判/交易/协商 | `teams/negotiation/` | 博弈策略师/谈判心理学家/BATNA分析师/文化顾问 |
| 面试/招聘/求职 | `teams/interview-prep/` | 技术面试官/行为面试官/系统设计面试官/招聘经理 |
| 安全/审计/渗透 | `teams/security-review/` | 威胁建模师/渗透测试者/合规官/隐私分析师 |
| 架构/技术选型 | `teams/tech-architecture/` | 系统架构师/可扩展性工程师/迁移专家/技术债务分析师 |
| 设计/UX/产品 | `teams/product-design/` | 用户研究员/产品经理/视觉设计师/无障碍专家 |
| 创业/商业/MVP | `teams/startup-advisor/` | 创业者导师/风险投资分析师/市场进入策略师/技术合伙视角 |
| 自定义 | `teams/custom/<name>/` | 用户自定义角色 |

**加载流程：**
1. 从用户输入识别场景关键词
2. 匹配 `teams/<team>/team.json` 获取角色列表
3. 读取每个角色的 `.md` 文件获取完整 prompt
4. 如果未匹配任何关键词 → 默认加载 `teams/default/`
5. 同时加载 `teams/shared/`（Phase 2-4 角色）

---

## 触发词 / When to Use

你不需要记命令。想用的时候，直接说人话就行：

| 你想干什么 | 怎么说 |
|-----------|--------|
| 🔬 深度研究 | `用多视角研究一下 [话题]` |
| 📝 审阅论文 | `用多视角审一下我的论文` |
| 💻 评审功能 | `用多视角看看这个功能值不值得加` |
| 🧭 判断方向 | `用多视角评估一下这个方向` |
| 📈 投资分析 | `用多视角分析一下这个投资` |
| 🗣️ 谈判准备 | `用多视角帮我分析这个谈判` |
| 🎯 面试准备 | `用多视角模拟面试` |
| 🔒 安全审计 | `用多视角做安全审计` |
| 🏗️ 架构评审 | `用多视角评估这个架构` |
| 🎨 设计评审 | `用多视角评审这个设计` |
| 🚀 创业建议 | `用多视角评估这个创业想法` |

**简单规则：** 只要你的话里包含"多视角" + 上面的动作词，Skill 就会自动触发。

---

## ⚡ 必需：使用 Agent 工具并行启动子 agent

**这是本 Skill 最核心的行为规则。不要在自己的上下文中顺序模拟 N 个角色。必须通过 Agent 工具派出独立的子 agent。**

### 数据收集机制

子 agent 返回输出有且只有两种可靠方式：

| 方式 | 做法 | 适合场景 |
|------|------|---------|
| **A. 直接返回值（推荐）** | Phase 1 的多个 agent 在同一 turn 用非 background 模式启动，它们的最终输出直接作为 tool result 返回 | Phase 1 多角色并行 |
| **B. 写入文件后读取** | 子 agent 用 Write 工具输出到指定目录，Coordinator 用 Read 工具读取 | Phase 2-4 单 agent，或内容特别长的场景 |

### 架构概述

```
你（Coordinator）
├── 识别场景 → 加载 teams/<team>/team.json → 读取角色 .md 文件
├── 澄清主题（如不够具体 → 先 AskUserQuestion）
│
├── ═══ Phase 1：Multi-Perspective Scan ═══
│    ├── 同一 turn 并行启动所有角色 Agent（非background）
│    │   Agent("ROLE_1 prompt")  ← 从 .md 文件读取
│    │   Agent("ROLE_2 prompt")  ← 从 .md 文件读取
│    │   ...
│    ├── 等待所有 agent 完成
│    ├── 展示每个角色的核心结论摘要
│    ├── 问用户：是否继续 Phase 2？
│    │
├── ═══ Phase 2：Contradiction Map ═══
│    ├── Agent("矛盾分析师", 从 teams/shared/ 加载 prompt)
│    ├── 展示矛盾地图
│    ├── 问用户：是否继续 Phase 3？
│    │
├── ═══ Phase 3：Synthesis ═══
│    ├── Agent("综合简报师", 从 teams/shared/ 加载 prompt)
│    ├── 展示综合简报
│    ├── 问用户：是否继续 Phase 4？
│    │
└── ═══ Phase 4：Peer Review ═══
     ├── Agent("同行评审员", 从 teams/shared/ 加载 prompt)
     └── 展示最终完整报告
```

---

## 🚫 强制执行规则

| 规则 | 说明 |
|------|------|
| ❌ 禁止合并 Phase | 每个 Phase 必须独立运行，用户确认后才进下一阶段 |
| ❌ 禁止跳过用户确认 | 每个 Phase 完成后必须展示摘要，问"是否继续下一步" |
| ❌ 禁止分批启动 Phase 1 | 所有角色必须在同一 turn 全量并行启动 |
| ❌ 禁止在自己上下文模拟角色 | 必须通过 Agent 工具派出独立子 agent |
| ✅ 必须从 teams/ 加载 prompt | 不要凭记忆写角色 prompt，去 Read 对应的 .md 文件 |

---

## 核心方法（4 步 STORM 流程）

### Phase 0：场景识别 + 团队加载

```
1. 从用户输入识别场景关键词（见上面的关键词表）
2. Read teams/<team>/team.json ← 获取角色列表
3. 对每个角色 Read teams/<team>/<slug>.md ← 获取完整 prompt
4. Read teams/shared/team.json 和 Phase 2-4 的 .md
5. 创建工作目录 outputs/<team>/
```

### Phase 1：Multi-Perspective Scan

```
在同一 turn 并行启动所有角色子 agent（非 background）：

✅ 正确做法：
   Agent("ROLE_1 prompt（从 .md 读取）", ...)
   Agent("ROLE_2 prompt（从 .md 读取）", ...)    ← 同一 turn
   ...                                              ← 同一 turn
   全部启动后 → 等待完成 → 收集结果

❌ 错误做法：
   - 分批启动（后启动的角色受前一批影响，破坏独立性）
   - background + SendMessage（子 agent 不会回复文字内容）
   - 在自己上下文里模拟角色（思维链互相污染）
```

每个子 agent 的 prompt 末尾追加：`"请将你的完整分析保存到 outputs/<team>/<role>.md 文件"`

### Phase 2：Contradiction Map

派出 **1 个子 agent**，使用 `teams/shared/contradiction-analyst.md` 中的 prompt。

### Phase 3：Synthesis

派出 **1 个子 agent**，使用 `teams/shared/synthesis-briefer.md` 中的 prompt。

### Phase 4：Peer Review

派出 **1 个子 agent**，使用 `teams/shared/peer-reviewer.md` 中的 prompt。

---

## 完整工作流

```text
你（Coordinator）
│
├── 识别场景关键词 → 加载 teams/<team>/ 和 teams/shared/
├── 澄清主题 → 如果不够具体，先问用户
│
├── ═══ PHASE 1：Multi-Perspective Scan ═══
│    ├── 创建工作目录 outputs/<team>/
│    ├── 同一 turn 并行启动所有角色 Agent（非background）：
│    │   从 team.json 读取角色列表，对每个角色：
│    │   Read teams/<team>/<slug>.md → 获取 prompt
│    │   每个 Agent prompt 末追加保存路径
│    ├── 等待所有 agent 完成
│    ├── 收集每个角色的输出
│    ├── 展示每个角色的核心结论摘要
│    ├── 问用户：是否继续 Phase 2？
│    │   是 → 继续
│    │   否 → 结束，或按用户要求调整
│    │
├── ═══ PHASE 2：Contradiction Map ═══
│    ├── Read teams/shared/contradiction-analyst.md → 获取 prompt
│    ├── Agent("矛盾分析师", {读取 Phase 1 的所有文件并分析})
│    ├── 读取矛盾地图
│    ├── 展示核心矛盾点、共识和盲区
│    ├── 问用户：是否继续 Phase 3？
│    │
├── ═══ PHASE 3：Synthesis ═══
│    ├── Read teams/shared/synthesis-briefer.md → 获取 prompt
│    ├── Agent("综合简报师", {读取 Phase 1+2 的所有文件})
│    ├── 读取综合简报
│    ├── 展示 5 个关键发现 + 可操作建议
│    ├── 问用户：是否继续 Phase 4？
│    │
└── ═══ PHASE 4：Peer Review ═══
     ├── Read teams/shared/peer-reviewer.md → 获取 prompt
     ├── Agent("同行评审员", {读取简报文件})
     ├── 读取同行评审报告
     └── 展示最终完整报告（所有 Phase 的输出）
```

---

## 关键原则

1. **Agent 团队是强制性的**：Phase 1 的多个角色必须作为并行子 agent 运行。这是本 skill 区别于"一个人自言自语模拟 N 种角色"的根本所在。
2. **从 teams/ 加载 prompt**：不要凭记忆写角色 prompt。每次去 Read teams/<team>/<slug>.md 获取准确内容。这是"渐进式加载"的核心。
3. **英文提示词保持原文**：子 agent 的 prompt 保留英文原文效果最佳。你的交互（展示给用户看、问问题）用中文。
4. **盲点优先**：Phase 2 的盲点分析往往是整个分析中最有价值的部分。
5. **共识≈真相**：如果所有角色都同意一个观点，它有极大概率是真的。
6. **先问再跑**：如果主题不够具体，先问 2-3 个澄清问题再开始。
7. **可中断、可迭代**：任何一步的输出如果用户不满意，可以要求重新调整某一角色的 prompt 强度或换一个角色，重新跑那个子 agent。
8. **自定义团队**：用户可以创建 `teams/custom/<name>/` 文件夹，放入自己的 team.json + 角色 .md 文件，skill 会自动发现。详见 `teams/custom/README.md`。

---

## 参考资料

- STORM paper: "Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking" — NAACL 2024, Stanford OVAL Lab
- Live demo: storm.genie.stanford.edu
- Source code: github.com/stanford-oval/storm (MIT License)