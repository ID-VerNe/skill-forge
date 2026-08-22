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
| **ip-as-logo-skill** | `ip-as-logo-skill/` | — | 生成极简可爱 IP 角色形象（方形、圆润厚重、双色主体 + 单色背景、主角偏下角构图）。适合产品吉祥物、Logo 角色、品牌形象图。自动推断产品背景，六选批量生成，绕开常见 AI 审美陷阱 |
| **igpsport-downloader** | `igpsport-downloader/` | v1.0.0 | iGPSPORT 路书下载器。输入路书编号或关键词,自动登录 iGPSPORT → 搜索路书 → 拉取航点 → 生成 GPX 文件,可直接导入 OsmAnd/Garmin/两步路/Strava 等地图软件。支持中国站 (prod.zh) 与国际站 (prod.en),两站账号和路书编号不互通。token 持久化缓存,避免重复登录 |
| **huashu-design** | `huashu-design/` | — | 花叔 Design —— 用 HTML 做高保真原型、交互 Demo、幻灯片、动画、设计变体探索 + 设计方向顾问 + 专家评审的一体化设计能力。需求模糊时启动设计方向顾问模式，推荐差异化风格并生成视觉 Demo [`🔗`](https://github.com/alchaincyf/huashu-design) |
| **resume-tailoring-skill** | `resume-tailoring-skill/` | — | AI 驱动简历定制工具。深度研究职位与公司文化、通过对话发现未文档化的经验、置信度评分匹配、多格式输出（MD/DOCX/PDF），简历库自学习 |
| **OfficeCLI** | `OfficeCLI/` | — | 通过 CLI 创建、分析、审阅和修改 Office 文档（.docx/.xlsx/.pptx）。单二进制、无依赖、无需 Office 安装。支持 L1 读取 → L2 DOM 编辑 → L3 原始 XML 三层操作策略 |
| **interfaces-skills** | `interfaces-skills/` | — | 界面设计技能合集（来自 [interfaces.dev](https://interfaces.dev) ）。包含 better-interface（跨学科统一评审）、better-ui（设计工程细节）、better-typography（排版）、better-colors（色彩）、better-accessibility（无障碍）、better-layout（布局）、better-writing（UX 文案）七个子 skill |
| **cf-notifier** | `cf-notifier/` | — | Cloudflare Workers 推送通知服务。通过 Wrangler 部署到 Cloudflare 边缘节点，支持多渠道通知推送 |

---

## 安装方式

将所需 skill 的目录链接到 `~/.claude/skills/` 下即可（推荐 Windows Junction 链接，避免重复拷贝）：

```bash
# Windows：用 junction 链接（管理员终端）
mklink /J %USERPROFILE%\.claude\skills\skill-name skill-forge\skill-name

# macOS/Linux：用符号链接
ln -s $(pwd)/skill-name ~/.claude/skills/skill-name
```

> **提示**：`huashu-design` 原为 git submodule，现已从仓库中移除（被 `.gitignore` 排除，通过 junction 链接到 `~/.claude/skills/` 使用）。如需独立更新，在其目录内执行 `git pull` 即可。

---

## 使用指南

| 文档 | 说明 |
|------|------|
| `guides/fix-windows-utf8-encoding.md` | Windows 中文乱码修复 —— 配置 Claude Code 子进程 UTF-8 编码的三层方案 |