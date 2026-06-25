---
name: multi-lens-research
version: 2.2.0
description: "基于斯坦福STORM方法的多视角深度研究Skill。通过模拟5个专家角色(实践者/学者/怀疑者/经济学家/历史学家)消除单线程思维盲点，执行4步研究流程。当用户需要深度研究话题、评审论文草稿发现盲点和误区、做Code Review评估功能是否值得加、判断研究方向值不值得动手、或用多视角分析任何复杂问题时使用。也适用于投资研究、商业决策、面试准备、谈判策略分析。注意：这是一个通用思维框架而非信息检索工具——它通过多角色视角碰撞产生洞见，不保证外部信息的最新性。"
metadata:
  requires: []
---

# multi-lens-research

> 基于斯坦福 STORM 方法的多视角深度研究 Skill。
>
> **核心理念**：不是让一个人在脑子里模拟 5 种角色——而是真的派出 **5 个独立的 agent** 各担任一种角色，并行分析，再让另一个 agent 合成他们的输出。这是"多视角"的工程化实现，比单线程模拟更深入、更抗偏见。

---

## 触发词 / When to Use

你不需要记命令。想用的时候，直接说人话就行：

| 你想干什么 | 怎么说 |
|-----------|--------|
| 🔬 深度研究一个话题 | `用多视角研究一下 [话题]` |
| 📝 审阅你的论文草稿 | `用多视角审一下我的论文` |
| 💻 评审一个功能或代码 | `用多视角看看这个功能值不值得加` |
| 🧭 判断研究方向的价值 | `用多视角评估一下这个方向` |

**简单规则：** 只要你的话里包含"多视角" + 上面的动作词（研究/审/看看/评估），Skill 就会自动触发。

**完整工作的 description（这是 Claude 自动识别触发用的）：**

> 基于斯坦福STORM方法的多视角深度研究Skill。通过模拟5个专家角色(实践者/学者/怀疑者/经济学家/历史学家)消除单线程思维盲点，执行4步研究流程。当用户需要深度研究话题、评审论文草稿发现盲点和误区、做Code Review评估功能是否值得加、判断研究方向值不值得动手、或用多视角分析任何复杂问题时使用。也适用于投资研究、商业决策、面试准备、谈判策略分析。

---

## ⚡ 必需：始终使用 Agent 工具并行启动子 agent

**这是本 Skill 最核心的行为规则。不要在自己的上下文中顺序模拟 5 个角色。必须通过 Agent 工具派出独立的子 agent。**

### 数据收集机制（重要）

子 agent 返回输出有且只有两种可靠方式：

| 方式 | 做法 | 适合场景 |
|------|------|---------|
| **A. 直接返回值（推荐）** | Phase 1 的 5 个 agent 在同一 turn 用 **非 background** 模式启动，它们的最终输出直接作为 tool result 返回到 Coordinator 上下文中 | Phase 1 多角色并行 |
| **B. 写入文件后读取** | 子 agent 用 Write 工具输出到指定目录，Coordinator 用 Read 工具读取 | Phase 2-4 单 agent，或内容特别长的场景 |

**错误的做法（不要用）：**
- ❌ 不要在子 agent 上使用 `run_in_background: true` + 用 SendMessage 去"请求输出"——子 agent idle 后不会回复文字，这是本次迭代发现的关键问题
- ❌ 不要期望子 agent 的文字输出通过 idle_notification 传回来——idle 通知只含状态信息，不含 output 内容

### 架构概述

```
你（Coordinator）
├── 澄清主题（如不够具体 → AskUserQuestion）
├── 确定场景（Research / Paper Review / Code Review / Direction Judge）
│
├── ═══ Phase 1：Multi-Perspective Scan ═══
│    ├── Agent("PRACTITIONER: 分析[TOPIC]，保存到outputs/")  ← 非background
│    ├── Agent("ACADEMIC: 分析[TOPIC]，保存到outputs/")     ← 非background
│    ├── Agent("SKEPTIC: 分析[TOPIC]，保存到outputs/")     ← 非background
│    ├── Agent("ECONOMIST: 分析[TOPIC]，保存到outputs/")   ← 非background
│    ├── Agent("HISTORIAN: 分析[TOPIC]，保存到outputs/")   ← 非background
│    └── (可选) Agent("REGULATOR/EXTRA: 分析[TOPIC]")      ← 非background
│    └── 所有角色在同一turn并行启动 → 等待全部完成
│    └── 从输出目录 Read 每个角色的文件来收集结果
│
├── 展示摘要 → 问用户是否继续
│
├── ═══ Phase 2：Contradiction Map ═══
│    ├── Agent("矛盾分析师", {从文件读取各角色输出并分析})
│    └── 从其 tool result 获取矛盾地图
│
├── 展示 → 问用户是否继续
│
├── ═══ Phase 3：Synthesis ═══
│    ├── Agent("综合简报师", {从文件读取角色输出+矛盾地图})
│    └── 从其 tool result 获取简报
│
├── 展示 → 问用户是否继续
│
└── ═══ Phase 4：Peer Review ═══
     ├── Agent("同行评审员", {从文件读取简报})
     └── 从其 tool result 获取评审结果
```

