# subtitle-polish

> ASS 双语字幕精校 Skill —— 三种模式：手动改一句 / 对轴 / 自动审校 9–11 轮。修复一律由脚本执行（dry-run / accept / rollback）。

**入口是 `SKILL.md`**，本 README 只做导航与全景，不重复细节。规则以 SKILL.md 与 `references/` 为准；两者冲突时，SKILL.md 赢。

## 三种模式

模式由用户调用时的措辞决定，**但最高优先级是「用户点名了要改成什么」**——那种情况一律走手动模式，即使同时出现「精校」「审计」字样。人已经把判据给出来了，再跑审计轮只会把这条指令淹没在几十条建议里。

| 模式 | 触发措辞 | 走什么 | 流程文档 |
|---|---|---|---|
| **手动** | `手动修` / `改` / `手动`，或直接说「把 0:01:16 改成 XXX」 | 人给指令 → fixes.json → dry-run → accept → verify，一气呵成不停门 | `references/manual-flow.md`（M0→M6） |
| **对轴** | `对轴` / `打轴` / `对齐` / `测轴`，或给了片源明说要看时间 | `align_audit` 测偏差 → `align_patch` 改时间字段，不碰文本 | `references/align-flow.md`（A0→A5 骨架）+ `build-timeline.md` + `align-audit.md` |
| **自动审校** | `精校` / `自动` / `审计`，或都没命中（默认） | 按轮次疗程逐轮审计修复，每轮一个 batch_id、快照可整轮回滚 | `references/auto-flow.md`（一轮 0→11）+ `rounds-spec.md`（多轮编排） |

### 模式是一个轴，监管是另一个轴

「跑几轮」和「每道门停不停」互相独立。**自动审校 × 逐步**（默认，每轮在门 1/门 2 停）与**自动审校 × 无监管**（`--auto`，一次跑完最后出总账）是同一流程的两个开关，不是两种新模式。

### 自动审校的开关

| 开关 | 作用 | 默认 |
|---|---|---|
| （无） | R1–R8 + R10，共 **9 轮** | ✅ |
| `--with-low` | 追加 R9（第 7 类低严重度） | 关 |
| `--with-inclusive` | 追加 R11（第 8 类中立与合规：性别/宗教/政治/法律） | 关 |
| `--with-spelling` | 把第 6 类**并入** R1–R3 与 R10 | 关 |
| `--auto` | 无监管：不停门，跑完出 `final-report.md` | 关 |

全开 = R1–R11 共 11 轮。**默认不跑第 6/7/8 类是有意为之，不是遗漏**——最终报告强制有「本次未覆盖」一节把它写出来。

**类别专轮一律全量出片，不切片取样。** token 不是本项目的稀缺资源，精确才是目标，这条是硬约束（`rounds-spec.md` §2）。

## 调用

```
/subtitle-polish <mode_keyword>:<ass_dir_or_file> 其对应的srt是 <srt_dir_or_file>
```

ass 与 srt 可以是目录或单文件。多文件默认同名配对（去扩展名 stem 相等），`--strip-suffix` 去指定后缀。项目背景写在 prompt 里，或放项目根 `.subtitle-polish/context.md`。

## 8 类问题分类法

| 类别 | 严重度 | 默认修 | 默认跑 |
|------|--------|--------|--------|
| 1 结构性生产缺陷（配对错位 / 英文轨覆盖 / 重复 / 截断 / 漏译） | 高 | 是 | 是 |
| 2 漏译 | 高 | 是 | 是 |
| 3 语义反转（否定 / 时态 / 程度 / 胜负颠倒） | 高 | 是 | 是 |
| 4 语境错译（词选对但场景不符） | 中 | 是 | 是 |
| 5 专名错误 / 不一致 | 中 | 是 | 是 |
| 6 原文拼写错误（undertrain→undertray） | 中 | 是 | **否**（`--with-spelling` 并入整体轮） |
| 7 低严重度（重复译文 / 语序 / 用词不自然） | 低 | 否（进 optional-fixes） | **否**（`--with-low` → R9） |
| 8 中立与合规（处女航→首航；政治表述只标注） | 中 | 按 A/B/C/D 子域 × L1–L4 分层 | **否**（`--with-inclusive` → R11） |

