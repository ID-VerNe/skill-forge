---
name: operations-guide
description: 操作指引章节的生成指引 — 如何继续、回滚、启动等
---

## 操作指引 — 生成指引

AI 从项目文件推断以下内容，生成完整的操作指引。

### 如何继续

向下一任 AI 交代步骤：

```markdown
### 如何继续

1. 阅读本 handoff 文档了解上下文
2. 执行 `git log --oneline -5` 查看最新提交
3. 处理「尚未完成的工作」中的高优先级项
```

- 步骤要具体，可执行
- 不需要读源码就能理解
- 如果有依赖的外部服务（API 密钥、数据库等），注明需要先配置

### 如何回滚

```markdown
### 如何回滚

回滚到本次会话开始前的状态：
```bash
git reset --hard <baseline-commit-hash>
```

回滚到某个特定 commit：
```bash
git reset --hard <commit-hash>
```
```

- 如果本次会话有多个 commit，提供回滚到基线的命令
- 如果有数据迁移，注明需要额外回滚迁移

### 项目启动

从 `package.json` 的 `scripts` 字段或等价文件自动检测：

```markdown
### 项目启动

- 前端: `pnpm dev`（监听 5173 端口）
- 后端: `go run main.go`（监听 8080 端口）
- 数据库: `docker compose up -d db`
```

检测逻辑：

| 文件/内容 | 对应命令 |
|-----------|---------|
| `package.json` 的 `"dev"` | 前端开发服务器 |
| `Makefile` 的 `run` | 项目启动 |
| `Dockerfile` + `docker-compose.yml` | Docker 启动 |
| `go.mod` 且有 `main.go` | `go run .` |
| `pyproject.toml` | `poetry run` 或 `uv run` |
| 没有明显启动方式 | 注明"未检测到启动方式" |

### 注意事项

从对话中提取用户偏好，例如：

```markdown
### 注意事项

- 用户偏好用 pnpm 而非 npm
- 不要在 CI 环境外执行 `pnpm build`（性能原因）
- 敏感文件（.env）不提交
- 改 CSS 前先检查 Tailwind 有没有现成的 utility class
```

### 输出格式

```markdown
## 5. 操作指引

### 如何继续
1. ...
2. ...
3. ...

### 如何回滚
...

### 项目启动
...

### 注意事项
- ...
- ...
```