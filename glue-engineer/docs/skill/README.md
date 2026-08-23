# 文档路由 — Glue Engineer Skill

本文档是 glue-engineer skill 的路由层,索引 8 个 docs/skill/ 文档,按需渐进加载对应文件。

> **这是 glue-engineer skill 的路由层。** 不要一次性读完全部文档——按需求渐进加载:每当你需要某个模式的具体流程/命令时,只读对应的文档文件。
>
> 文档目录:`docs/skill/`(相对于本 skill 目录)。**每个文件标注了「何时读」**,有匹配场景才读。

## 文件索引

按触发场景索引全部 6 个 docs/skill/ 文档,命中即读对应文件。

| 文件 | 何时读(触发场景) |
|------|------------------|
| [`docs/skill/decision-tree.md`](decision-tree.md) | 拿到一个任务、不确定走哪个模式时。含决策树 + 模式对比 |
| [`docs/skill/search-mode.md`](search-mode.md) | 进入 SEARCH 模式(设计/构建/评估系统)后,执行完整流程时 |
| [`docs/skill/deep-mode.md`](deep-mode.md) | 用户确认进入 DEEP 模式(候选库源码级分析)时 |
| [`docs/skill/cli-reference.md`](cli-reference.md) | 需要查具体命令(scout/discover/cross-search/cap-match/bridge/mvp-scope/audit/analyze)时 |
| [`docs/skill/troubleshooting.md`](troubleshooting.md) | 跑命令报错、缓存失效、深度分析产物异常时 |
| [`docs/skill/arch-overview.md`](arch-overview.md) | 纯参考,了解代码结构、桥接策略矩阵、生成代码示例时 |

## 快捷路径

常见任务 → 最快到达文档或命令的捷径。

- **搜 GitHub 仓库 / "有没有人做过 X"** → Discover 模式,直接跑:
  ```
  python -m polyglot discover "<keyword>" [--qualifiers "stars:>50 language:python"] [--sort stars] [--limit N]
  ```
  详细见 `docs/skill/cli-reference.md`(GitHub 仓库检索类)。
- **设计/构建/评估一个系统** → Search 模式,见 `docs/skill/search-mode.md`。
- **源码级深度分析候选库** → Deep 模式,见 `docs/skill/deep-mode.md`。
- **纯命令查询** → 见 `docs/skill/cli-reference.md` + `docs/skill/troubleshooting.md`。

## 命令速查(常驻)

全部 CLI 入口的速查表格,完整参数见 `cli-reference.md`。

```bash
python -m polyglot scout <lang> "<keyword>"         # 包级:查生态注册表(要装的库)
python -m polyglot discover "<keyword>"              # 项目级:查 GitHub 仓库(有没有人做过)
python -m polyglot cross-search "<kw>" --languages python,rust,javascript   # 跨语言
python -m polyglot mvp-scope <project> --features "f,cat" "f2,cat"          # P0/P1/P2 分级
python -m polyglot cap-list                          # 能力注册表
python -m polyglot cap-match python orjson rust serde_json                  # 能力+许可证匹配
python -m polyglot bridge python orjson rust serde_json                     # 生成胶水代码
python -m polyglot audit <lang> <name>               # 审计包
python -m polyglot analyze <lang> <src>              # 分析源码
```

> **scout vs discover 语义**(一句话):`scout` = 包级,查要装的库(注册表,带版本/下载量);`discover` = 项目级,查"有没有人做过"(GitHub 仓库,带星数)。Go repo 通过 `proxy.golang.org/@latest` 精确补 version。

## 架构概念(需要时再读)

代码结构、桥接策略矩阵、生成代码示例、Deep Mode 产物结构见 `docs/skill/arch-overview.md`(纯参考,不影响执行)。