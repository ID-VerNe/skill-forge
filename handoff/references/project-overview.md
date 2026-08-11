---
name: project-overview
description: 项目概述章节的生成指引
---

## 项目概述 — 生成指引

AI 从项目元数据文件和目录结构推断，自动填充以下内容。

### 1. 项目名称、类型、技术栈

检测以下元数据文件，推断项目类型和技术栈：

| 元数据文件 | 推断信息 |
|------------|---------|
| `package.json` | 前端/Node 项目，依赖列表，框架（React/Vue/Svelte） |
| `pyproject.toml` | Python 项目，打包工具（poetry/uv/pip） |
| `go.mod` | Go 项目，模块名 |
| `Cargo.toml` | Rust 项目 |
| `composer.json` | PHP 项目 |
| `requirements.txt` | Python 项目（pip） |
| `pom.xml` / `build.gradle` | Java 项目 |

如果找不到元数据文件，通过目录结构推断：
- 有 `src/`、`components/`、`app/` → 前端框架
- 有 `src/main.go` → Go
- 有 `src/main.py` → Python
- 有 `app.py`、`manage.py` → Django/Flask

### 2. 前端包管理器

检测以下锁文件确定包管理器：

| 锁文件 | 包管理器 |
|--------|---------|
| `pnpm-lock.yaml` | pnpm |
| `package-lock.json` | npm |
| `yarn.lock` | yarn |
| `bun.lockb` | bun |

如果没有锁文件，检查目录下是否有 `node_modules/.bin/pnpm` 等。

### 3. 前端目录

- 读 `package.json` 的 `scripts` 字段了解启动命令
- 看目录结构确定前端代码位置（`src/`、`app/`、`client/` 等）

### 4. 一句话说明项目是干什么的

从 README、package.json 的 description 字段、或代码结构推断项目用途。

### 输出格式

```markdown
## 1. 项目概述

- **项目名称**: <从元数据推断>
- **项目类型**: <Web 应用 / CLI 工具 / 库 / ...>
- **技术栈**: <如 React 18 + TypeScript + Vite>
- **前端包管理器**: <pnpm / npm / yarn>
- **前端目录**: <src/ 或 app/>
- **一句话说明**: <项目是干什么的>
```