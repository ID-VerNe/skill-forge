---
name: subtitle-polish
version: 1.0.0
description: 字幕精校。用户说"精校字幕"、"字幕审计"、"修字幕"时触发。输入 ASS 双语成品 + SRT 源，走 审计→人确认→修复 全流程，修复由脚本执行（dry-run/accept/rollback）。也支持 /subtitle-polish 命令。
---

# subtitle-polish 字幕精校 Skill

## 适用范围

- 输入：ASS 双语成品（英文行 + 中文行成对，track 取值 `英文/中文/注释`）+ SRT 源（权威英文）
- 不适用：无 SRT 源（拒绝运行）、VTT/单语成品、SRT 双语（不处理）
- 修复手段：只调脚本（extract_slice / apply_fixes / global_replace），**不直接 Edit ASS**

## 调用约定

```
/subtitle-polish 精校：<ass_dir_or_file> 其对应的srt是 <srt_dir_or_file>
```

ass 与 srt 可以是目录或单文件：
- 多文件：默认同名配对（去扩展名 stem 相等），`--strip-suffix` 去指定后缀
- 单文件：用户给详细地址，直接用

可选项目背景写在 prompt 里（如"这是汽车节目，注意底盘术语"），或放项目根 `.subtitle-polish/context.md`。

## 激活流程

技能激活后：

1. **解析 prompt**：提取 ass 路径、srt 路径、可选项目背景。
2. **校验**：若无 srt 路径 → 停下，告知"需要 SRT 源才能跑"。
3. 按下面「阶段流程」0→11 执行，每阶段结束向用户报告进度。
4. 门1（md 报告后）与门2（dry-run 后）**停下等用户**，不自动推进。

## 阶段流程

### 0. 环境检查

- 系统有 python（默认）。检查 `pysubs2`：`python -c "import pysubs2"`，失败则 `python -m pip install pysubs2`。

### 1. 配对

- 多文件：用 `lib/ass_srt_pair.pair_dirs(ass_dir, srt_dir)` 同名配对。
- 单文件：直接用 `pair_files(ass_path, srt_path)`。
- 输出 `[(ass_path, srt_path), ...]` 给用户确认。

### 2. 提取切片

对每对文件跑：
```bash
python <skill>/scripts/extract_slice.py <ass> <srt> --out .subtitle-polish/slices/
```
- 按 srt 块序号切，~700 块/份 + 100 块 overlap。
- 输出 `.subtitle-polish/slices/<stem>_p<n>.txt`，一 block 一行：
  `<srt_id> | <ass_time> | <英文> | <中文> | <注释>`
- 头注列异常标记：ASS_HAS_SRT_NONE / SRT_HAS_ASS_NONE / ONE_TO_MANY / MULTI_SAME_LANG / ASS_TRACK_OVERWRITE

### 3. 审计（自适应起 agent）

- 每文件份数 = `max(1, round(块数/700))`。
- **小文件短路**：单文件块数 < 200 时，主 agent 可直接审计该切片，不必另起子 agent（省成本）。
- 每份起一个子 agent，prompt 用 `prompts/audit.tmpl`，填入 `{slice_path}`、`{start_block}`、`{end_block}`、`{project_context}`。
- project_context 来源（按优先级）：① 用户 prompt 里写的背景；② `.subtitle-polish/context.md`；③ **两者都没有时，主 agent 读 SRT 前 50 块 + ASS 样式自动合成一段项目背景**（领域、话题、疑似专名列表）。
- 子 agent 后台跑期间，**主 agent 用 grep/正则独立预扫可疑点**（专名不一致、异常字符、ASR 错词模式），子 agent 返回后合并两边发现。
- 子 agent 报告：附 [start_block, end_block] 范围 + 问题列表（srt_id/类别/严重度/英文/现译/问题/建议）。

### 4. 验证轮1（按类别打包）

- 把同类问题打包给一个验证 agent，prompt 用 `prompts/verify.tmpl`（支持 `{findings}` 列表，多条独立给结论）。
- 输入：每条问题 + 前后各 5 块上下文 + srt 原文。
- **adversarial 默认驳回**：只有找不到反驳理由才确认。
- 验证 agent 发现 srt_id 与 srt 原文不符时，输出 `corrected_srt_id`（纠正后定位键），主 agent 据此修正 fixes.json。
- 补 agent 触发（绝对阈值，非相对均值）：某文件验证驳回率 > 40%，或确认问题密度 > 1/100 块 → 补 agent 重看**整个文件**。最多补 2 轮。单文件场景阈值同样适用。

### 5. 合并报告

- 主 agent 用 `prompts/synthesize.tmpl` 合并，按 (file, srt_id, category) 去重。
- 输出 `.subtitle-polish/reports/audit-report.md`（小节式，按严重度排序）。
- 多文件：另出每文件明细 `.subtitle-polish/reports/<stem>-detail.md`。
- 每条格式：
  ```
  ### <id> — <类别>（严重度）
  - 英文: <原文>
  - 现译: <当前中文>
  - 问题: <一句话>
  - 建议: <建议译文>
  ```
