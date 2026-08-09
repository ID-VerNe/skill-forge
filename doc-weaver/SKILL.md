---
name: doc-weaver
version: 2.1.0
description: "项目文档编织器。基于lat.md格式规范，使用lat.md工具链，自动为项目生成覆盖所有模块的知识图谱文档到docs/目录，并用lat check做验证。当用户说'写文档'、'补充文档'、'生成项目文档'、'document this project'、'weave docs'时触发。文档主要供AI agent阅读，而非人类。"
metadata:
  requires: [lat.md]
---

# doc-weaver v2.1 — 基于 lat.md 工具链的文档编织器

> **核心理念**: 使用 lat.md 的工具链，写文档到 `docs/` 目录，通过目录 junction/symlink 让 `lat.md/` → `docs/`，使 `lat check` 能直接验证文档。

## 前置条件

目标项目必须已安装 `lat.md` CLI 并创建了 `lat.md/` → `docs/` 的目录 junction：

```bash
npm install -g lat.md
# 在项目根目录：
mkdir -p docs
lat init                     # 创建 lat.md/ 目录
mv lat.md/*.md docs/         # 把初始文件移到 docs/
rmdir lat.md                 # 删除原目录
# Windows: 创建 junction
cmd.exe /c "mklink /J lat.md docs"
# Linux/macOS: 创建 symlink
ln -s docs lat.md
```

## 文档格式规范（继承自 lat.md）

项目文档存放在 `docs/` 目录下，遵循 lat.md 的格式规范。

### 目录结构

```
docs/
  lat.md                  # 根索引：所有文档的入口点
  Project.md              # [Tier 1] 入口文档：一句话描述 + 模块清单
  Architecture.md         # 架构总览：模块依赖关系、数据流向、技术选型
  Glossary.md             # 术语表：每个概念在项目中定义且仅定义一次
  <module>.md             # [Tier 2] 模块知识文档，每个模块一个文件
  <module>/               # 子模块目录（可选）
    <submodule>.md
schema/                   # [Tier 3] 结构化数据（项目根目录，不是 docs/ 下）
  graph.json              # 全模块依赖图（必需）
  <module>.schema.json    # 模块结构化 schema（可选）
```

> **注意**: `schema/` 目录放在项目根目录，而非 `docs/` 下。因为 `lat check` 只接受 `lat.md/` 目录下的 `.md` 文件，JSON 文件放在 `docs/schema/` 会导致验证错误。

### Section ID

每个 section 拥有层次化 ID：`file#Heading#Subheading#Subsubheading`

- 第一段：项目根相对路径，**去掉 `.md` 扩展名**
- 示例：`docs/backends#Supported Languages#Python`
- 根标题（h1）在引用时可省略（解析器自动补全）
- 源码引用：`[[lib.rs#GpuMode]]`（项目相对路径，不是 `src/` 前缀）

### Wiki Link 语法

```
// @lat: [[lib.rs#GpuMode]]     // TypeScript, JavaScript, Rust, Go, C
# @lat: [[lib.rs#GpuMode]]      // Python
```

`@lat` 注解的 section ID 使用**短格式**：`[[file.rs#SymbolName]]` 或 `[[file#Heading#Subheading]]`，不要使用完整层级路径 `[[lat.md/file#h1#h2#h3]]`。

### 前文规则

每个 section **必须**有前导段落：紧跟在 heading 后的第一段文字，**≤250 字符**（不计 wiki link 语法），保证搜索摘要的简洁性。

**前导段落必须是有意义的描述，而非通用模板**。以下写法是禁止的：
- ❌ `"Key concepts overview: ..."` — 无信息量
- ❌ `"Dependencies overview: ..."` — 无信息量
- ❌ `"Error conditions overview: ..."` — 无信息量

✅ 正确写法：`"Core types shared across both binaries — GpuMode, Config, AppOverride, and Error — used by the CLI and GUI entry points."`

### Wiki Link 语法

| 语法 | 含义 |
|------|------|
| `[[target]]` | 链接到 `target.md` 文件的根 section |
| `[[target#Heading]]` | 链接到 `target.md` 中的特定 heading |
| `[[target\|alias]]` | 带别名的链接 |
| `[[lib.rs#GpuMode]]` | 链接到源码符号（项目相对路径，无 `src/` 前缀） |

