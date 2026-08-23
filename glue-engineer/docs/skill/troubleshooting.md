# Troubleshooting（错误处理）

常见错误的症状、根因与解决方案对照表,覆盖 discover/audit/deep 全链路与 Windows 环境问题。

> 何时读：跑命令报错、缓存失效、深度分析产物异常时。

| 问题 | 原因 | 解决 |
|------|------|------|
| `discover` 返回 0 结果 | gh 搜索词太宽泛/太窄 | 换关键词或放宽 `--qualifiers`；如报 `gh CLI is not authenticated` → 提示用户 `gh auth login` |
| `discover` Go repo 未补 version | `proxy.golang.org` 对非 Go 模块返回 404 | 属正常（该 repo 不是 Go 模块），保留 gh 原始数据 |
| `audit go` 报 module not found | `proxy.golang.org/{module}/@latest` 返回 404 | 模块不存在或拼写错误；旧的 `api.gpkg.go.dev` 死域名路径已移除 |
| `deep-init` 克隆失败 | GitHub 不可达 | 确保 GitHub 能访问，减少 repo 列表 |
| `deep-validate` 显示全 `x` | subagent 还没跑 | 这正常——先跑 subagent 再验证 |
| `deep-compare` 打出 `DATA INCOMPLETE` 横幅 | 架构报告缺少必填字段 | 跑 subagent 补全，然后 `deep-validate` 确认全部通过再 rerun |
| `deep-compare` 排名只有 confidence 没有 coverage | 旧版 `comparison.json` 缓存 | 重建 workspace 重跑 `deep-pack` → subagent → `deep-validate` → `deep-compare` |
| Subagent 没有 Write 权限 | agent 定义中 `permissionMode` 配置不对 | 验证 agent 定义文件中的 `permissionMode: default` |
| 权限提示频繁 | 没有安装 `.claude/settings.json` | 安装权限 whitelist 后重新加载 |
| GBK 编码错误 | Windows 控制台编码问题 | 执行 `set PYTHONIOENCODING=utf-8` 再跑 Python 命令 |
| `deep-clean` 交互卡住 | Bash 环境 `input()` 可能异常 | 必须使用 `--force` / `-f` 参数跳过确认 |
| 速率限制 | GitHub API 被限 | 使用缓存（24h TTL）→ 显示提示 |
| Phase 1 超时 | 单个 scout agent 超时（60s） | 标记为 timeout，用部分结果继续 |
| Phase 2 克隆失败 | 仓库不可达 | 标记为 failed → 对比表中显示 "clone failed" |
| Phase 3 探测失败 | 探测工具不可用 | 显示 "probe unavailable" → 用户决定是否跳过 |
| Phase 5 自愈失败 | 最多 2 次自动修复 → 仍失败 | 向用户上报 |
| v3 生成失败 | Schema 验证错误 | 失败详情 + 建议修复方向 |
| v3 验证失败 | 具体验证级别失败 | 文件/行号提示 → 用户决定修复或重新生成 |
| Deep Mode 遗漏候选库 | 主 agent 主观跳过某个库 | 规则强制要求传所有候选库 |