# glue-engineer — lat.md 知识图配置

本项目使用 [lat.md](https://www.npmjs.com/package/lat.md) 维护结构化知识图谱，记录架构、设计决策和测试规范到 `lat.md/` 目录。

## 工作前

- 运行 `lat locate "Section Name"` 查找相关章节
- 运行 `lat expand "user prompt"` 展开 `[[refs]]` 为文件位置

## 任务后检查清单（必需）

每次任务完成后，**必须**执行：

- [ ] 更新 `lat.md/`（如果添加/修改了功能、架构、测试或行为）
- [ ] 运行 `lat check`（所有 wiki 链接和代码引用必须通过）

## 命令

```bash
lat locate "Section Name"      # 精确/模糊查找章节
lat refs "file#Section"        # 查找引用某章节的内容
lat search "natural language"  # 语义搜索所有章节
lat expand "user prompt text"  # 展开 [[refs]] 为实际位置
lat check                      # 验证所有链接和代码引用
```

## 语法速查

- **Section ID**: `lat.md/path/to/file#Heading#SubHeading`
- **Wiki 链接**: `[[target]]` 或 `[[target|alias]]`
- **源码链接**: `[[polyglot/router.py#import_backend]]`
- **代码注解**: `# @lat: [[section-id]]` (Python) / `// @lat: [[section-id]]` (JS/TS/Rust/Go)
- **前导段落**: 每个 section 必须有 ≤250 字符的前导段落

## 项目结构

- `lat.md/` — 知识图谱文档目录
  - `lat.md` — 根索引（所有文档清单）
  - `Project.md` — 项目概述
  - `Architecture.md` — 架构设计
  - `Glossary.md` — 术语表
  - `polyglot.md` — 核心 CLI 包
  - `deep.md` — v4 Deep Mode
  - `glue.md` — v3 Glue Engine
  - `backends.md` — 6 语言后端
  - `common.md` — 共享基础设施
  - `vtree.md` — VTree 解析器
  - `agents.md` — 子 agent 定义
  - `evals.md` — 评估清单
  - `scripts.md` — 辅助脚本
  - `tests.md` — 测试规范