**关键规则**：文档中的源码引用格式为 `[[path/to/file.rs#SymbolName]]`，**绝对禁止**使用 `[[src/path/to/file.rs#SymbolName]]`（`src/` 前缀会导致 `lat check` 报 `file not found` 错误）。

### 源码注解

```
// @lat: [[lib.rs#GpuMode]]     // TypeScript, JavaScript, Rust, Go, C
# @lat: [[lib.rs#GpuMode]]      // Python
```

`@lat` 注解的 section ID 使用**短格式**：`[[file.rs#SymbolName]]` 或 `[[file#Heading#Subheading]]`，不要使用完整层级路径 `[[lat.md/file#h1#h2#h3]]`。

---

## 核心工作流

整个流程分为 5 个阶段，按顺序执行。**Orchestrator agent 必须为每个 Phase 派出独立的子 agent 执行**，而非自己直接写文件。

### 架构总览

```
你（主 agent）
  └── Orchestrator（子 agent）
       ├── Phase 0: 自己扫描项目
       ├── Phase 1: 子 agent → 写 Tier 1 文档
       │   └── 完成后跑 lat check → 不通过则修复重试
       ├── Phase 2: 并行子 agent（每个模块一个）
       │   ├── agent → <module>.md
       │   ├── agent → <module>.md
       │   └── ...
       │   └── 完成后跑 lat check → 不通过则修复重试
       ├── Phase 3: 子 agent → 生成结构化数据
       │   └── 完成后跑 lat check → 不通过则修复重试
       ├── Phase 4: 子 agent → 添加 @lat 注解
       │   └── 完成后跑 lat check → 不通过则修复重试
       └── Phase 5: 子 agent → 最终验证
            └── 跑 lat check → 修复所有错误 → 报告结果
```

### Phase 0：项目扫描（Orchestrator 自己执行）

在开始写任何文档之前，**先扫描整个项目**收集上下文：

1. 读取 `package.json` / `Cargo.toml` / `pyproject.toml` / `go.mod` 获取项目元数据和技术栈
2. 读取 `README.md` / `CLAUDE.md` 获取现有项目描述
3. 扫描源码根目录，识别所有顶级模块/包
4. 对每个模块，快速扫描其 exports、关键 types/interfaces、外部依赖
5. 识别 entry points（main、HTTP handlers、CLI commands）

**输出**：一份项目全景清单，包含模块列表、每个模块的关键符号、模块间依赖关系。

### Phase 1：生成 Tier 1 入口文档

**派出一个子 agent**，生成 `docs/` 目录下的索引和入口文件：

**`docs/lat.md`** — 根索引：
```markdown
# docs

- [[Project]] — 项目概述与模块清单
- [[Architecture]] — 架构设计与模块依赖
- [[Glossary]] — 术语表
- [[auth]] — 鉴权模块
- [[api]] — API 路由层
```

**`docs/Project.md`** — 项目入口文档（Tier 1，~1K tokens）：
```markdown
# Project

**Tech Stack**: TypeScript + Node.js + PostgreSQL + Redis
**Architecture Pattern**: Clean Architecture

## Modules

- [[auth]] — 用户鉴权，OAuth 2.0，JWT 管理
- [[api]] — HTTP API 路由与中间件

## Dependency Graph

依赖关系见 [[Architecture#Module Dependencies]]。
```

**`docs/Architecture.md`** — 架构总览

**`docs/Glossary.md`** — 术语表

**Phase 1 输出检查清单**（子 agent 必须遵守）：
- [ ] 每个文件有 `# Title` 根标题
- [ ] 每个 section 有 ≤250 字符的前导段落
- [ ] `lat.md` 包含了所有文档的 wiki link 条目
- [ ] 所有 wiki link 指向的文件将在 Phase 2 中创建
- [ ] 源码引用使用项目相对路径，**不加 `src/` 前缀**

**完成后**：Orchestrator 跑 `lat check`，不通过则让子 agent 修复，通过后才进入 Phase 2。

### Phase 2：生成 Tier 2 模块知识文档

**并行派出子 agent（每个模块一个）**，对 Phase 0 识别出的每个模块生成一个 markdown 文档到 `docs/` 下：