### 为什么必须用 Agent 团队 + 数据收集的正确方式

**不推荐 background + SendMessage 模式：** 本次测试中发现，使用 `run_in_background: true` 启动子 agent 后，Coordinator 通过 SendMessage 请求输出时，子 agent 仅返回 idle_notification 而 **不返回文字内容**。输出内容存在于 Agent 工具的 tool result 中，但没有被持久化到磁盘。

**推荐方案：同一 turn 并行启动所有子 agent（非 background），每个 agent 将分析保存到磁盘，完成后 Coordinator 读取文件。**

| 方式 | 问题 |
|------|------|
| 自己模拟 5 个角色 | 同一条思维链，角色间互相污染，本质上只是"换口吻说话" |
| **5 个子 agent 并行** | **每个角色独立推理，真正产生不同视角，冲突才真实** |
| 自己综合 | 上下文窗口限制，容易丢失细节 |
| **子 agent 综合** | **独立审视所有角色输出，不受先入为主影响** |

---

## 🚫 强制执行规则：一次只跑一个 Phase

**不可违反的规则 — 违反此规则 = 没有执行本 Skill：**

| 禁止的行为 | 原因 |
|-----------|------|
| ❌ **禁止合并 Phase** — 不允许在一个 Agent 调用里同时完成多个 Phase | 每个 Phase 的输出需要独立验证、需要用户确认、需要作为下一 Phase 的独立输入 |
| ❌ **禁止跳过用户确认** — 每个 Phase 完成后必须展示摘要，问"是否继续下一步" | 用户可能想中途调整角色、补充上下文、或直接拿中间结果就走 |
| ❌ **禁止 Phase 1 的 5 个角色分批启动** — 必须同一 turn 全量并行 | 分批 = 后启动的角色受前一批影响，破坏了独立性 |
| ❌ **禁止 Phase 2/3/4 和 Phase 1 合并到一个 Agent 调用里** | 矛盾地图必须基于所有角色输出 → 简报必须基于矛盾地图 → 评审必须基于简报。这是严格的串行依赖 |

**正确节奏 — 每个阶段是独立的 Agent 调用，中间有用户确认：**

```
你（Coordinator）
│
├── ═══ Phase 1 调用 ═══
│    ← 同一 turn 并行派出 N 个子 agent（非background）
│    ← 收集所有输出
│    ← 展示摘要给用户
│    ← 问：是否继续 Phase 2？
│        用户回答"否" → 结束
│        用户回答"是" →
│
├── ═══ Phase 2 调用 ═══
│    ← 派出 1 个子 agent（读取所有 Phase 1 文件）
│    ← 收集矛盾地图
│    ← 展示摘要给用户
│    ← 问：是否继续 Phase 3？
│
├── ═══ Phase 3 调用 ═══
│    ← 派出 1 个子 agent（读取 Phase 1+2 文件）
│    ← 收集综合简报
│    ← 展示摘要给用户
│    ← 问：是否继续 Phase 4？
│
└── ═══ Phase 4 调用 ═══
     ← 派出 1 个子 agent（读取简报）
     ← 收集同行评审
     ← 展示最终完整报告
```

---

## 执行模式（唯一模式）

**只有一种模式：分步确认模式。**

每次调用本 Skill 时，严格按照以下节奏执行，**不允许一步到位跑完 4 个 Phase**：

1. **Phase 1**：同一 turn 并行派出所有角色子 agent → 收集输出 → 展示摘要 → **询问是否继续 Phase 2**
2. **等待用户确认后 → Phase 2**：派出矛盾分析师子 agent → 展示摘要 → **询问是否继续 Phase 3**
3. **等待用户确认后 → Phase 3**：派出综合简报师子 agent → 展示摘要 → **询问是否继续 Phase 4**
4. **等待用户确认后 → Phase 4**：派出同行评审员子 agent → 展示最终完整报告

> **如果用户说"全自动一次跑完"或"一起跑了吧"等任何试图合并 Phase 的请求：**
> 礼貌拒绝，解释原因：每个 Phase 的输出需要你过目确认，中途可能调整方向或角色。然后按分步模式执行 Phase 1。

---

## 核心方法（4 步 STORM 流程）

### Phase 1：Multi-Perspective Scan（多视角扫描）