- id 空间：单文件 `1..N`；多文件 `<shortname>#<srt_id>`（如 `e02#152`）。
- 第 7 类（低严重度）单独写 `.subtitle-polish/reports/optional-fixes.md`。

### 6. 人确认门1

- 把 audit-report.md 路径告诉用户，**停下**。
- 用户回复形式："修 <id列表>，<id> 是误报，<id> 特意翻的"。
- 区分 `status` 字段（fixes.json 里记）：`accepted`（修）、`misreport`（误报，不该报）、`intentional`（特意翻的，译文本就对的）、`skipped`（暂不处理）。所有非 accepted 的都 `enabled=false` 不执行，但 status 记原因。
- 用户也可能直接给意见让重审某条。

### 7. 生成 fixes.json

- 按用户选的 id 生成 `.subtitle-polish/fixes.json`（1-6 类）。
- 每条：`{id, audit_id, file, srt_id, track, action, suggested_new, final_new, category, reason, enabled, status, srt_path}`
  - `audit_id`：对应审计报告里的发现编号；`id` 是 fix 自身编号。一条审计发现可拆多条 fix，id 用 `<audit_id><suffix>`（如 `1a`/`1b`/`3a`），audit_id 为父。
  - `final_new` 缺省 = `suggested_new`；用户改过则覆盖。
  - `enabled=true` 仅给 status=accepted 的；其余 `enabled=false`。
  - `status` ∈ accepted | misreport | intentional | skipped（见门1）。
  - `action` ∈ replace | delete | swap（swap 换文本不换时间戳，附 `swap_with`）。
  - `srt_path` 显式写，避免脚本找不到配对 srt。
- 第 7 类进 `.subtitle-polish/optional-fixes.json`，默认不并入主修。

### 8. 脚本 dry-run

```bash
python <skill>/scripts/apply_fixes.py .subtitle-polish/fixes.json --dry-run
```
- 输出 `.subtitle-polish/reports/dry-run.md`（每条 file/id/现译→新译/类别，现译与新译都显示含标签的真实文本）。

### 9. 人确认门2

- 把 dry-run.md 路径告诉用户，**停下**。
- 用户显式 accept 后才执行。**门1的"修 1-5"只授权生成 fixes.json 和跑 dry-run，不等于门2通过**。除非用户在门1明确说"全修并直接执行"（合并语义），否则必须等门2独立确认。

### 10. 执行

```bash
python <skill>/scripts/apply_fixes.py .subtitle-polish/fixes.json --accept --batch-id <ts>
```
- 按 srt_id + track 定位（srt_id→timestamp→ass Dialogue）。
- 每条写 `.subtitle-polish/log.jsonl`（ts/batch_id/action/file/srt_id/track/old_text/new_text/category/reason）。
- 备份原文件为 `.bak`。

### 11. 验证轮2（可选）

- 用户对仍存疑条目可再起验证 agent（用 verify.tmpl）。

## 回滚

```bash
# 按整 batch
python <skill>/scripts/apply_fixes.py --rollback batch=<batch_id>
# 按单条
python <skill>/scripts/apply_fixes.py --rollback id=<srt_id> --file <ass_path>
# 按时间点（回滚该时间之前所有）
python <skill>/scripts/apply_fixes.py --rollback before=<ts>
```
所有操作都留 log.jsonl 记录，支持单条/整 batch/时间点三种粒度回滚。

## 全局替换（跨文件统一专名）

审计后若发现专名不一致（如 维多利亚皇冠 9 处应统一为 皇冠维多利亚）：
```bash
python <skill>/scripts/global_replace.py <pattern> <replacement> --track 中文 --files <glob> --dry-run
python <skill>/scripts/global_replace.py <pattern> <replacement> --track 中文 --files <glob> --accept
```
默认只改中文行，`--track 英文` 改英文行。

## 文件结构

```
<skill>/
├── SKILL.md
├── references/        # 7 类分类法、数据流规范、术语处理原则
├── prompts/           # audit/verify/synthesize 模板
└── scripts/           # extract_slice.py / apply_fixes.py / global_replace.py + lib/
```

项目产物（不进 skill）：
```
.subtitle-polish/
├── slices/            # 切片
├── reports/           # audit-report.md / detail / dry-run.md / optional-fixes.md
├── fixes.json
├── optional-fixes.json
└── log.jsonl          # 不进 git，.gitignore 加它
```

## 重要约束

- **不带术语表**：作为第三者审校，不预设专名映射。详见 `references/glossary-handling.md`。
- **7 类分类法**：结构性生产缺陷/漏译/语义反转/语境错译/专名错误不一致/原文拼写错误/低严重度。详见 `references/category-taxonomy.md`。
- **不 Edit ASS**：所有修改走脚本。
- **srt 是权威英文源**（除拼写错误，srt 与 ass 同源，拼写靠子 agent 判断）。
- **异常标记**：提取脚本自动标 ASS_HAS_SRT_NONE 等，这些本身是审计线索。
- **不要幻觉**：审计 agent 拿不准就别报，宁可漏报不要误报（有验证轮兜底）。
