# 数据流与文件格式规范

## 输入

- **ass 成品**：双语 ASS（英文行 + 中文行成对，同一时间戳）。track 取值固定 `英文/中文/注释`。
- **srt 源**：权威英文源（纯英文）。srt 必须提供，否则 skill 拒绝运行。
- **调用**：
  ```
  /subtitle-polish 精校：<ass_dir_or_file> 其对应的srt是 <srt_dir_or_file>
  ```

## 配对规则

- **多文件**：默认同名匹配（去扩展名后 stem 相等，忽略大小写）。可选 `--strip-suffix` 去指定后缀（如 `track3,track4,_cleaned`）应对未来命名变化。
- **单文件**：用户在 prompt 里给详细地址，skill 直接用。
- **pipeline 成品**：最终 ass 与 srt 的 stem 一致（_cleaned 只在 cache 中间文件里，不影响成品配对）。

## 切片格式（extract_slice.py 输出）

按 **srt 块序号** 切，~700 块/份 + 100 块 overlap。每份文件 `<stem>_p<n>.txt`（stem 与 id 空间 shortname 一致，如 `e02_p1.txt`，不用 `s1e2_p1`）。

**一 block 一行**：
```
<srt_id> | <ass_time> | <英文> | <中文> | <注释>
```
- `<srt_id>`：srt 块序号（1-based）
- `<ass_time>`：ass 时间戳（`0:MM:SS.CC` 起止，如 `0:01:23.45`）
- `<英文>`：ass 里该 block 的英文行文本（去 `{\be3}` 等标签），多行用 ` ⏎ ` 连
- `<中文>`：中文行文本，多行用 ` ⏎ ` 连
- `<注释>`：注释行文本，无则留空

**字段分隔**：` | `（空格竖线空格）。

**头注**：每份文件开头用 `#` 注释行列出该份的异常 block（见下）。

## 异常标记

提取脚本配对时遇到以下情况标记异常，写进切片头注 + 报告：

| 标记 | 含义 |
|------|------|
| `ASS_HAS_SRT_NONE` | ass 有 Dialogue 但 srt 没有对应块（ass 多出行） |
| `SRT_HAS_ASS_NONE` | srt 块在 ass 里找不到对应（漏译/丢行） |
| `ONE_TO_MANY` | 一个 srt 块在 ass 里配到多个时间戳相近的行 |
| `MULTI_SAME_LANG` | 同一 block 内有多个英文行或多个中文行（不允许；最多英-中-注） |
| `ASS_TRACK_OVERWRITE` | 英文行的可见文本含中文字符（英文轨被中文覆盖，生产缺陷） |
| `TIME_TEXT_DRIFT` | 时间戳匹配但英文文本仅部分相似（ass 可能人工调轴），需人工核查 |

## 配对算法（lib/ass_srt_pair.py）

时间戳模糊匹配 + 原文文本双校验：

1. srt 块的时间戳转 ass 格式（毫秒截 2 位）。
2. 在 ass Dialogue 里找时间戳相差 ±0.5s 内的候选行。
3. 对候选行做文本相似度（fuzzy ratio，归一化去标点/去说话人标记后），>85 才配对；纯音效块（srt 全是 `[xxx]`）按时间戳配即可。
4. 时间戳不过但文本相似度 >85 → 仍配对并标 anomaly 提示时间偏移（应对 ass 人工调轴场景）。
5. 任一校验不过 → 标 unpaired（SRT_HAS_ASS_NONE 或 ASS_HAS_SRT_NONE）。
6. 一个 srt 块配到多行 → ONE_TO_MANY。
7. 同一 block 内同语言多行 → MULTI_SAME_LANG。
8. 英文行可见文本含中文 → ASS_TRACK_OVERWRITE。
9. 时间戳匹配但英文相似度 0.6~0.85 → TIME_TEXT_DRIFT（ass 可能调轴）。

## 时间格式（lib/time_fmt.py）

- ASS：`H:MM:SS.CC`（2 位毫秒），如 `0:01:23.45`
- SRT：`HH:MM:SS,CCC`（3 位毫秒），如 `00:01:23,450`
- 互转：毫秒截 2 位（SRT→ASS）或补 0（ASS→SRT）。