「默认修」说的是找到就改，「默认跑」说的是这一轮要不要去看——两者不是一回事。详见 `references/category-taxonomy.md` 与 `references/inclusive-language.md`。

## 关键设计

- **不带术语表**：作为第三者审校，不预设专名映射。每个专名基于上下文与领域知识判断前后是否一致。
- **SRT 是权威英文源**（除拼写错误——srt 与 ass 同源，拼写靠子 agent 判断）。
- **不 Edit ASS**：所有修改走脚本，skill 只编排流程。唯一例外是相邻块时间差 < 0.5s 的撞车场景，允许 Edit 但必须用 `apply_fixes.py --manual-log` 补记 log。
- **特效标签自动还原**：replace/swap 时自动提取并保留原行 `{\be3}`、`{\an8}` 等前导标签。
- **文本对 ≠ 时间对**：`verify_fixes` 与 `cross_check` 都不读时间字段，两者全绿时整集仍可能偏轴 2.9 秒。给了片源就必须跑 `align_audit.py`，判据是分时段 delta 中位极差，且**不能拿片源内嵌字幕流代替音频**。详见 `references/align-audit.md`。
- **时间轴在翻译前建立，不在交付前抢救**：先用 `extract_subs.py` 抽流、`align_audit --compare` 判轴——多数片源里本来就有同轴的那一条。详见 `references/build-timeline.md`。
- **判断归 agent，脚本只定位**：这是顶层原则，适用于全部 8 类。`scan_seed.py` 出的锚点只说明「这里出现了某种形态」，不说明「这里是问题」；`scan_inclusive.py` 返回 0 条候选只说明「词表没命中」，不说明「干净」。全文通读与最终判定由并行 subagent 做——一个 subagent 负责一个切片，在自己那一整片内把所有类别一起过。分工与切分规则见 `references/subagent-delegation.md`。
- **第 8 类白名单是默认值不是禁区**：`母头/公头/处女座/夫妻肺片/大陆架/台湾地区` 默认判「不是问题」；agent 通读后若认为该改，只能写 L3 给理由，不得自行造替换词绕过白名单。C 子域（政治与主权）一律只 flag 不落盘，具体时政条目不入词表——只做发现与标注，不做立场判定。
- **判「不是问题」也要写下来**：`false_positive` 记录是清单迭代的唯一来源；不写，清单就只增不减，最终退化成噪声。
- **Prompt 只喂事实，不喂结论**：历史台账可贴「改了什么」，不可贴「为什么改」，否则模型会顺着上一轮的判断继续错。工程上用 `regression_check.py --no-reason` 强制。

## 脚本

| 脚本 | 用途 | 模式 |
|---|---|---|
| `extract_slice.py` | ass+srt → 按 srt 块切片，标异常 | 自动审校 |
| `precheck_punct.py` | 中文行标点归一（默认 dry-run） | 自动审校 |
| `pre_audit.py` | 三轨预审（需显式开启） | 自动审校 |
| `scan_seed.py` | 出锚点（命中词 / 白名单候选 / 感叹·贬义·主权形态 + 归并段上下文），贴进审计 prompt。**只定位，不判断**；退出码恒 0 | 自动审校（R11，也用于 1–7 类查漏） |
| `scan_inclusive.py` | 第 8 类词表判定：按子域 A/B/C/D 分段出命中，C 只 flag 不改，L4 白名单优先丢弃。**词表 0 命中 ≠ 干净** | 自动审校（R11） |
| `round_orchestrator.py` | 轮次编排：排轮次表 / 记轮次 / 整轮快照回滚 / 定格 / 出 final-report | 自动审校 |
| `apply_fixes.py` | 执行 fixes.json / 回滚 / `--manual-log` | 三模式 |
| `global_replace.py` | 跨文件纯文本替换 | 三模式 |
| `verify_fixes.py` | 核验 log 已落盘（恒等式，不验译文对不对） | 三模式 |
| `cross_check.py` | 中英对照复核 + 撞车预警 + 动到历史结论 | 三模式 |
| `regression_check.py` | 跨轮次台账 / 连续改动 / 批次沉住度（只读 log） | 三模式 |
| `extract_subs.py` | 列 / 抽片源内嵌字幕流（判轴的前置） | 对轴 |
| `align_audit.py` | 对音频测时间偏差（whisper/qwen 双引擎） | 对轴 |
| `align_patch.py` | 按偏移改时间轴（线性 / 曲线 / 重定时），写 log、`--revert` | 对轴 |
| `timeline_gate.py` | 读凭据判时间轴能否开工（不跑模型） | 对轴 + 自动审校阶段 0 |
| `precheck_timeline.py` | L0 结构哨兵：秒级时间轴体检（不加载模型） | 前置 |
| `lib/` | time_fmt / ass_srt_pair / log / tags / paths / align_core | — |

