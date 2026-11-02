# prompt 构造约束（防答案注入）

审计与验证子 agent 的 prompt 构造必须遵守本规则。SKILL.md 阶段 3/4 引用本文件。

## 问题

第三轮实测（会话 8ea54874，EP02+EP05）暴露：主 agent 把"预扫线索 + 正确答案"塞进 audit/verify 子 agent 的 prompt，导致审计与 adversarial 验证都失去独立性——审计 agent 报的几乎全是主 agent 预扫点，verify agent 几乎全确认，没有任何反驳成功的硬伤被独立挖出。

## 规则

### 1. audit prompt 的"项目背景"只放中性领域事实，不放翻译判断结论

**中性领域事实**（可放）：
- 节目类型、主角身份、机械型号的事实性描述
- 例："Class 37 是柴油-电力传动机车（English Electric Type 3，1960 年代投产），不是蒸汽机车。英文里只说 locomotive 时指机车。"
- 例："节目是英国铁路修复真人秀，主角修的是一台 Class 37 型柴油机车。"

**翻译判断结论**（不可放）：
- 主 agent 已经判断"该译 X 不该译 Y"的结论
- 反例（**禁止**塞进 audit prompt）：
  - "Deluxe（Deluxe Media）是专业字幕公司，非粉丝'字幕组'"——这是对 e02#720 的判断结论
  - "Reservoir Bourgeois 是把 Francis 的姓套进 Reservoir 的谐音梗，应译'布儒瓦'"——这是对 e05#309 的判断结论
  - "TMD = Track Maintenance Depot 机务段（铁路术语，非脏话）"——这是对 e05#349 的判断结论
  - "emus 是铁路俚语 = EMU 电力动车组，不是鸟鸸鹋"——这是对 e05#588 的判断结论
  - "drill/drill bit = 钻头/手电钻（机械维修场景，不是播种机 seed drill）"——这是对 e02#423/427 的判断结论
- 这些是审计 agent 该自己判断的，主 agent 预先告诉它 = 审计失去独立性。

**判定标准**：项目背景里的一句话，如果它直接指向某个 srt_id 的"问题是什么/该怎么译"，就是判断结论，不能放。如果它是关于节目/机械/术语的通用事实，与具体某条 srt_id 的判断无关，可以放。

### 2. 删掉 audit prompt 的"特别留意（预扫线索）"段

主 agent 在子 agent 跑期间用 grep/正则独立预扫可疑点（专名不一致、异常字符、ASR 错词模式），这是允许的（SKILL.md 阶段 3）。但预扫发现**只供主 agent 合并时参考**，不喂给审计 agent。

**禁止**：在 audit prompt 里加"特别留意（主 agent 预扫线索，你独立核验）：srt_id 309 / 156 / 719 ..."这种段——即使附一句"不一定全报"，审计 agent 仍会被引导到这些点，少看其他块。

**允许**：主 agent 预扫后，发现列表自己留着；子 agent 返回后，主 agent 把两边发现合并去重（synthesize 阶段）。

### 3. verify prompt 无"项目背景"段

`prompts/verify.tmpl` 本身**没有**项目背景占位符，只有 `{findings}`。主 agent 不得在模板之外私加项目背景段。

**原因**：adversarial 验证的设计是"默认驳回，只有找不到反驳理由才确认"。把判断结论塞进 verify prompt = 让 verify agent 按主 agent 判断走，adversarial 名存实亡。第三轮实测 E02 8/8 确认、E05 15/16 确认（唯一驳回的是用户预先标过"低严重度"的 13→21 项），就是 verify prompt 塞了答案的后果。

**如确需领域事实**（罕见）：只给中性事实（"这集主角修的是 Class 37 柴油机车"），不给翻译结论（"locomotive 应译'机车'"）。领域事实应尽量从 findings 里的上下文自推断，不外喂。

### 4. 历史台账：可贴"改了什么"，不可贴"为什么改"

多轮疗程（`rounds-spec.md`）会把历史台账注入审计 prompt（`{ledger}` 占位符）。
这条线**不在**「贴不贴」，而在「贴到哪一层」：

| 台账字段 | 贴不贴 | 理由 |
|---|---|---|
| 第几轮 / srt_id / old_text → new_text | **贴** | 这是盘面事实，agent 打开切片就能看到。不贴等于要求它把「这行刚被改过」当成没发生 |
| batch_id / category / verdict | **贴** | 同上，是账不判断 |
| `reason`（上一轮写的判断理由） | **不贴** | 这是判断结论。贴了 agent 会顺着上轮的理由往下推，`bag` 那次连推三轮就是这么发生的 |
| 上一轮的「建议译文」 | **不贴** | 同上 |

具体做法：`regression_check.py` 加 `--no-reason`，输出的台账**直接就没有理由列**：

```bash
python <skill>/scripts/regression_check.py --ledger --conflicts --no-reason
```

不用手工删列——手删迟早会漏一次，漏的那次就把结论灌进去了。`--no-reason` 版台账只留
`轮次 | srt_id | 改动前 | 改动后`，且把提示语从「说明当时那条理由错在哪」换成
「说明这条改动错在哪」，因为后者不再有「当时理由」可引用。

要看理由时用**不带** `--no-reason` 的输出（人工复看用），那份不要贴进 prompt。

配套的一句话约束写进 prompt（`audit.tmpl` 已内置）：