子 agent 的 prompt 模板（**必须包含以下约束**）：

```
你正在为 {module_name} 模块写文档。
输出文件：docs/{module_name}.md

## 结构要求

# {Module display name}

一句概述（≤250 字符）：这个模块负责什么、为什么存在。

## Key Concepts

### {概念名}

概念解释（≤250 字符）。内部机制概要。

Reference: [[file.rs#SymbolName]]  （项目相对路径，不加 src/ 前缀）

### {概念名 2}

...

## Dependencies

列出该模块依赖的其他模块和外部 crate。**必须包含两项**：
1. 内部模块依赖（wiki link 链接到其他模块文档）
2. 外部 crate 依赖（列出 crate 名称和用途）

## Consumed By

哪些模块使用本模块：

- [[other_module]] — 使用说明

## Error Conditions

该模块特有的错误条件。**只列本模块产生的错误**，不要重复其他模块已列出的错误。

## 关键规则（必须遵守）

1. 每个 section 必须有 ≤250 字符的前导段落，**且必须是有意义的描述**。禁止使用 `"Key concepts overview: ..."`、`"Dependencies overview: ..."` 等无信息量的通用模板。
2. 涉及其他模块的必须用 `[[wiki link]]`
3. 涉及源码符号的必须用 `[[file.rs#SymbolName]]`（项目相对路径，**不加 src/ 前缀**）
4. 不要创建重复的 section（检查是否有内容相同的 heading）
5. 一个概念只写一次，不要在不同 section 里重复描述
6. 对每个有文档价值的函数/结构体/枚举，在源码中找到对应位置并记录引用
7. 在 Dependencies 节中，**同时列出内部模块和外部 crate**，两者缺一不可
8. **源码引用格式必须是 `[[file.rs#SymbolName]]`**，绝对禁止 `[[src/file.rs#SymbolName]]`
```

**并行执行**：
- 所有模块的 agent 同时启动（使用 Agent 工具，同一 turn 全部派出）
- 每个 agent 独立写自己的文件，互不依赖

**完成后**：Orchestrator 跑 `lat check`，不通过则让对应模块的子 agent 修复，全部通过后才进入 Phase 3。

### Phase 3：生成结构化数据（必需）

**派出一个子 agent**，生成机器可读的 JSON 结构化数据到 `schema/`（项目根目录）：

**必须生成** `schema/graph.json` — 全模块依赖图：
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

**可选生成** `docs/schema/<module>.schema.json` — 各模块的 exports、dependencies、errors 等结构化描述。

**完成后**：Orchestrator 跑 `lat check`，不通过则修复，通过后才进入 Phase 4。

### Phase 4：添加源码注解

**派出子 agent（每个模块一个，或所有模块合并到一个 agent）**，在源码中添加 `@lat:` 注解。规则：

1. 对 `docs/` 中每个描述了代码行为的 leaf section，在对应源码中添加 `# @lat: [[section-id]]` 或 `// @lat: [[section-id]]`
2. 放在对应的函数/类/测试前一行
3. 不要重复——每个 section 对应一个注释
4. 不要在简单 getter/setter 或明显无业务含义的代码上添加
5. 源码引用路径使用项目相对路径，**不加 `src/` 前缀**
6. 注意：Python 文件用 `# @lat:`，JavaScript/TypeScript/Rust/Go/C 文件用 `// @lat:`
7. **覆盖范围要求**：所有文档中提到的函数、结构体、枚举、常量都应有 `@lat` 注解。包括有文档价值的私有函数（如 `load_config()`、`save_state()` 等有业务含义的私有辅助函数）。
8. **`@lat` 注解格式**：使用短格式 `[[file.rs#SymbolName]]` 或 `[[file#Heading#Subheading]]`，**不要**使用完整层级路径如 `[[lat.md/file#h1#h2#h3]]`。`lat check` 接受的格式是 `[[file.rs#SymbolName]]`（文件引用符号）或 `[[file#Heading#Subheading]]`（文档引用）。

**完成后**：Orchestrator 跑 `lat check`，检查 `@lat:` 注解是否指向真实存在的 section。不通过则修复，通过后才进入 Phase 5。

### Phase 5：最终验证

**派出一个子 agent**，执行最终验证。**该子 agent 的职责是运行 `lat check` 并修复所有错误**，直到全部通过。

```bash
# 从项目根目录运行
cd <project-root>
lat check
```

#### 验证规则

`lat check` 自动检查：
1. **Wiki 链接完整性**：所有 `[[target]]` 引用是否指向真实存在的文件或 section
2. **源码引用完整性**：所有 `[[path/to/file#symbol]]` 引用是否指向真实存在的文件
3. **前导段落规则**：每个 section 是否有 ≤250 字符的前导段落
4. **根索引完整性**：根索引 (`lat.md`) 是否列出了所有文档
5. **代码引用检查**：`# @lat:` / `// @lat:` 注解是否指向真实存在的 section

#### 修复策略

- 如果 `lat check` 报错，按错误信息逐条修复：
  - `broken link` → 修复 wiki link 路径或创建缺失的目标文件
  - `no leading paragraph` → 在 heading 后添加前导段落
  - `missing entries` → 在根索引中添加缺失的文档条目
  - `file not found` → 修复源码引用路径（使用项目相对路径，不加 `src/` 前缀）
  - `code ref not found` → `@lat:` 注解指向的 section 不存在，修正注解或修正 section ID
  - `section not covered` → 文档中的 section 没有对应的 `@lat:` 注解，添加注解
- 修复后重新运行 `lat check` 直到全部通过
- **重复修复的次数上限为 5 轮**，超过后向用户报告剩余问题

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
2. **Phase 5 不可跳过**：所有文档生成/更新后，必须运行 `lat check` 做验证
3. **Phase 5 使用 `lat check` 而非自定义 agent**：利用 lat.md 工具链的机械验证能力，稳定且快速
4. **@lat: 注解不冗余**：一个 leaf section 对应一个 `@lat:` 注解，不重复
5. **@lat: 注解覆盖完整**：所有有文档价值的函数（包括私有辅助函数）都应有注解
6. **第一次运行覆盖所有模块**：后续运行只处理变更的模块
7. **Section ID 不可变**：一旦发布，不轻易修改 section ID（wiki link 会断）
8. **Project.md 是唯一入口**：AI agent 到达项目后首先读 Project.md，决定加载哪些模块文档
9. **源码引用不加 `src/` 前缀**：使用项目根相对路径，如 `[[lib.rs#GpuMode]]`。**绝对禁止** `[[src/lib.rs#GpuMode]]`
10. **永不自动 commit**：文档生成和验证完成后，将结果报告给用户，由用户决定何时、以什么 message 提交。不允许在流程末尾执行 `git add`、`git commit` 或 `git push`
11. **每个 Phase 完成后立即验证**：Orchestrator 在每个 Phase 完成后跑 `lat check`，不通过不进下一 Phase
12. **所有 Phase 需派出子 agent**：Phase 1-5 全部由独立的子 agent 执行，Orchestrator 只负责协调和验证
13. **Dependencies 节必须同时包含内部模块和外部 crate**：两者缺一不可，避免不同 agent 的粒度不一致
14. **禁止重复内容**：同一概念在整个文档集中只出现一次，子 agent 应先检查是否存在再写
15. **前导段落禁止通用模板**：禁止使用 `"Key concepts overview: ..."`、`"Dependencies overview: ..."` 等无信息量的写法。每个前导段落必须是有意义的描述
16. **`@lat` 注解使用短格式**：`[[file.rs#SymbolName]]` 或 `[[file#Heading#Subheading]]`，**不要**使用完整层级路径 `[[lat.md/file#h1#h2#h3]]`
17. **`schema/` 放在项目根目录**：非 `docs/schema/`，因为 `lat check` 只接受 `lat.md/` 下的 `.md` 文件，JSON 在 `docs/schema/` 会导致验证错误

---

## 端到端示例：为 AI agent 准备一个完整的文档体验

编写完成后，项目的文档应该能让一个**从未看过源码的 AI agent** 在几分钟内准确回答以下所有问题。

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
| Agent 漏掉某个核心模块 | 索引缺失 | 检查 root index → Project.md 的 wiki link 链是否完整 |
| Agent 错误描述实现方式 | 文档行为描述与源码不一致 | Phase 5 验证未通过，修正文档或代码 |