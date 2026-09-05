# Skill Forge 🔨

> 个人自用 Claude Code Skills 合集

## 包含的 Skills

| Skill | 目录 | 版本 | 说明 |
|-------|------|------|------|
| **commit-message-writing** | `commit-message-writing/` | v1.1.0 | 自动写 commit message、执行 git commit & push 的 skill。遵循 Conventional Commits 格式，自动扫描变更文件并逐个追踪，强制设置作者身份 |
| **doc-weaver** | `doc-weaver/` | **v2.1.0** | 项目文档编织器。基于 lat.md 工具链，自动为项目生成覆盖所有模块的知识图谱文档到 `docs/` 目录（Tier 1 入口 + Tier 2 模块知识 + Tier 3 结构化数据），并用 `lat check` 做验证。Orchestrator + 每 Phase 独立子 agent 架构。适用于 AI-first 的多项目管理场景——文档主要供 AI agent 阅读，而非人类。需安装 `lat.md` CLI 并配置 `lat.md/` → `docs/` junction |
| **gpt-image-2** | `gpt-image-2/` | v1.0.0 | GPT Image 2 Prompt 编写 Skill。渐进式加载架构（SKILL.md 主路由 + references 按需加载），覆盖 12 类任务类型（Text-to-Image / Edit / Multi-Image / Text-in-Image / Photorealism / Product / UI / Infographic / Logo / Character / Style Transfer / Drawing→Photoreal），将模糊审美词转译为具体视觉事实 |
| **multi-lens-research** | `multi-lens-research/` | **v3.0.0** | 基于斯坦福 STORM 方法的多视角深度研究 Skill。v3 多团队架构：11 个专业团队（Code Review / Paper Review / Direction Judge / Investing / 等）+ 自定义团队，通过场景关键词自动匹配，agent prompt 按需渐进加载。支持自动模式（用户说"自动完成全流程"等即跳过 Phase 间确认，一次跑完 4 步流程） |
| **glue-engineer** | `glue-engineer/` | **v4.0.0** | 多语言胶水代码生成引擎。双模架构：**Search Mode**（CLI 自动探索候选库 → 完整方案规划）→ 用户确认 → **Deep Mode**（并行子 agent 架构分析 → `deep-compare` → `deep-summarize` → reuse-map + 许可证检查 → 集成路线规划）。强制使用 CLI 工具链，输出统一归入 `.glue/search/` 和 `.glue/deep/` |
| **license-add** | `license-add/` | v1.0.0 | 把常用开源许可证（MIT/Apache-2.0/GPL-3.0/LGPL-3.0/MPL-2.0/BSD-2-Clause/BSD-3-Clause/CC0-1.0）从内置 `references/` 拷贝到目标项目根目录的 LICENSE，并用脚本自动替换 `[year] [fullname]` 等占位符。官方标准文本来自 GitHub API licenses 接口，不依赖网络。支持自定义目标目录/文件名/年份/版权持有者，`--dry-run` 预览 |
| **igpsport-downloader** | `igpsport-downloader/` | v1.0.0 | iGPSPORT 路书下载器。输入路书编号或关键词,自动登录 iGPSPORT → 搜索路书 → 拉取航点 → 生成 GPX 文件,可直接导入 OsmAnd/Garmin/两步路/Strava 等地图软件。支持中国站 (prod.zh) 与国际站 (prod.en),两站账号和路书编号不互通。token 持久化缓存,避免重复登录 |
| **cf-notifier** | `cf-notifier/` | — | Cloudflare Workers 推送通知服务。通过 Wrangler 部署到 Cloudflare 边缘节点，支持多渠道通知推送 |
| **subtitle-polish** | `subtitle-polish/` | v1.0.0 | 字幕精校 Skill。输入 ASS 双语成品 + SRT 源，走 审计 → 人确认 → 修复 全流程。多 agent 并行审计（按 srt 块自适应切片 + overlap）、adversarial 验证轮去幻觉、脚本执行修复（replace/delete/swap + dry-run/accept/rollback）。按 srt_id+track 定位，自动还原 `{\be3}` 等特效标签；标点预检对照 translate_principle pipeline 规则规范化中文行 |

---

## 安装方式

将所需 skill 的目录链接到 `~/.claude/skills/` 下即可（推荐 Windows Junction 链接，避免重复拷贝）：

```bash
# Windows：用 junction 链接（管理员终端）
mklink /J %USERPROFILE%\.claude\skills\skill-name skill-forge\skill-name

# macOS/Linux：用符号链接
ln -s $(pwd)/skill-name ~/.claude/skills/skill-name
```


---

## 使用指南

| 文档 | 说明 |
|------|------|
| `guides/fix-windows-utf8-encoding.md` | Windows 中文乱码修复 —— 配置 Claude Code 子进程 UTF-8 编码的三层方案 |