> 若你判这行是错的，必须说明**上一轮那条改动的理由错在哪**——不是「上一轮改得不好」，
> 是「上一轮把 X 当成 Y，而 X 实际是 Z」。

要求它自己给出 rebuttal，比禁止它碰历史更有效：禁止只会让它绕过，要求 rebuttal 会让它真的去看上一轮改了什么。

**边界**：`cross_check` 的「动到了历史刚定下的内容」表**可以**贴（那是「第 X 轮定下的内容」这个事实），但同样不贴当轮的 reason。详见 `auto-flow.md` 11c。

## 正例（audit prompt 项目背景）

```
## 项目背景

节目 **Francis Bourgeois and Chris Harris: We Saved A Train**（2026，Amazon）。英国铁路修复真人秀。主角 Francis Bourgeois（TikTok 火车网红）+ Chris Harris（汽车媒体人）联手抢救一台 Class 37 型柴油-电力传动机车（车号 37025 与 37403），修复后送回遗产铁路运营。

关键事实：
- Class 37 是柴油-电力传动机车（English Electric Type 3，1960 年代投产）。
- 37025 / 37403 是 Class 37 的车号。同一台机车在不同语境用不同车号指代。
- 主角姓氏 Bourgeois（法语姓）。

铁路/机械术语（中性事实，供参考）：
- bogie/bogies = 转向架；wheelset = 轮对；heritage railway = 遗产铁路；main air reservoir = 主风缸/储气罐；throttle lever = 油门手柄；timing chain = 正时链条；railhead = 钢轨/轨头。
```

注意：没有"Deluxe 是字幕公司""Reservoir 是谐音梗应译布儒瓦""TMD 是机务段非脏话"这些判断结论。

## 反例（第三轮实测的 audit prompt，禁止）

```
## 项目背景（错误示范）

... drill/drill bit = 钻头/手电钻（机械维修场景，**不是**播种机 seed drill）；
railhead = 钢轨/轨头；expansionary contraction = 热胀冷缩。
- East Lancs Railway = 东兰开夏铁路（**铁路**不是赛车场）；
  trackside pub = 铁路沿线/铁道旁的酒吧（**不是**赛道旁）；
- 主角姓氏 Bourgeois 在成品里统一作"布儒瓦"。注意 "Reservoir Bourgeois"
  是把 Francis 的姓套进 "Reservoir"（储气罐）的谐音梗，**姓的译法应与
  全名一致用"布儒瓦"**，不要译成"布尔乔亚"（那是 bourgeoisie 的社会学词）。

## 特别留意（主 agent 预扫线索，你独立核验，不一定全报）：
srt_id 309 / 156 / 719 / 720 / 726 / 728 ...
```

错在哪：
- "drill = 钻头不是播种机"是对 e02#423/427 的判断结论
- "Reservoir Bourgeois 应译布儒瓦"是对 e05#309 的判断结论
- "trackside pub 不是赛道旁"是对 e02#719 的判断结论
- "特别留意"段把预扫点喂给审计 agent

## 适用

- audit agent prompt：遵守规则 1、2、4
- verify agent prompt：遵守规则 3
- synthesize 阶段主 agent 自己合并：不受本约束（主 agent 已知两边发现，合并是它的职责）

## 轮次相关占位符一览（`prompts/audit.tmpl`）

| 占位符 | 填什么 | 空值时的处理 |
|---|---|---|
| `{project_context}` | 中性领域事实 | 主 agent 自动合成一段，不留空 |
| `{round_scope}` | 本轮只审哪几类 | **不留空**，不填等于要求 agent 审全部 8 类 |
| `{ledger}` | 历史改动（去 reason 列） | R1 留一句「本次是第一轮，无历史台账」 |
| `{inclusive_list}` | L4 白名单（默认值，不是禁区） | 非 R11 留「本轮未启用第 8 类，不需要判断性别中立」，**不要留空** |
| `{seeds}` | `scan_seed.py` 出的锚点 + 归并段上下文（JSON 或 MD） | 非 R11 留空即可，模板已写好「若为空表示本轮未启用第 8 类」 |
| `{n_rows}` | 该片 SRT 总块数（**全片口径**，不是切片内行数） | **不许留空**。留空 = srt_id 没有上界，M2 的 15 次越界就是这么来的 |

`{start_block}` / `{end_block}` / `{n_rows}` 三个是**同一组**：模板用它们划出 srt_id 的
合法值域 `{start_block}..{end_block}`（全片 `1..{n_rows}`），并要求越界条目走「越界候选」
单列而不是混进发现列表。三者缺一，边界就说不清——只剩一个下界而没有上界时，
agent 会把「我觉得在附近」当成合法行号。

`round_scope`、`inclusive_list`、`seeds` 必须成对出现：
只给范围不给白名单，agent 会把 `母头` 报成敏感词；只给白名单不给范围，agent 会以为整轮都在审第 8 类。

**`{seeds}` 的措辞约束**：注入时必须同时出现「这是线索不是待办清单」那一句（`scan_seed.py` 的
`instruction` 字段自带）。只贴锚点不贴这句，agent 会退化成逐条勾选，漏掉锚点之外的问题——
而锚点之外恰恰是词表与正则的盲区。同理，**不许**在 prompt 里写「按 anchors 逐条判断」。
