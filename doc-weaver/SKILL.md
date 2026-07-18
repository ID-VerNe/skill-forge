---
name: doc-weaver
version: 1.0.0
description: "项目文档编织器。基于lat.md格式规范，自动为项目生成覆盖所有模块的知识图谱文档，并用并行子agent做源码级比对验证。当用户说'写文档'、'补充文档'、'生成项目文档'、'document this project'、'weave docs'时触发。适用于AI-first的多项目管理场景——文档主要供AI agent阅读，而非人类。"
metadata:
  requires: []
---

# doc-weaver v1 — AI-First 项目文档编织器

> **核心理念**: 不是用 lat.md 的工具链，而是用 Claude Code 的 agent 能力，实现他的**格式规范**和**验证逻辑**。
>
> 文档由 AI agent 生成，由 AI agent 维护，由 AI agent 验证。人类只需在关键决策点给出设计意图。

---

## 文档格式规范（继承自 lat.md）

项目文档存放在 `lat.md/` 目录下，使用以下规范：

### 目录结构

```
lat.md/
  <module>.md         # 每个模块一个文件
  <module>/           # 子模块目录（可选）
    <submodule>.md

  lat.md              # 根索引：所有文档的入口点
  Project.md          # [Tier 1] 入口文档：一句话描述 + 模块清单
  Architecture.md     # 架构总览：模块依赖关系、数据流向、技术选型
  Glossary.md         # 术语表：每个概念在项目中定义且仅定义一次
```

### Section ID

每个 section 拥有层次化 ID：`file#Heading#Subheading#Subsubheading`

- 第一段：项目根相对路径，**去掉 `.md` 扩展名**
- 之后每段：各级标题文本，精确链
- 示例：`lat.md/auth#OAuth Flow#Token Refresh`
- 根标题（h1）在引用时可省略（解析器自动补全）

### Wiki Link 语法

| 语法 | 含义 |
|------|------|
| `[[target]]` | 链接到 `target.md` 文件的根 section |
| `[[target#Heading]]` | 链接到 `target.md` 中的特定 heading |
| `[[target\|alias]]` | 带别名的链接 |
| `[[src/auth.ts#validateToken]]` | 链接到源码符号 |

### 源码注解

```
// @lat: [[section-id]]     // TypeScript, JavaScript, Rust, Go, C
# @lat: [[section-id]]      // Python
```

### 前文规则

每个 section **必须**有前导段落：紧跟在 heading 后的第一段文字，**≤250 字符**（不计 wiki link 语法），保证搜索摘要的简洁性。

### 目录索引约定

`lat.md/` 下每个子目录必须有一个同名索引文件（如 `lat.md/tests/tests.md`），包含该目录所有文件的 wiki link 清单：

```markdown
# Tests

- [[tests/unit]] — 单元测试规范
- [[tests/integration]] — 集成测试规范
```

---

## 核心工作流

整个流程分为 5 个阶段，按顺序执行。

### Phase 0：项目扫描（项目级上下文收集）

在开始写任何文档之前，**先扫描整个项目**收集上下文：

1. 读取 `package.json` / `Cargo.toml` / `pyproject.toml` / `go.mod` 获取项目元数据和技术栈
2. 读取 `README.md` / `CLAUDE.md` 获取现有项目描述
3. 扫描 `src/` 或源码根目录，识别所有顶级模块/包
4. 对每个模块，快速扫描其 exports、关键 types/interfaces、外部依赖
5. 识别 entry points（main、HTTP handlers、CLI commands）

**输出**：一份项目全景清单，包含模块列表、每个模块的关键符号、模块间依赖关系。

### Phase 1：生成 Tier 1 入口文档

生成 `lat.md/` 根目录下的索引和入口文件：

**`lat.md/lat.md`** — 根索引：
```markdown
# lat.md

项目 lat.md/ 目录的入口。以下为所有文档清单：

- [[Project]] — 项目概述与模块清单
- [[Architecture]] — 架构设计与模块依赖
- [[Glossary]] — 术语表
- [[auth]] — 鉴权模块
- [[api]] — API 路由层
- [[database]] — 数据访问层
```

**`lat.md/Project.md`** — 项目入口文档（Tier 1，~1K tokens）：
```markdown
# Project

**Tech Stack**: TypeScript + Node.js + PostgreSQL + Redis
**Architecture Pattern**: Clean Architecture

## Modules

- [[auth]] — 用户鉴权，OAuth 2.0，JWT 管理
- [[api]] — HTTP API 路由与中间件
- [[database]] — 数据访问层，迁移管理
- [[worker]] — 后台任务队列处理
- [[config]] — 配置管理

## Dependency Graph

依赖关系见 [[Architecture#Module Dependencies]]。
```

