---
name: project-conventions
description: 项目约定参考章节的生成指引 — 涵盖设计 token、架构约定、命名规范等
---

## 项目约定参考 — 生成指引

AI 根据检测到的项目类型，自动填充适用的约定参考。

### 对于前端 / UI 项目

检测以下文件中的设计 token / 约定：

| 检测目标 | 找到什么 | 示例 |
|----------|---------|------|
| `tailwind.config.*` | 自定义颜色、断点、字体 | `primary: '#1a73e8'` |
| CSS 变量定义（`*.css` 中的 `--*`） | 设计 token | `--color-primary`, `--spacing-md` |
| `DESIGN.md` | 设计系统文档 | 字体、颜色、圆角、间距 |
| `theme.ts` / `theme.js` | 主题对象 | MUI/Chakra 的自定义主题 |
| `.stitch/` | Stitch 设计系统 | 组件库定义 |
| PostCSS / UnoCSS 配置 | 原子化 CSS 框架 | purgeCSS 配置 |
| `stylelint.config.*` | CSS 规范 | 样式规则约定 |

输出示例：

```markdown
## 4. 设计规范参考

### 设计 Token

| Token | 值 | 用途 |
|-------|-----|------|
| `--color-primary` | `#1a73e8` | 主按钮、链接 |
| `--color-danger` | `#dc3545` | 删除、错误提示 |
| `--radius-md` | `8px` | 卡片、对话框圆角 |

### 字体

- 正文: Inter (400/500)
- 标题: Inter (600/700)

### 设计决策

- 主色选 #1a73e8 而非 #0d6efd：因为前者在浅色背景上对比度更高（WCAG AA 4.5:1）
- 圆角 8px 而非 4px：与当前 Sketch 设计稿保持一致
```

### 对于后端项目

检测以下约定：

| 检测目标 | 找到什么 |
|----------|---------|
| `go.mod` / `pyproject.toml` | 模块路径、命名约定 |
| API 路由文件 | 路由模式（`/api/v1/`） |
| 代码结构 | 分层架构（handler/service/repository） |
| lint 配置（`.golangci.yml`、`pylintrc`） | 代码规范约束 |
| 数据库 schema 文件 | 数据库约定（命名、迁移工具） |

### 对于通用项目

| 检测目标 | 找到什么 |
|----------|---------|
| `.editorconfig` | 缩进、编码风格 |
| `.gitignore` | 忽略规则 |
| `CONTRIBUTING.md` | 贡献指南、分支命名 |
| commit 历史 | 约定式提交风格（feat/fix/docs） |
| `CLAUDE.md` | AI 工作约定 |

### 自动填充规则

1. 精确记录找到的值，不要写"大概"、"类似"
2. 对每个 token/约定，说明为什么这样选（从对话中提取，或从代码注释推断）
3. 如果项目没有明显约定，写"本项目未检测到明显约定，建议协商建立"
4. 不要编造不存在的 token 或约定