## 产出文件位置

所有产物放项目根 `.subtitle-polish/`：
```
.subtitle-polish/
├── slices/          # 切片文件（审计中间产物）
├── reports/
│   ├── audit-report.md       # 主审计报告（小节式，严重度排序）
│   ├── <stem>-detail.md      # 每文件明细（多文件时，每文件一个，不合并）
│   ├── dry-run.md            # 修复 dry-run 预览
│   ├── precheck-punct.md     # 标点预检报告（dry-run；accept 不覆盖此文件）
│   ├── optional-fixes.md     # 第 7 类润色（人读）
│   └── verify-fixes.md       # 执行后验证报告
├── fixes.json       # 主修清单（1-6 类，是脚本的输入）
├── optional-fixes.json  # 第 7 类低严重度（机器读，同 fixes.json schema）
└── log.jsonl        # 操作日志（不进 git）
```

**分界**：`fixes.json` / `optional-fixes.json` 是脚本输入（人/AI 编辑），`reports/` 是脚本输出（只读）。`log.jsonl` 不进 git，其余进。

`.gitignore` 加 `.subtitle-polish/log.jsonl`（不进 git，其余进）。

### 报告每条带时间戳

所有报告（audit-report.md / dry-run.md / verify-fixes.md / optional-fixes.md）的每条 `###` 标题或正文必须带 `<ass_time>` 时间戳（如 `0:01:16.56-0:01:18.00`），方便人对照视频定位。时间戳来自切片文件的 `<ass_time>` 字段（synthesize 阶段）或 ass Dialogue 的 start/end（dry-run/verify 阶段，脚本定位时已取）。

### optional-fixes.json 必须生成

第 7 类低严重度项**必须同时**生成 `optional-fixes.md`（人读）和 `optional-fixes.json`（机器读，同 fixes.json schema）。只出 .md 不出 .json 视为流程缺陷——驳回/低严重度项无 structured 追溯，回滚时无法按 id 定位。

### 门 1 升级后重生 audit-report.md

门 1 用户把 optional 项升级到 main 后，主 agent 必须**重新生成 audit-report.md**（含升级条目，标注"用户升级"），dry-run 必须和最新 audit-report 一一对应。否则 audit-report（旧 23 条）与 fixes.json（升级后 33 条）对不上，回滚时无法追溯。

### 每文件一个 detail 报告

多文件场景，每文件一个 `<stem>-detail.md`，不合并到一个文件。如 `e02-detail.md` + `e05-detail.md`，不要把 E05 节塞进 e02-detail.md。

## 补 agent 触发阈值

阶段 4 验证轮后，按文件统计确认问题密度：

- **绝对阈值**：某文件确认问题密度 > 1/100 块 → 补 agent 重看整个文件。最多补 2 轮。
- **驳回率**：某文件验证驳回率 > 40% → 补 agent 重看整个文件。
- **超过即触发，不得加软条件跳过**（如"刚过""验证确凿""大概率重复"）。这些是主 agent 自行放宽阈值的借口，第三轮实测 E02=1.11/100、E05=1.91/100 都超阈值，主 agent 加三软条件跳过，漏报风险未被兜底。

单文件场景阈值同样适用。

## 验证上下文构造

阶段 4 验证轮，主 agent 给 verify agent 喂"前后各 5 块"上下文时，**必须用 skill 的 `build_verify_ctx.py`**（不要手写脚本）：

```
python <skill>/scripts/build_verify_ctx.py <findings.json> <slice_paths...> <srt_path>
```

- 输入 findings.json（审计 agent 输出解析成的结构化 JSON）+ 切片文件列表（多切片，跨边界自动从含该 id 的切片取上下文）+ srt 路径
- 输出 verify_ctx.txt，每条 finding 带前后各 5 块上下文 + srt 原文 + ass_time
- 主 agent 把输出 **inline 进 verify.tmpl 的 `{findings}` 占位符**，不靠 SendMessage 二次喂、不让 verify agent 自己 Read ctx 文件
- 禁止手工编号上下文块（数行易 +1 偏移，test2 实测偏移 -2 导致 verify agent 被误导）