**关键：在同一 turn 并行启动所有子 agent（不设 run_in_background），让它们在各自的 prompt 中把分析 Write 到磁盘文件。所有 agent 完成后，Read 每个文件来收集结果。**

#### 正确做法与错误做法

```
✅ 正确做法（同一 turn 并行，非background）：
   Agent("PRACTITIONER: 分析[TOPIC]，把输出保存到outputs/practitioner.md", ...)
   Agent("ACADEMIC: 分析[TOPIC]，把输出保存到outputs/academic.md", ...)        ← 同一turn
   Agent("SKEPTIC: 分析[TOPIC]，把输出保存到outputs/skeptic.md", ...)          ← 同一turn
   ...
   全部启动后 → 等待完成 → Read 各文件获取结果

❌ 错误做法（background + SendMessage）：
   Agent("...", {run_in_background: true})                                      ← 子agent完成后
   SendMessage(to: "agent", "请输出分析")                                        ← 不会回复文字
   → 子agent只返回 idle_notification，内容无法回收
```

#### 并行启动 5 个角色的具体代码模式

用一个目录存放所有角色的输出，例如 `workspace/[session]/outputs/`。

每个子 agent 的 prompt 末追加：`"请将你的完整分析保存到 [路径]/[角色名].md 文件"`。

启动后等待所有 agent 的 tool result 返回，然后挨个 Read 文件获取内容。

每个子 agent 的 prompt 结构：

```
你是一位[角色名]。请从你的专业角度分析以下主题：

[TOPIC / PAPER / CODE / DIRECTION]

请输出：
1. 你的核心立场（2 句话）
2. 支持你观点最强的 3 条证据（每条 2-3 句话，具体、有引用）
3. 你注意到但其他角色几乎肯定不会注意到的一件事（这是你独有的价值）
4. 如果有证据或数据支持，请明确说明出处
```

**5 个默认角色：**

| 角色 | 核心追问 |
|------|---------|
| THE PRACTITIONER 实践者 | 真实世界每天在用的人知道什么学术界不知道的？ |
| THE ACADEMIC 学者 | 同行评审证据到底说了什么？和流行观点矛盾在哪？ |
| THE SKEPTIC 怀疑论者 | 主流叙事错在哪里？支持者刻意忽略了什么？ |
| THE ECONOMIST 经济学家 | 谁从中获利？什么财务激励在塑造这个领域？ |
| THE HISTORIAN 历史学家 | 历史上什么时候发生过类似的事？后来怎样了？ |

**根据用户身份追加的视角：**

| 用户领域 | 追加角色 |
|---------|---------|
| 能源工程（P2P/预测） | 电力市场监管者（关注法规合规、电网稳定性） |
| 材料工程（SERS） | 实验实践者（关注可重复性、制备难度、真实环境挑战） |
| 全栈开发 | 运维工程师（关注部署、监控、CI/CD 影响、技术债务） |

**场景特化角色替换：**

| 场景 | 替换角色集 |
|------|-----------|
| **Paper Review** | SUPPORTIVE REVIEWER / HOSTILE REVIEWER / METHODOLOGIST / COMPETITOR / INTERDISCIPLINARY BRIDGE |
| **Code Review** | ARCHITECT / USER-ADVOCATE / MINIMALIST / SECURITY-PERFORMANCE ENGINEER / BUSINESS ANALYST |
| **Direction Judge** | OPTIMIST / PESSIMIST / PUBLICATION STRATEGIST / RESOURCE REALIST / PATTERN-MATCHER |

### Phase 2：Contradiction Map（矛盾地图）

派出 **1 个子 agent**，它的 prompt 让子 agent 自己 Read Phase 1 写入的所有文件并分析。

```
你是一位矛盾分析师。请读取以下文件：
- outputs/practitioner.md
- outputs/academic.md
- outputs/skeptic.md
- outputs/economist.md
- outputs/historian.md
(以及 outputs/regulator.md 如有追加)

基于这些独立视角，在输出的文字中完成矛盾地图分析：

1. DIRECT CONTRADICTIONS: List every place where two or more perspectives
   directly contradict each other. For each: which perspectives, what exact
   claims clash, and what would resolve it.

2. EVIDENCE STRENGTH RANKING: Which perspective has the strongest evidence?
   Weakest? Why? Be specific about what makes evidence "strong" (empirical
   vs theoretical, sample size, replication, real-world validation).

3. THE ONE QUESTION: One question that if answered would resolve the
   biggest contradiction.

4. CONSENSUS: What does EVERY perspective agree on? (This is likely true.)

5. BLIND SPOT: What topic did NONE of the perspectives address?
   (This is often the most valuable finding. Push hard — what did everyone
   assume and not question?)
```

### Phase 3：Synthesis（综合简报）

