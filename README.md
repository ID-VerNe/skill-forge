# Skill Forge 🔨

> 个人自用 Claude Code Skills 合集

## 包含的 Skills

| Skill | 目录 | 版本 | 说明 |
|-------|------|------|------|
| **commit-message-writing** | `commit-message-writing/` | v1.1.0 | 自动写 commit message、执行 git commit & push 的 skill。遵循 Conventional Commits 格式，自动扫描变更文件并逐个追踪，强制设置作者身份 |
| **gpt-image-2** | `gpt-image-2/` | v1.0.0 | GPT Image 2 Prompt 编写 Skill。渐进式加载架构（SKILL.md 主路由 + references 按需加载），覆盖 12 类任务类型（Text-to-Image / Edit / Multi-Image / Text-in-Image / Photorealism / Product / UI / Infographic / Logo / Character / Style Transfer / Drawing→Photoreal），将模糊审美词转译为具体视觉事实 |
| **multi-lens-research** | `multi-lens-research/` | v2.2.0 | 基于斯坦福 STORM 方法的多视角深度研究 Skill |
| **glue-engineer** | `glue-engineer/` | **v4.0.0** | 多语言胶水代码生成引擎 + Deep Mode。跨语言搜索、能力本体匹配、自动桥接代码生成；v4 新增深度分析管道：`deep-init` → 并行子 agent 架构分析 → `deep-compare` → `deep-summarize` → reuse-map + 许可证检查 → 集成路线规划 |

---

## 安装方式

将所需 skill 的目录链接或复制到 `~/.claude/skills/` 下即可。

```bash
# 示例：安装 glue-engineer（含 4 个子 agent 定义）
ln -s $(pwd)/glue-engineer ~/.claude/skills/glue-engineer
cp glue-engineer/agents/*.md ~/.claude/agents/

# 查看可用的子 agent
/agents
```
