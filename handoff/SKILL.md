---
name: handoff
version: 2.0.1
description: 生成或读取 Handoff 交接文档。v2 主载体是 GitHub issue(单仓库当前态,supersedes 链),local 模式写本地文件但采集仍依赖 gh 和远端。用户说"handoff"、"交接"、"交接文档"、"看前一个 agent"、"上一份 handoff" 时触发。也支持 /handoff 命令。
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

1. **找入口**:不管 `HANDOFF.md` 是否存在,先查询
   `gh issue list --repo OWNER/REPO --label handoff --state open --json number`。
   - 恰有一份 → `gh issue view N --repo OWNER/REPO`,取得正文
   - 确认没有 open handoff → 探测 `.handoffs/handoff-*.md` 最新文件;也没有则告知用户没有记录
   - 多份 → 报告异常并停止,不猜哪份是当前态;查询失败 → 报告错误,不当成没有记录或静默转 local
2. **读正文**:跑 `python handoff/scripts/collect.py --read <draft-or-issue-body.md>` 取结构化概要(frontmatter + §1 事实表 + §2 交付行 + §4 四桶计数 + §3/§5/§6/§7 是否已填),再按 8 节骨架读,重点 §4 遗留 / §5 下一步 / §7 不确定项
3. **不主动执行代码,不检查 git 状态,不推进未完成项**

读到的正文含 H1 → 该文件不是 handoff v2 产物(check.py 第 0 项会拦),按坏格式上报。
local 模式读到的内容,在总结开头标注:「本地模式,发布不维护 issue 交接链、不关单;文件只反映采集时快照」。

---

## 生成路由

### 0. 前置:问模式(D17,未指明拒绝执行)

问用户:**issue 模式**(GitHub issue 作为载体)还是 **local 模式**(写 .handoffs/)?
两种模式的采集都需要 gh、认证和远端;local 不是离线模式,只跳过检查 6/7。

- 用户已明示 → 直接用,不问第二次
- 未明示 → 停下来问,不许猜,不许自动探测后静默执行

### 1. 取数(D4/D20)

先查询当前 open handoff。首份须向用户确认基线 commit 和窗口起始日期;后续默认使用上一份
`head_commit` 作基线,其 UTC 日期作起点,允许用户明确覆盖。前驱损坏、多份 open 或指定的
`--supersedes` 不匹配实际旧单时停止,不得猜测。

```bash
# 首份:基线和日期由用户提供
python handoff/scripts/collect.py --repo OWNER/REPO --baseline <commit> \
  --window-start YYYY-MM-DD --repo-dir . --out draft.md

# 后续:默认沿用上一份 head 及其 UTC 日期
python handoff/scripts/collect.py --repo OWNER/REPO --repo-dir . --out draft.md
```

- local 模式使用相同采集命令,将 `--out` 指向 `.handoffs/handoff-YYYY-MM-DD.md`。
- `--supersedes` 未传时自动查当前 open handoff;显式指定时必须与其一致。
- 可用 `--head` 指定 head,默认采集时的 HEAD;baseline/head 均解析为实际 commit SHA 写入
  frontmatter。head 是采集快照,不是此后恒等于 HEAD。
- gh、认证、远端查询或 git 失败 → 报告错误并停止,不得建议切换 local 作为离线替代。

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

使用草案 frontmatter 中的 baseline/head 作为参数,不要用后来变化的 HEAD 替代快照。
参数按解析后的 commit 比对,短 SHA 与全 SHA 等价,但必须指向同一 commit。
九项全过才允许发布;首份要求零份 open handoff,后续要求恰有指定 `supersedes` 旧单。
任一条失败 → 中止,把失败项 + 怎么修贴给用户,不许跳过、不许降级。

### 4. 发布(仅 issue 模式)

1. 确认 `handoff` label 存在;若缺失,用 `gh label create handoff --repo OWNER/REPO` 创建。
   失败则停止。发布前重新运行硬门禁,核对草案 `supersedes` 和当前 open issue。
2. 用 draft 正文、标题 `[handoff] YYYY-MM-DD～MM-DD <一句话主题>` 和 `handoff` label
   执行 `gh issue create --repo OWNER/REPO`,记录返回的新 issue 号 N。
3. 若 `supersedes` 非 null,重新核对新旧单身份和 open 状态,只关闭该旧单
   (`gh issue close <supersedes> --repo OWNER/REPO`),然后在旧单追评 `superseded by #N`。
   首份跳过关单和追评。
4. 发布后运行 `python handoff/scripts/check.py --repo OWNER/REPO --published N`,
   确认 N 是唯一 open handoff。检查失败则报告实际状态,不宣布成功。
5. `HANDOFF.md` 是可选静态入口,即使缺失也能读取;如需初始化,另行获得用户授权后再建文件或 PR,
   不作为发布的一部分自动创建或 commit。新建或改动该文件会占住第 6 项,必须另有提交记录
   (单独 commit 或独立 PR)后才会通过;不要在发布前留下未提交的 `HANDOFF.md`。

发布前检查不是锁,多个发布者需事先协调。创建后只允许预期的新单和指定旧单同时 open;
若发现竞争、额外或身份不符的 open 单,停止并报告,不擅自关闭其他单。
任何一步失败或结果不确定时,先查询远端并核对新旧 issue、状态和评论,报告已完成步骤:

- 创建失败或响应丢失:先确认是否已创建本次新单;无法唯一确认时停止,不要盲目重建。
- 关单失败:确认新单和指定旧单后,只补关仍 open 的指定旧单;存在竞争则停止。
- 追评失败:检查旧单是否已有对应评论,缺失时只补该评论,不要重复创建或关单。
- 发布后检查失败或查询失败:保留现场,查明 open 单的身份和数量后再恢复检查;若有竞争则交由用户协调。

### 5. 发布(仅 local 模式)

draft 写到 `.handoffs/handoff-YYYY-MM-DD.md`;同日已有则追加序号(-2/-3)。
local 发布不维护 issue 交接链、不关单,不创建 HANDOFF.md;采集仍可能从当前 open issue 取前驱。

---

## 写作原则(继承,适用 agent 填的章节)

1. 下一个 agent 不看代码也能操作
2. 精确到文件和变量名,不写"修改了样式"
3. 记录设计决策与理由,不只记录做了什么
4. 诚实:不把半成品标为已完成;无复算命令的数字进 §7
5. Git 节点可追溯:frontmatter 的 baseline/head 就是回滚点
6. 中文撰写,禁止 emoji
