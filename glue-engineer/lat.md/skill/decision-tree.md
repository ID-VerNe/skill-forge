# 决策树 — 入口路由

根据用户输入选择 Search/Discover/Deep 模式的决策树,以及模式对比表。

> 何时读:**拿到任务、不确定走哪个模式时。** 一次读完。

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

## 三模式对比

Search/Discover/Deep 在触发条件、入口命令、检索粒度、是否询问用户、输出内容上的对比。

| | SEARCH | DISCOVER | DEEP |
|---|---|---|---|
| 触发 | 设计/构建/评估系统 | "有没有人做过 X" | 用户确认深度分析 |
| 入口 | `scout` + `cross-search` + `mvp-scope` | `discover` | `deep-init` |
| 检索粒度 | 包级(生态注册表) | 项目级(GitHub 仓库) | 源码级(克隆仓库) |
| 是否询问 | 自动进入 | 自动进入 | Search 尾部强制询问 |
| 主输出 | 完整方案 + P0/P1/P2 分级 | 仓库列表 + 星数/license | 架构报告 + 复用映射 + 集成方案 |
| 文档 | search-mode.md | cli-reference.md | deep-mode.md |

## 绝对禁止的行为

使用本 skill 时必须避免的 7 类错误行为,以及对应的正确做法。

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

用户自然语言表达与对应模式的映射表,方便快速匹配用户意图。

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

不记得命令?说人话就行——会自动理解需求并启动合适的管道。