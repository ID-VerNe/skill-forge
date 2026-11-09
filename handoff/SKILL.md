---
name: handoff
version: 2.0.0
description: 生成或读取 Handoff 交接文档。v2 起主载体是 GitHub issue(单仓库当前态,supersedes 链),local 模式保留给无远端仓。用户说"handoff"、"交接"、"交接文档"、"看前一个 agent"、"上一份 handoff" 时触发。也支持 /handoff 命令。
---

# Handoff 交接文档 Skill(v2)

规范全文在 `references/handoff-issue-spec.md`;本文件只写路由与流程,不重复规范。
改行为先改规范,再改本文件。

## 激活流程

技能激活后,先问用户:**读**(看前一个 agent 做了什么)还是**写**(生成一份新的 handoff)?

- 触发词已明确(如"生成交接文档"→ 写,"看看前一个 agent"→ 读)→ 直接走对应路由,跳过询问
- 未明确 → 问一次,不问第二次

---

## 读取路由(D13/D18/D7)

读是纯读,不写 comment、不留回执。

1. **找入口**
   - issue 模式:仓库根有 `HANDOFF.md` → 按它三步走(`gh issue list --label handoff --state open` → `gh issue view N`)
   - 无 `HANDOFF.md` 或仓里无 open handoff → 探测 `.handoffs/handoff-*.md` 最新文件(local 模式)
   - 两者都无 → 告知用户:当前项目没有 handoff 记录
2. **读正文**:按 8 节骨架总结,重点 §4 遗留 / §5 下一步 / §7 不确定项
3. **不主动执行代码,不检查 git 状态,不推进未完成项**

local 模式读到的内容,在总结开头标注:「本地模式,无 supersedes 链、无关单、读不到远端进度」。

---

## 生成路由

### 0. 前置:问模式(D17,未指明拒绝执行)

问用户:**issue 模式**(GitHub issue 作为载体)还是 **local 模式**(无远端仓,写 .handoffs/)?

- 用户已明示 → 直接用,不问第二次
- 未明示 → 停下来问,不许猜,不许自动探测后静默执行

### 1. 取数(D4/D20)

```bash
# issue 模式
python handoff/scripts/collect.py --repo OWNER/REPO --baseline <commit> --head <commit> \
  --window-start YYYY-MM-DD --today YYYY-MM-DD --repo-dir . --out draft.md

# local 模式(同上,只是写出口在 .handoffs/)
python handoff/scripts/collect.py ... --out .handoffs/handoff-YYYY-MM-DD.md
```

- `--baseline` / `--window-start` 未传且无上一份 handoff → collect.py 报硬失败,不许猜
- `--supersedes` 未传 → collect.py 自动找当前 open handoff issue(D1 链)
- 无 gh / 未登录 / 离线 → 硬失败,错误信息给出路:
  `issue 模式需要 gh,如需本地模式请用 --mode local 重跑`(D6 续)

collect.py 出四块:frontmatter + §1 口径表 + §2 交付表 + §4 遗留骨架。
**agent 不许手改这些数字**;数字只能来自 collect.py 输出。

### 2.  agent 补判断章节

只补四节,其余一律不许动:

- §3 决策与理由(本轮关键决策、取舍、被否掉的方案)
- §5 下一步(可执行顺序,每条带前置 + 验收命令)
- §6 环境与坑(环境事实 + 复现命令;口述无记录的进 §7)
- §7 无法追溯与不确定项(无复算命令的数字、无文字记录的结论、来源不明的口径;允许为空,不允许省)

§4 四桶由 collect.py 预分;agent 只做一件事:把分类错的挪对桶,并给 §4.4 补阻塞性质注释。

### 3. 硬门禁(D12/D21)

```bash
python handoff/scripts/check.py draft.md --repo OWNER/REPO \
  --baseline <commit> --head <commit> --repo-dir . --mode issue|local
```

八项全过才允许发布;任一条失败 → abort,把失败项 + 怎么修贴给用户,不许跳过、不许降级。

### 4. 发布(仅 issue 模式)

1. `gh issue create` 用 draft 正文 + 标题 `[handoff] YYYY-MM-DD～MM-DD <一句话主题>`,label `handoff`
2. 拿回 N 后:关旧单(`gh issue close <supersedes>`)+ 旧单追 comment `superseded by #N`
3. `HANDOFF.md` 死文字不动(D14/D15);若仓里还没有 HANDOFF.md,从 `references/HANDOFF.md` 拷一份并 commit

### 5. 发布(仅 local 模式)

draft 写到 `.handoffs/handoff-YYYY-MM-DD.md`;同日已有则追加序号(-2/-3)。
无 supersedes 链、无关单、无 HANDOFF.md。

---

## 写作原则(继承,适用 agent 填的章节)

1. 下一个 agent 不看代码也能操作
2. 精确到文件和变量名,不写"修改了样式"
3. 记录设计决策与理由,不只记录做了什么
4. 诚实:不把半成品标为已完成;无复算命令的数字进 §7
5. Git 节点可追溯:frontmatter 的 baseline/head 就是回滚点
6. 中文撰写,禁止 emoji
