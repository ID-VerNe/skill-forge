---
name: handoff-issue-spec
description: handoff issue 规范全文(D1-D22 决策 + 三条补充),collect.py/check.py/SKILL.md 的唯一事实源
---

# Handoff Issue 规范 v1

本规范是 handoff skill 在 GitHub issue 上做跨会话进度追踪的唯一事实源。
collect.py / check.py / SKILL.md 的行为都由本文档推导;改行为先改本文档。

## 0. 核心原则

1. **issue 是快照载体,不是事实源**。所有可复算的数字由 collect.py 从 git/gh API 取,
   issue 正文只放判断、决策、风险和承认不知道的东西。
2. **单事实源**。一个项目一次只有一种模式生效(issue 或 local),不允许双写。
3. **机器读优先**。读者是 agent:入口是 HANDOFF.md 死文字 + frontmatter,
   正文是完整 markdown 但每节标题固定,check.py 可断言。
4. **诚实记录不知道**。§7 强制存在,允许为空,不允许省略;无复算命令的数字只能进 §7。

## 1. 生命周期(D1/D2/D5/D8)

- 单仓库当前态:一个仓库最多一份 open handoff issue。
- 每次 handoff 开新 issue,frontmatter `supersedes` 指上一份;创建成功后自动关旧单
  并在旧单追一行 comment `superseded by #N`。
- label 只有一个 `handoff`(wiredraw 已建);生命周期靠 issue state 表达,不加第二个 label。
- 触发权在用户:纯手动,collect.py 只报体量数字,不自动建议、不自动触发。
- open handoff 恒为 1 是 check.py 的硬闸(第 7 项);不为 1 说明关单失败,读者入口已破。

## 2. 标题与入口(D3/D14/D15)

- 标题:`[handoff] YYYY-MM-DD～MM-DD <一句话主题>`。不带规模数字,数字进 §1。
- 仓库根 `HANDOFF.md` 是静态死文字,只放读者三步:
  1. `gh issue list --repo <OWNER/REPO> --label handoff --state open --json number`
  2. `gh issue view <N> --repo <OWNER/REPO>`
  3. 按正文 8 节骨架读,重点 §4 遗留 / §5 下一步 / §7 不确定项
- HANDOFF.md 不放 issue 号、不放 commit、不放任何会过期的字段;handoff 流程永不改它。
- check.py 第 6 项校验 HANDOFF.md 相对 git HEAD 无 diff;第 7 项校验 open handoff 恒为 1。

## 3. 文档形态(D13/D19)

- 正文是完整 markdown,8 节骨架固定(标题文字一字不差,check.py 第 5 项断言):
  1. 数据口径(脚本生成,每行带复算命令)
  2. 本窗口交付(行 = merged PR,验证状态从 linked issue label 取)
  3. 决策与理由(agent 写)
  4. 遗留与阻塞(脚本预分四桶,agent 修正)
  5. 下一步(agent 写,带前置 + 验收命令)
  6. 环境与坑(agent 写,环境事实 + 复现命令)
  7. 无法追溯与不确定项(agent 写,允许为空不允许省)
- frontmatter 固定字段:schema / repo / window.from / window.to / baseline_commit /
  head_commit / supersedes。window.from 是日期不是 commit。
- local 模式与 issue 模式共用同一骨架,只是写出口不同(local 写 .handoffs/ 最新文件)。

## 4. 取数口径(D4/D9/D10/D11/D20)

- 窗口 = 上一份 frontmatter.baseline_commit..HEAD;无上一份时用户必须给 --baseline 与
  --window-start,脚本拒绝猜。
- 合并提交用 `git log --merges` 全口径(含本地回合 origin/main),不用 compare API 的
  `Merge pull request` 计数(会少算本地回合)。
- 合并 PR / 关闭 issue 按窗口起点日期过滤 mergedAt / closedAt。
- open issue 排除 label `handoff` 自身。
- §2 行 = merged PR;linked issue 从 PR body 的 `Closes|Refs|Fixes #N` 解析,只扫关键词后,
  不扫标题、不扫正文叙述;去重。
- §4 四桶(label 优先,窗口内 merged PR 次之):
  - verify-pending: open + needs-live-verify label(等真机回签,PR 在不在窗口内都进)
  - merged-unclosed: open + 无 needs-live-verify + 窗口内有 merged PR linked
  - needs-repro: open + needs-repro label + 无窗口内 merged PR
  - code-needed: open + 其余(agent 细分要代码/要硬件/要维护者/理论风险)

## 5. 模式与失败语义(D16/D17/D18/D6 续)

- 写路由必须用户明示 `--mode issue` 或 `--mode local`;未指明拒绝执行。
- issue 模式无 gh / 未登录 / 离线 → 硬失败,错误信息给出路:
  `issue 模式需要 gh,如需本地模式请用 --mode local 重跑`。不静默降级。
- 读路由自动探测:有 open handoff issue 走 issue 模式三步;无 open 且有 .handoffs/ 最新
  文件走 local 模式,并标注「本地模式,无 supersedes 链、无关单、读不到远端进度」。
- 读是纯读,不写 comment、不留回执(D7)。

## 6. 发布前硬门禁(D12/D21 + 三条补充)

check.py 八项,全过才允许创建 issue,任一条失败 abort 并打印具体哪条 + 怎么修:

1. frontmatter 必填字段齐且格式对(schema 值 = handoff/v1,repo/baseline/head 与 CLI 参数一致)
2. baseline_commit 是 head_commit 的祖先
3. §1 口径表每行的复算命令在本机重跑结果与表中数字一致(能本地跑的全跑;需特殊环境的 skip)
4. 正文 #N 引用全部存在于该仓(issue 或 PR 均可)
5. 8 节骨架标题文字齐全(§7 允许空但不许省)
6. issue 模式下 HANDOFF.md 相对 git HEAD 无 diff
7. issue 模式下 open handoff issue 恒为 1
8. §4 表行首 #N 必须是 issue 号(PR 号不得误入;GitHub 的 issues API 对 PR 也返回 200,
   要再查 pulls/N 才分得清)

## 7. 写作原则(继承旧版,适用 agent 填写的 §3/§5/§6/§7)

- 下一个 agent 不看代码也能操作;精确到文件和变量名;记录设计决策与理由。
- 诚实:不把半成品标为已完成;无复算命令的数字进 §7;口述无记录的结论进 §7。
- 中文撰写,禁止 emoji。