**`lat.md/Architecture.md`** — 架构总览

### Phase 2：生成 Tier 2 模块知识文档

对 Phase 0 识别出的**每个模块**，生成一个 markdown 文档：

模板：
```markdown
# 模块名

一句概述：这个模块负责什么、为什么存在。

## Responsibilities

- 核心职责 1
- 核心职责 2

## Key Concepts

### 概念名

概念解释。内部机制概要。

Reference: [[src/module/file.ts#SymbolName]]

### 概念名 2

...

## Dependencies

该模块依赖的其他模块和原因：

- [[database]] — 持久化存储用户数据
- [[config]] — 读取配置参数

## Consumed By

哪些模块使用本模块：

- [[api]] — 通过 service 层调用鉴逻辑
- [[worker]] — 在后台任务中使用

## Error Conditions

可机器解析的错误码和恢复路径（见 [[module.schema.json]]）
```

**关键规则**：
- 每个 section 必须有 ≤250 字符的前导段落
- 涉及其他模块的必须用 `[[wiki link]]`
- 涉及源码符号的必须用 `[[src/path#symbol]]`
- 每个文件遵循 directory index 约定

### Phase 3：生成 Tier 3 结构化数据

对每个模块，生成机器可读的 JSON schema：

**`docs/schema/<module>.schema.json`**：
```json
{
  "module": "auth",
  "version": "1.0.0",
  "exports": [
    { "name": "login", "kind": "function", "params": ["email", "password"], "returns": "Token" },
    { "name": "refreshToken", "kind": "function", "params": ["token"], "returns": "Token" }
  ],
  "dependencies": {
    "internal": ["database", "redis"],
    "external": ["jsonwebtoken"]
  },
  "consumers": ["api", "websocket"],
  "errors": {
    "TOKEN_EXPIRED": { "code": 401, "recovery": "Call refreshToken" },
    "INVALID_CREDENTIALS": { "code": 403, "recovery": null }
  },
  "entryPoints": ["src/auth/service.ts"],
  "configKeys": ["JWT_SECRET", "JWT_EXPIRY"]
}
```

同时生成 **`docs/graph.json`** — 全模块依赖图：
```json
{
  "modules": [
    { "name": "auth", "dependsOn": ["database", "redis"], "usedBy": ["api", "worker"] },
    { "name": "database", "dependsOn": [], "usedBy": ["auth", "api", "worker"] }
  ],
  "entryPoints": ["src/server.ts", "src/worker.ts"],
  "techStack": { "language": "TypeScript", "runtime": "Node.js" }
}
```

### Phase 4：添加源码注解

在源码中添加 `@lat:` 注解。规则：

1. 对 `lat.md/` 中每个描述了代码行为的 leaf section，在对应源码中添加 `// @lat: [[section-id]]`
2. 放在对应的函数/类/测试前一行
3. 不要重复——每个 section 对应一个注释
4. 不要在简单 getter/setter 或明显无业务含义的代码上添加

### Phase 5：并行源码级比对验证（关键步骤）

这是整个流程的**质量保证环节**。派出**并行子 agent**，每个模块一个，做源码级比对。

#### 验证协议

每个验证 agent 的 prompt 模板：