## 结案条件

三条判据，结论四态：**PASS(0) / FAIL(2) / UNVERIFIED(3) / AMBIGUOUS(4)**。`UNVERIFIED` 不是「通过」，是「没验」——报告里不许写成「全部通过」。

```bash
python scripts/verify_fixes.py   --batch-id <ts>   # 盘面 == log
python scripts/cross_check.py    --batch-id <ts>   # 中英对照复核
python scripts/align_audit.py    --sub <ass> --media <片源> --write-credential   # 对音频对齐
python scripts/timeline_gate.py  <ass> --media <片源>                            # 凭据闸门（毫秒级）
```

- `verify_fixes` 0 失败只证明「改的东西确实写进去了」，**是恒等式，与译文对不对无关**。
- `cross_check` 读的是译文，但只看当前盘面，且撞车预警召回有限，表干净不等于全文正确。
- `align_audit` 证明「写进去的东西出现在对的时间」。

前两条都不看时间字段——**文本全对、时间轴整集偏 2.9 秒的成品照样全绿**。无片源时第三条跑不了，但必须在报告里写明「本次未验时间轴」。

## 回滚

```bash
python scripts/apply_fixes.py --rollback batch=<batch_id>
python scripts/apply_fixes.py --rollback id=<srt_id> --file <ass_path>
python scripts/apply_fixes.py --rollback before=<ts>
python scripts/round_orchestrator.py --run <stamp> --rollback-to r03   # 整轮快照
```

**多轮叠加后不要用 `--rollback batch=` 逐轮往回退**：会撞上 retime 浮点残差、delete 无法重建、global_replace 交叉三个限制。回退轮次用 `round_orchestrator.py --rollback-to rNN`，它是整字节快照，ASS 与 log 一起还原。详见 `references/rounds-spec.md` §5.3。

## 产出（项目侧，不进 skill）

```
.subtitle-polish/
├── slices/            # 切片（审计中间产物）
├── reports/           # audit-report.md / detail / dry-run.md / precheck-punct.md / verify-fixes.md
├── fixes.json         # 主修清单（1–6 类）
├── optional-fixes.json# 第 7 类低严重度
├── runs/<stamp>/      # 自动审校：轮次快照 + manifest + final-report.md
├── log.jsonl          # 不进 git
└── (字幕同目录) <episode>.ts.json   # 时间轴凭据，进 git
```

## 依赖

- Python 3（系统 python）
- `pysubs2`（skill 启动时自动 `pip install pysubs2`）
- 对齐审计另需（只在跑 `align_audit.py` 时）：`faster-whisper` + large-v3 模型；或 `qwen_asr` + `Qwen3-ForcedAligner-0.6B` + `soundfile`/`torch`。视频抽音轨需 `ffmpeg`。缺这些不影响文本精校。

## 测试

```bash
cd <skill-forge>
python tests/test_subtitle_polish_inclusive.py    # 第 8 类白名单 / 分层 / 静默漏检
python tests/test_subtitle_polish_regression.py   # 台账 / 连续改动 / --no-reason
python tests/test_subtitle_polish_rounds.py       # 轮次编排 / 定格 / 快照回滚
```

`tests/test_subtitle_polish_*.py` 全 14 个文件，改动后应全绿。

## 范围与边界

- **适用**：ASS 双语成品 + SRT 源。track 取值 `英文/中文/注释`。
- **不适用**：无 SRT 源（拒绝运行）、VTT / 单语成品、SRT 双语。
- 其他语言对要改 track 名需改 prompts 模板与脚本配置。
