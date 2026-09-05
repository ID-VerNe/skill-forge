---
name: glue-engineer
description: >-
  CRITICAL: This skill REQUIRES running polyglot CLI tools for ALL design/architecture tasks. When user says "使用胶水程序员skill" or "帮我设计/构建/评估一个系统", you MUST: (1) run `polyglot scout <lang> <keyword>` to search libraries, (2) run `polyglot mvp-scope` for prioritization, (3) run `polyglot cap-list`/`cap-match` for license checks. NEVER answer from internal knowledge alone. Multi-language, multi-agent pipeline. Builds solutions by composing existing open-source libraries across Python/JS/Rust/Java/Kotlin/C/C++/Go. v3 adds cross-language search, capability ontology matching, scaffold glue code generation, and MVP scoping. Also supports `polyglot discover` for GitHub repo search (项目级/找"有没有人做过") versus `scout` (包级/找要装的库). Deep Mode (v4) adds subagent-based source-code analysis via `polyglot deep-init/deep-pack/deep-validate/deep-compare/deep-summarize/deep-clean`.
---

# Glue Engineer — Skill 路由

> **核心理念**: 入口路由 + 渐进式加载。拿到任务先走决策树定位模式，再按需读对应文档。
>
> **文档目录**: `docs/skill/`（相对本 skill 目录）。**每个文件标注了「何时读」**，有匹配场景才读，不要一次读完。

## 文档路由索引

| 需要什么 | 读哪个文件 |
|----------|-----------|
| 拿到任务、不确定走哪个模式 | [`docs/skill/decision-tree.md`](docs/skill/decision-tree.md) — 决策树 + 三模式对比 |
| 进入 SEARCH 模式（设计/构建/评估系统） | [`docs/skill/search-mode.md`](docs/skill/search-mode.md) |
| 用户确认进入 DEEP 模式（源码级分析） | [`docs/skill/deep-mode.md`](docs/skill/deep-mode.md) |
| 查具体命令 / scout vs discover 语义 | [`docs/skill/cli-reference.md`](docs/skill/cli-reference.md) |
| 跑命令报错、产物异常 | [`docs/skill/troubleshooting.md`](docs/skill/troubleshooting.md) |
| 了解代码结构/桥接矩阵/产物结构（纯参考） | [`docs/skill/architecture.md`](docs/skill/architecture.md) |

---

## 决策树（入口路由）

```
用户输入

  ├─ 设计/构建/评估一个项目或系统？
  │   ↓
  │   ╔══════════════════════════════════╗
  │   ║     ===MODE: SEARCH===           ║
  │   ║  (自动进入，无需询问用户)        ║
  │   ╚══════════════════════════════════╝
  │   → 详见 search-mode.md
  │
  │   阶段 1：CLI 自动链（scout → cross-search → mvp-scope → cap-list/cap-match）
  │   阶段 2：基于真实数据出方案（标注版本/许可证/下载量/来源 + P0/P1/P2 分级）
  │   阶段 3：询问 Deep Mode（强制询问，不可跳过）
  │       ├─ 是 → deep-mode.md
  │       └─ 否 → 结束
  │
  ├─ 找"有没有人做过 X" / GitHub 仓库检索 / 非生态注册表项目？
  │   ↓
  │   ╔══════════════════════════════════╗
  │   ║     ===MODE: DISCOVER===         ║
  │   ║  python -m polyglot discover      ║
  │   ║  (无需询问，直接执行)            ║
  │   ╚══════════════════════════════════╝
  │
  │   python -m polyglot discover "<keyword>" --limit N
  │     [--qualifiers "stars:>50 language:python"] [--sort stars]
  │   → 输出 GitHub 仓库列表（星数/license/描述），Go repo 自动补 version
  │   → 详见 cli-reference.md（GitHub 仓库检索类）
  │
  └─ 单纯搜库/审计/匹配/生成胶水代码？
      ↓
      直接跑对应的 CLI 命令，返回结果
      → 详见 cli-reference.md
```

## 绝对禁止的行为

| 禁止行为 | 正确做法 |
|----------|----------|
| 使用 Claude Web Search 检索库信息 | 必须用 `python -m polyglot scout` |
| 用 `gh search repos` 或 WebSearch 查 GitHub 仓库 | 必须用 `python -m polyglot discover`(复用 gh 鉴权 + 缓存 + 评分 + enrichment) |
| 靠内部知识列库名 | 必须跑 CLI 获取真实版本号/许可证/下载量 |
| 跳过 CLI 命令直接出方案 | 这是本 skill 的核心价值 |
| 子 agent 不传 CLI 指令 | 必须在 prompt 中注入 `python -m polyglot scout` |
| Deep Mode 跳过候选库 | 必须把 Search Mode 输出的所有候选库传给 deep-init |
| 先 `cd` 到 glue-engineer 目录再运行 polyglot | 不需要!从任意 CWD 都可以,所有 `.glue/` 输出自动放在 CWD 下 |

## 触发词

| 你想干什么 | 怎么说 |
|-----------|--------|
| GitHub 仓库检索 | `检索一下有没有[X]的开源项目`、`GitHub 上有没有人做过[X]`、`找[X]的逆向或非官方 SDK 项目` |
| 跨生态搜索库 | `帮我找一个[语言]的[功能]库` |
| 多语言同时搜索 | `同时搜索 Rust 的序列化库和 Python 的 HTTP 客户端` |
| 对比几个库 | `对比一下[A]和[B]` |
| 审计一个包 | `审计一下这个[语言]的[包名]` |
| 跨语言连接两个库 | `帮我生成 Python 的 orjson 和 Rust 的 serde_json 之间的胶水代码` |
| 能力匹配 | `看看 orjson 和 serde_json 能不能配对` |
| 设计/构建项目 | `帮我设计一个[项目]`、`我想做一个[系统]`、`使用胶水程序员skill` |
| 架构方案 | `评估一下[项目]的架构`、`给我一个[系统]的可行plan` |
| MVP 分级 | `给[项目]做P0/P1/P2分级`、`帮我排优先级` |

