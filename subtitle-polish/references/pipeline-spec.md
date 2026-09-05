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

按 **srt 块序号** 切，~700 块/份 + 100 块 overlap。每份文件 `<stem>_p<n>.txt`。

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

## 配对算法（lib/ass_srt_pair.py）

时间戳模糊匹配 + 原文文本双校验：

1. srt 块的时间戳转 ass 格式（毫秒截 2 位）。
2. 在 ass Dialogue 里找时间戳相差 ±0.5s 内的候选行。
3. 对候选行做文本相似度（fuzzy ratio），>85 才配对。
4. 任一校验不过 → 标 unpaired（SRT_HAS_ASS_NONE 或 ASS_HAS_SRT_NONE）。
5. 一个 srt 块配到多行 → ONE_TO_MANY。
6. 同一 block 内同语言多行 → MULTI_SAME_LANG。

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
│   ├── <stem>-detail.md      # 每文件明细（多文件时）
│   └── dry-run.md            # 修复 dry-run 预览
├── fixes.json       # 主修清单（1-6 类）
├── optional-fixes.json  # 第 7 类低严重度
└── log.jsonl        # 操作日志（不进 git）
```

`.gitignore` 加 `.subtitle-polish/log.jsonl`（不进 git，其余进）。

## fixes.json schema

```json
[
  {
    "id": "e02#152",            // 单文件：1..N；多文件：<shortname>#<srt_id>
    "file": ".../e02....ass",   // 目标 ass 绝对路径
    "srt_id": 152,              // srt 块序号（定位键）
    "track": "中文",            // 英文/中文/注释
    "action": "replace",        // replace | delete | swap
    "suggested_new": "我把托马斯甩开了",  // agent 建议
    "final_new": "我把托马斯甩开了",      // 人确认后；缺省=suggested_new
    "category": "语义反转",
    "reason": "胜负颠倒 losing=甩开",
    "enabled": true             // 人 accept 时 true，skipped/误报 false
  }
]
```

**swap** 额外字段：`swap_with`: 另一个 srt_id。交换两行的文本部分，不动时间戳/样式/标签。

## id 空间

- **单文件输入**：全局 `1..N`，按 srt_id 顺序编号。
- **多文件输入**：`<shortname>#<srt_id>`，shortname 取文件名可识别部分（如 `e02`）。

## log.jsonl schema

```json
{"ts":"2026-09-05T21:30:00","batch_id":"20260905_213000","action":"replace","file":".../e02....ass","srt_id":152,"track":"中文","old_text":"我输了","new_text":"我把托马斯甩开了","category":"语义反转","reason":"胜负颠倒"}
```
一行一条。不进 git。

## rollback

三种粒度，按 log.jsonl 反向应用 old_text：
- `--rollback batch=<batch_id>`：回滚整个 batch
- `--rollback id=<srt_id>`：回滚单条（按 srt_id+file 定位）
- `--rollback before=<ts>`：回滚某时间点之前所有操作

所有操作都留记录，避免单条回滚破坏成对修改（可整 batch 回滚后再选择性重做）。