```
你是 doc-weaver 验证 agent。
你的任务：比对 `lat.md/<module>.md` 和源代码，找出所有不一致。

请做以下检查：

1. **接口完整性检查**：文档中描述的 exports、函数签名、参数、返回值是否与源码一致？
   - 文档写了但代码没有 → `doc_claim_not_in_code`
   - 代码有但文档没写 → `code_feature_not_documented`

2. **依赖关系检查**：文档中声明的 dependencies/consumers 是否正确？
   - 源码中 import/require 了但文档没提 → 遗漏依赖
   - 文档声明了但源码中没有 import → 过期依赖

3. **错误条件检查**：文档中描述的 error codes 和 recovery 路径是否真实存在？
   - 文档写了某个 error 但源码中从未 throw → 虚构错误
   - 源码中 throw 了某个 error 但文档没记录 → 遗漏错误

4. **行为描述检查**：文档中的业务逻辑描述是否准确反映了源码实现？
   - 文档说"使用 JWT"但源码用 session → 描述错误
   - 文档描述了一个流程但实际代码逻辑不同 → 描述不准确

5. **符号引用检查**：文档中的 `[[src/path#symbol]]` 引用是否都指向真实存在的符号？

输出格式（JSON）：
```json
{
  "module": "auth",
  "verdict": "passed" | "needs_fix" | "failed",
  "issues": [
    {
      "severity": "error" | "warning",
      "category": "doc_claim_not_in_code" | "code_feature_not_documented" | "wrong_dependency" | "incorrect_error" | "behavior_mismatch" | "broken_symbol_ref",
      "docLocation": "lat.md/auth#OAuth Flow#Token Refresh",
      "codeLocation": "src/auth/token.ts:42",
      "description": "文档声明 refreshToken 返回类型为 Token，但源码返回类型为 { accessToken, refreshToken }",
      "suggestion": "更新文档返回类型为 { accessToken: string, refreshToken: string }"
    }
  ]
}
```

验证完成后输出 SUMMARY：
- 总问题数
- 按严重程度/类型分类
- 推荐操作：自动修复 / 需人工判断
```

#### 并行执行

所有模块的验证 agent **同时启动**（使用 Agent 工具的非 background 模式）。

#### 结果汇总 + 修复

汇总所有验证结果后，根据严重程度决定修复策略：

- **error 级别 + 可自动修复**（如符号引用错了、参数名过时）→ 自动修复
- **error 级别 + 需判断**（如行为描述不准确）→ 报告给用户
- **warning 级别**（如遗漏了次要 feature）→ 记录但不阻塞

---

## 触发方式

| 你想干什么 | 怎么说 |
|-----------|--------|
| 🆕 首次生成文档 | `写文档` 或 `weave docs` |
| 🔄 补充/更新文档 | `补充文档` 或 `update docs for <module>` |
| ✅ 验证文档准确性 | `验证文档` 或 `verify docs` |
| 🏗️ 为新模块写文档 | `给 <module> 写文档` |
| 🔗 添加 wiki 引用 | `给 <module> 添加 cross-ref` |

---

## 关键规则

1. **Phase 0 必须先跑**：不要凭已有知识写文档，必须先扫描项目代码获取真实结构
2. **Phase 5 不可跳过**：所有文档生成/更新后，必须做并行源码级验证
3. **Tier 3 结构化数据的生成时机**：在 Phase 2 生成完 markdown 文档后立即生成，保证 schema 反映最新设计
4. **@lat: 注解不冗余**：一个 leaf section 对应一个 `@lat:` 注解，不重复
5. **第一次运行覆盖所有模块**：后续运行只处理变更的模块
6. **Section ID 不可变**：一旦发布，不轻易修改 section ID（wiki link 会断）
7. **Project.md 是唯一入口**：AI agent 到达项目后首先读 Project.md，决定加载哪些模块文档
8. **永不自动 commit**：文档生成和验证完成后，将结果报告给用户，由用户决定何时、以什么 message 提交。不允许在流程末尾执行 `git add`、`git commit` 或 `git push`

---

---

## 端到端示例：为 AI agent 准备一个完整的文档体验

编写完成后，项目的文档应该能让一个**从未看过源码的 AI agent** 在几分钟内准确回答以下所有问题。用 glue-engineer 在 doc-weaver 上测试时，Explore agent 仅凭文档（0 行源码）就给出了准确的项目理解。

以下是一个成功的端到端验证流程：

### 验证方法

1. 派出一个 Explore 类型的子 agent，只给它极模糊的提示词（如"帮我看下这个项目是干什么的、怎么用、实现原理"），不指定读什么文件
2. 检查 agent 的报告是否能准确回答：
   - 项目是做什么的（一句话总结）
   - 核心 CLI 用法和技术栈
   - 模块划分和依赖关系
   - 关键设计决策
3. 如果 agent 依赖了自己的知识而不是文档引用 → 文档不够，需要补
4. 如果 agent 漏掉了重要模块 → 文档索引不足，检查 wiki link 覆盖
5. 如果 agent 给出了错误理解 → 文档表述有歧义，需要修正

### 成功指标

| 指标 | 达标标准 |
|------|---------|
| 项目概述 | Agent 能给出准确的一句话总结 |
| CLI 用法 | Agent 能列出主要命令和参数 |
| 架构理解 | Agent 能画出模块依赖关系图 |
| 设计决策 | Agent 能列出 3+ 个关键设计决策 |
| 无需源码 | Agent 未主动读任何 `.py`/`.ts` 等源码文件 |
| 无幻觉 | Agent 所有结论都在文档中有可靠引用 |

### 失败模式

| 现象 | 根因 | 修复 |
|------|------|------|
| Agent 回答"我不确定" | 文档覆盖不足 | 补写该模块的 Tier 2 文档 |
| Agent 说"以 xxx 库为例"但用了自己的知识 | 缺少使用示例 | 在 Project.md 或 README 中添加最小示例 |
| Agent 漏掉某个核心模块 | 索引缺失 | 检查 lat.md → Project.md 的 wiki link 链是否完整 |
| Agent 错误描述实现方式 | 文档行为描述与源码不一致 | Phase 5 验证未通过，修正文档或代码 |