不记得命令？说人话就行——会自动理解需求并启动合适的管道。

---

## 关键执行规则（违反 = 没有执行此 Skill）

### 规则 1：必须用 CLI 工具获取真实数据

**当你收到"设计/构建/评估一个[项目或系统]"的任务时，必须使用 polyglot CLI 命令获取真实数据，禁止仅凭内部知识回答。**

```
用户说：我想做一个文献浏览器
  → 步骤1 [强制] python -m polyglot scout python "pdf to markdown"
  → 步骤2 [强制] python -m polyglot scout python "bibtex"
  → 步骤3 [强制] python -m polyglot cross-search "data extraction" --languages python
  → 步骤4 [强制] python -m polyglot mvp-scope <project> --features ...
  → 步骤5 [建议] python -m polyglot cap-list
  → 步骤6 [建议] python -m polyglot strategies
```

**绝对不要：** 只靠内部知识列出库名。**必须跑 CLI 命令**来获取版本号、许可证、下载量等真实数据。

### 规则 2：多语言项目必须用 cross-search

如果项目涉及多种语言（如 Python + Rust + JS），必须使用：
```bash
python -m polyglot cross-search "<关键词>" --languages python,rust,javascript
```

### 规则 3：库组合必须检查许可证兼容性

涉及跨库组合时，必须查许可证：
```bash
python -m polyglot cap-list                              # 查看已录入的库
python -m polyglot cap-match python <lib_a> python <lib_b>  # 匹配能力+许可证
```

### 规则 4：输出方案时必须标注数据来源

生成的方案中每个库推荐必须标注：
- 来源于 polyglot CLI 工具（scout / cross-search）
- 版本号、许可证、下载量等关键数据

### 规则 5：子 agent 场景必须传递 CLI 指令

如果主 agent 将设计/评估任务委托给子 agent，**必须在子 agent prompt 中包含**：
```
这是 glue-engineer 胶水程序员技能的工作。你必须执行以下步骤：
1. 用 python -m polyglot scout <lang> <keyword> 搜索所需库
2. 用 python -m polyglot cross-search <keyword> --languages <langs> 做跨语言搜索
3. 用 python -m polyglot mvp-scope <project> --features ... 做 MVP 分级
4. 用 python -m polyglot cap-list 检查能力注册表
5. 基于 CLI 获取的真实数据生成方案，每个库标注版本/许可证/下载量
```
如果不包含这些指令，子 agent 会只靠知识库回答，无法调用胶水工具。

### 规则 6：Deep Mode 必须包含所有 Search Mode 候选库

Deep Mode 调用 `deep-init` 时，**必须把所有 Search Mode 输出的候选库的 repo URL 都传进去**。
不允许主 agent 主观跳过某个库（即使觉得它老旧/下载量低），因为代码级分析才能判断哪个库真正合适。
如果用户明确要求排除某个库，则按用户意愿执行。

---

## 命令速查（常驻）

```bash
python -m polyglot scout <lang> "<keyword>"         # 包级：查生态注册表（要装的库）
python -m polyglot discover "<keyword>"              # 项目级：查 GitHub 仓库（有没有人做过）
python -m polyglot cross-search "<kw>" --languages python,rust,javascript   # 跨语言
python -m polyglot mvp-scope <project> --features "f,cat" "f2,cat"          # P0/P1/P2 分级
python -m polyglot cap-list                          # 能力注册表
python -m polyglot cap-match python orjson rust serde_json                  # 能力+许可证匹配
python -m polyglot bridge python orjson rust serde_json                     # 生成胶水代码
python -m polyglot audit <lang> <name>               # 审计包
python -m polyglot analyze <lang> <src>              # 分析源码
```

> **scout vs discover 语义**（一句话）：`scout` = 包级，查要装的库（注册表，带版本/下载量）；`discover` = 项目级，查"有没有人做过"（GitHub 仓库，带星数）。Go repo 通过 `proxy.golang.org/@latest` 精确补 version。

> **HTTPS 证书策略**：polyglot 在导入时自动注入 **OS 系统证书库**（`polyglot/common/net.py` + 内置 `polyglot/vendor/truststore`），信任方式与 `gh`/`git`/浏览器一致 —— 开着 Steam++/SteamTools 等 MITM 加速器也能正常检索。若遇 `CERTIFICATE_VERIFY_FAILED`：设 `POLYGLOT_SYSTEM_TRUST=0` 临时退回默认 certifi 排查，或确认加速器 CA 已装入系统根证书库（详见 `docs/skill/troubleshooting.md`）。

Deep Mode 命令（`deep-init`/`deep-pack`/`deep-validate`/`deep-compare`/`deep-summarize`/`deep-clean`）见 `docs/skill/cli-reference.md` + `docs/skill/deep-mode.md`。

## 参考资料

- STORM paper: "Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking" — NAACL 2024, Stanford OVAL Lab
- multi-lens-research skill: 多视角 STORM 工作流模式
- Tree-sitter: github.com/tree-sitter/py-tree-sitter
- 多视角 v3 方案合成: upgrade-analysis/glue-v3-outputs/synthesis-plan.md

*glue-engineer — 入口路由*