派出 **1 个子 agent**，让它读取 Phase 1 所有角色文件 + Phase 2 矛盾地图文件。

```
Synthesize everything below into a research briefing:

[参考文件路径]

1. ONE-PARAGRAPH SUMMARY: Brief a CEO with 60 seconds. Nuance, not headline.

2. 5 KEY FINDINGS: Ranked by reliability (confidence score 1-10 each).
   For each: which perspectives support it, which challenge it.

3. HIDDEN CONNECTION: One non-obvious link that only shows up when you
   see all perspectives together.

4. ACTIONABLE INSIGHT: Based on all evidence, what should someone in
   [USER'S ROLE] actually DO differently? Be specific.

5. FRONTIER QUESTION: The one question that if answered would change
   everything about how we understand this topic.
```

### Phase 4：Peer Review（同行评审）

派出 **1 个子 agent**，读取综合简报文件并评审。

```
Peer review the following research briefing:

[参考文件路径]

1. CONFIDENCE SCORES: Rate each of the 5 findings on 1-10 for reliability.
   Explain each score.

2. WEAKEST LINK: Which claim are you LEAST confident in? What specific
   info would you need to verify it?

3. BIAS CHECK: Which perspective might be overrepresented? Did one voice
   dominate the synthesis?

4. MISSING PERSPECTIVE: Is there a 6th angle that should have been
   included? What would change?

5. OVERALL GRADE: If a Stanford professor reviewed this, what grade would
   they give? What would they tell me to fix? Be honest.
```

---

## 完整工作流

```text
你（Coordinator）
│
├── 澄清主题 → 如果不够具体，先问用户
│
├── ═══ PHASE 1：Multi-Perspective Scan ═══
│    ├── 创建工作目录 outputs/
│    ├── 同一 turn 并行启动所有角色 Agent（非background）：
│    │   Agent("PRACTITIONER: 分析[TOPIC]，保存到outputs/practitioner.md")
│    │   Agent("ACADEMIC: 分析[TOPIC]，保存到outputs/academic.md")
│    │   Agent("SKEPTIC: 分析[TOPIC]，保存到outputs/skeptic.md")
│    │   Agent("ECONOMIST: 分析[TOPIC]，保存到outputs/economist.md")
│    │   Agent("HISTORIAN: 分析[TOPIC]，保存到outputs/historian.md")
│    │   Agent("追加视角(如REGULATOR): 分析[TOPIC]...")   ← 可选
│    ├── 等待所有 agent 完成
│    ├── Read 每个文件获取内容
│    ├── 展示每个角色的核心结论摘要
│    ├── 问用户：是否继续 Phase 2？
│    │   是 → 继续
│    │   否 → 结束，或按用户要求调整
│    │
├── ═══ PHASE 2：Contradiction Map ═══
│    ├── Agent("矛盾分析师", {读取 Phase 1 的所有文件并分析})
│    ├── 读取矛盾地图
│    ├── 展示核心矛盾点、共识和盲区
│    ├── 问用户：是否继续 Phase 3？
│    │   是 → 继续
│    │   否 → 结束
│    │
├── ═══ PHASE 3：Synthesis ═══
│    ├── Agent("综合简报师", {读取 Phase 1+2 的所有文件})
│    ├── 读取综合简报
│    ├── 展示 5 个关键发现 + 可操作建议
│    ├── 问用户：是否继续 Phase 4？
│    │   是 → 继续
│    │   否 → 结束
│    │
└── ═══ PHASE 4：Peer Review ═══
     ├── Agent("同行评审员", {读取简报文件})
     ├── 读取同行评审报告
     └── 展示最终完整报告（所有 Phase 的输出）
```

---

## 关键原则

1. **Agent 团队是强制性的**：Phase 1 的 5 个角色必须作为并行子 agent 运行。这是本 skill 区别于"一个人自言自语模拟 5 种角色"的根本所在。不要走捷径在自己上下文里模拟。
2. **英文提示词保持原文**：子 agent 的 prompt 保留英文原文效果最佳。你的交互（展示给用户看、问问题）用中文。
3. **盲点优先**：Phase 2 的第 5 条往往是整个分析中最有价值的部分。
4. **共识≈真相**：如果所有 5 个视角都同意一个观点，它有极大概率是真的。
5. **先问再跑**：如果主题不够具体，先问 2-3 个澄清问题再开始。
6. **可中断、可迭代**：任何一步的输出如果用户不满意，可以要求重新调整某一角色的 prompt 强度或换一个角色，重新跑那个子 agent。

---

## 参考资料

- STORM paper: "Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking" — NAACL 2024, Stanford OVAL Lab
- Live demo: storm.genie.stanford.edu
- Source code: github.com/stanford-oval/storm (MIT License)
