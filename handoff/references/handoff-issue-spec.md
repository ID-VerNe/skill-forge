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
3. **机器读优先**。读者是 agent:直接查询 handoff issue,可选的 HANDOFF.md 提供静态入口;
   frontmatter 和固定章节便于机器读取,check.py 可断言。
4. **诚实记录不知道**。§7 强制存在,允许为空,不允许省略;无复算命令的数字只能进 §7。

## 1. 生命周期(D1/D2/D5/D8)

- 稳定状态:一个仓库最多一份 open handoff issue。发布过程中创建新单和关闭旧单之间允许短暂有两份。
- 发布前按草案 frontmatter `supersedes` 校验:首份为 null 时必须没有 open handoff;
  后续必须恰有一份 open handoff,且号码等于 `supersedes`。多份、身份不符或查询失败均中止。
- 每次 handoff 开新 issue;创建后只关闭 `supersedes` 指定的旧单,并在旧单追 comment
  `superseded by #N`。首份没有旧单,跳过关单和追评。发布后验证新单是唯一 open handoff。
- 若创建、关单、追评或发布后验证失败,保留已完成的操作并报告实际状态;恢复前重新查询,
  核对新旧 issue 身份,只补做尚未完成的步骤,不盲目重建或关闭其他单。
- 发布前检查不是原子锁;多个发布者必须协调。创建后只允许预期的新单和指定旧单同时 open;
  发现竞争、额外或身份不符的 open handoff 则停止并报告,不擅自关闭其他发布者的 issue。
- label 只有一个 `handoff`;缺失时发布前创建,生命周期靠 issue state 表达,不加第二个 label。
- 触发权在用户:纯手动,collect.py 只报体量数字,不自动建议、不自动触发。

## 2. 标题与入口(D3/D14/D15)

- 标题:`[handoff] YYYY-MM-DD～MM-DD <一句话主题>`。不带规模数字,数字进 §1。
- 读者不依赖入口文件,直接查 `gh issue list --repo <OWNER/REPO> --label handoff --state open --json number`,
  唯一结果用 `gh issue view <N> --repo <OWNER/REPO>` 读取,再按正文骨架读;多份则报告异常。
- 仓库根 `HANDOFF.md` 是可选的静态入口,不放 issue 号、commit 或其他会过期的字段。
  初始化入口是单独的、须用户授权的文件变更或 PR;handoff 发布流程不自动创建或提交它。
- check.py 第 6 项校验已有 HANDOFF.md 无未提交改动;文件缺失不妨碍读取或发布。

## 3. 文档形态(D13/D19)

- 正文是完整 markdown,8 节骨架固定(标题文字一字不差,check.py 第 5 项断言):
  1. 数据口径(脚本生成,每行带复算命令)
  2. 本窗口交付(行 = merged PR,验证状态从 linked issue label 取)
  3. 决策与理由(agent 写)
  4. 遗留与阻塞(脚本预分四桶,agent 修正)
  5. 下一步(agent 写,带前置 + 验收命令)
  6. 环境与坑(agent 写,环境事实 + 复现命令)
  7. 无法追溯与不确定项(agent 写,允许为空不允许省)
- 正文不放 H1:标题信息已由 frontmatter 承载,H1 属禁止项(check.py 断言无 `^# `)。
- agent 读取入口:`python handoff/scripts/collect.py --read <file>` 输出结构化 JSON
  (frontmatter + §1 事实表 + §2 交付行 + §4 四桶计数 + §3/§5/§6/§7 是否已填),
  只解析不取数不联网;读路由不再人工逐节摘。
- frontmatter 固定字段:schema / repo / window.from / window.to / baseline_commit /
  head_commit / supersedes。window.from 是日期不是 commit。
- local 模式与 issue 模式共用同一骨架,只是写出口不同(local 写 .handoffs/ 最新文件)。

## 4. 取数口径(D4/D9/D10/D11/D20)

- 首份交接必须由用户提供 `--baseline` 与 `--window-start`,脚本拒绝猜。后续默认用上一份
  `head_commit` 作 baseline,该 commit 的 UTC 日期作窗口起点;二者均可显式覆盖。
  baseline 必须是本次 head 的祖先;采集时将 baseline/head 解析为实际 commit SHA 写入 frontmatter。
  本次 head 是采集时的快照,不要求此后恒等于 HEAD;检查时使用草案中的 SHA。
- §1 不执行目标仓库的项目专属脚本,也不统计其门禁或自检项目数;其余取数失败必须明确报错,
  不得伪装成不适用。
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
- 两种写模式的采集均依赖 gh、认证及远端数据;local 只改变写出口且跳过检查 6/7,
  不是离线方案。缺 gh、认证或远端查询失败时硬失败,不静默降级或声称 local 可离线使用。
- 读路由直接查询 open handoff,不论 HANDOFF.md 是否存在;恰有一份则读 issue,
  确认无 open 且有 .handoffs/ 最新文件则读 local 并标注
  「本地模式,发布不维护 issue 交接链、不关单;文件只反映采集时快照」。查询失败不等于无记录,
  应报告失败,不得静默转 local。
- 读是纯读,不写 comment、不留回执(D7)。

## 6. 发布前硬门禁(D12/D21 + 三条补充)

check.py 九项,全过才允许创建 issue,任一条失败 abort 并打印具体哪条 + 怎么修:

0. 正文无 H1 行(标题信息由 frontmatter 承载,H1 属禁止项)
1. frontmatter 必填字段齐且格式对(schema 值 = handoff/v1,repo/baseline/head 与 CLI 参数一致)
2. baseline_commit 是 head_commit 的祖先
3. §1 口径表每行的复算命令在本机重跑结果与表中数字一致(能本地跑的全跑;需特殊环境的 skip)
   §1 复算命令不变量:值列 = 表中数字,命令列 = 可本机重跑的 gh/git 命令;命令里不得出现仓名字面量(check_sensitive private-repo 规则会红),用 --repo 参数值代替
   已发布快照对 check 3 会红属预期,不加降级:issue 之间不是串行推进,而是按需选择性推进,
   窗口外的合并/开闭会让复算值偏离快照值;读方按快照读,不要求它等于现在
4. 正文 #N 引用全部存在于该仓(issue 或 PR 均可)
5. 8 节骨架标题文字齐全(§7 允许空但不许省)
6. issue 模式下已有 HANDOFF.md 无未提交改动;不存在时通过
7. issue 模式发布前:首份 `supersedes: null` 时 open handoff 数为 0;后续恰有一份,
   且 issue 号等于 `supersedes`;查询失败或身份不符均失败。发布后另行检查新 issue
   为唯一 open handoff;local 模式跳过 6/7
8. §4 表行首 #N 必须是 issue 号(PR 号不得误入;GitHub 的 issues API 对 PR 也返回 200,
   要再查 pulls/N 才分得清)

## 7. 写作原则(继承旧版,适用 agent 填写的 §3/§5/§6/§7)

- 下一个 agent 不看代码也能操作;精确到文件和变量名;记录设计决策与理由。
- 诚实:不把半成品标为已完成;无复算命令的数字进 §7;口述无记录的结论进 §7。
- 中文撰写,禁止 emoji。
