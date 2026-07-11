# Skill Forge 🔨

> 个人自用 Claude Code Skills 合集

## 包含的 Skills

| Skill | 目录 | 版本 | 说明 |
|-------|------|------|------|
| **commit-message-writing** | `commit-message-writing/` | v1.1.0 | 自动写 commit message、执行 git commit & push 的 skill。遵循 Conventional Commits 格式，自动扫描变更文件并逐个追踪，强制设置作者身份 |
| **gpt-image-2** | `gpt-image-2/` | v1.0.0 | GPT Image 2 Prompt 编写 Skill。渐进式加载架构（SKILL.md 主路由 + references 按需加载），覆盖 12 类任务类型（Text-to-Image / Edit / Multi-Image / Text-in-Image / Photorealism / Product / UI / Infographic / Logo / Character / Style Transfer / Drawing→Photoreal），将模糊审美词转译为具体视觉事实 |
| **multi-lens-research** | `multi-lens-research/` | **v3.0.0** | 基于斯坦福 STORM 方法的多视角深度研究 Skill。v3 多团队架构：11 个专业团队（Code Review / Paper Review / Direction Judge / Investing / 等）+ 自定义团队，通过场景关键词自动匹配，agent prompt 按需渐进加载 |
| **glue-engineer** | `glue-engineer/` | **v4.0.0** | 多语言胶水代码生成引擎。双模架构：**Search Mode**（CLI 自动探索候选库 → 完整方案规划）→ 用户确认 → **Deep Mode**（并行子 agent 架构分析 → `deep-compare` → `deep-summarize` → reuse-map + 许可证检查 → 集成路线规划）。强制使用 CLI 工具链，输出统一归入 `.glue/search/` 和 `.glue/deep/` |
| **huashu-design** | `huashu-design/` | — | 花叔 Design —— 用 HTML 做高保真原型、交互 Demo、幻灯片、动画、设计变体探索 + 设计方向顾问 + 专家评审的一体化设计能力。需求模糊时启动设计方向顾问模式，推荐差异化风格并生成视觉 Demo [`🔗`](https://github.com/alchaincyf/huashu-design) |

---

## 安装方式

将所需 skill 的目录链接到 `~/.claude/skills/` 下即可（推荐 Windows Junction 链接，避免重复拷贝）：

```bash
# Windows：用 junction 链接（管理员终端）
mklink /J %USERPROFILE%\.claude\skills\glue-engineer skill-forge\glue-engineer

# macOS/Linux：用符号链接
ln -s $(pwd)/glue-engineer ~/.claude/skills/glue-engineer
```

> **提示**：`huashu-design` 是 git submodule，克隆本仓库后需执行 `git submodule update --init` 拉取其内容。

---

## 使用指南

| 文档 | 说明 |
|------|------|
| `guides/fix-windows-utf8-encoding.md` | Windows 中文乱码修复 —— 配置 Claude Code 子进程 UTF-8 编码的三层方案 |