## fixes.json schema

```json
[
  {
    "id": "e02#152",            // fix 自身编号；多文件用 <shortname>#<srt_id>，拆条加后缀 <audit_id><suffix>
    "audit_id": "e02#152",     // 对应审计报告里的发现编号（父）；多文件与 id 一致
    "file": ".../e02....ass",   // 目标 ass 路径（脚本会归一化比较）
    "srt_id": 152,              // srt 块序号（定位键）
    "track": "中文",            // 英文/中文/注释
    "action": "replace",        // replace | delete | swap
    "suggested_new": "我把托马斯甩开了",  // agent 建议
    "final_new": "我把托马斯甩开了",      // 人确认后；缺省=suggested_new
    "category": "语义反转",
    "reason": "胜负颠倒 losing=甩开",
    "enabled": true,            // 仅 status=accepted 为 true
    "status": "accepted",       // accepted|misreport|intentional|skipped|deferred_to_global
    "srt_path": ".../e02....srt"  // 显式写配对 srt，避免脚本找不到
  }
]
```

- **id = audit_id**（多文件用 `<shortname>#<srt_id>`，如 `e02#152`；单文件也用此格式而非全局序号）。fixes.json / dry-run.md / audit-report.md 三处 id 一致，人 review 时一眼对上。**不用全局 1..N 序号**（第三轮实测用了全局序号 `1..33` + audit_id 双轨，人看 fixes.json 得靠 audit_id 反查 id，多此一举）。
- **一条审计发现可拆多条 fix**：例如 audit_id=`e02#152` 配对错位要改 srt 4+5 两行中文 → fix `e02#152a`(srt 4) + `e02#152b`(srt 5)，共享 `audit_id=e02#152`。id 加字母后缀区分。
- **swap** 额外字段：`swap_with`: 另一个 srt_id。交换两行的文本部分，不动时间戳/样式/标签。
- **status 语义**：
  - `accepted`=修（apply_fixes 执行）
  - `misreport`=误报（不该报）
  - `intentional`=特意翻的（译文本就对）
  - `skipped`=暂不处理
  - `deferred_to_global`=转给 global_replace 处理（如 Francis 统一替换，本条不执行，避免与 global_replace 重复改）
  - 非 accepted 都 `enabled=false` 不执行，但 status 记原因供追溯。

## id 空间

- **统一格式**：`<shortname>#<srt_id>`，shortname 取文件名可识别部分（如 `e02`）。单文件也用此格式（shortname 从文件名取），不用全局 `1..N`。
- **拆条**：`<shortname>#<srt_id><suffix>`（如 `e02#152a`、`e02#152b`），suffix 用字母。

## log.jsonl schema

```json
{"ts":"2026-09-05T21:30:00","batch_id":"20260905_213000","action":"replace","file":"C:/abs/path/e02.ass","srt_id":152,"track":"中文","old_text":"{\\be3}我输了","new_text":"{\\be3}我把托马斯甩开了","category":"语义反转","reason":"胜负颠倒"}
```
一行一条。不进 git。

**字段说明**：
- `file`：归一化为绝对路径存储，rollback 比较时容忍相对路径/斜杠方向差异（filter_log 用 `_norm_file` 归一化两端比较）。
- `old_text` / `new_text`：都记**实际落盘的 ASS 文本**（含合并后的 `{\be3}` 等标签），forward 与 rollback 对称、可重放。replace 的 new_text = `_replace_text` 后的 `e.text`（不是 fixes 里的裸 final_new）。
- rollback 定位：优先 srt_id→timestamp→Dialogue；srt 推不到时用 new_text 去 tag 后在 subs 里搜当前内容（fallback）。

## rollback

三种粒度，按 log.jsonl 反向应用 old_text：
- `--rollback batch=<batch_id>`：回滚整个 batch
- `--rollback id=<srt_id>`：回滚单条（按 srt_id+file 定位）
- `--rollback before=<ts>`：回滚某时间点之前所有操作

所有操作都留记录，避免单条回滚破坏成对修改（可整 batch 回滚后再选择性重做）。
