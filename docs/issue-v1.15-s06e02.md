# issue v1.15 — S06E02 取证报告核实：哪些是真缺陷，哪些是现场惹的

- 依据：`S06E02/.subtitle-polish/runs/20261102_100945/forensics/FINAL-REPORT.md`（第二轮取证）
- 立场：**只核实，不改代码。** 本文逐条判定报告里的 20 个问题在 skill 代码里是否成立。
- 关联：issue #24（v1.14）的 A/B/C/D 已合入 `1eea777`；本文只谈它没覆盖到的部分。

---

## 0. 一句话结论

报告质量很高，但**它取证的是「一次手工带跑」的项目，不是 skill 本身**。20 条里：

| 分类 | 条数 | 含义 |
|---|---|---|
| **skill 真缺陷** | 9 | 代码/文档里确实存在，与 E02 无关，换一集照样发生 |
| **E02 现场惹的** | 7 | 起因是主会话临时写的 `tools/*.py`，skill 里没有这些文件 |
| **报告判断有误** | 3 | 报告自己标了「更正」，但我核下来仍有偏差 |
| **合理建议但非缺陷** | 1 | 方向对，但报告当成 bug 写 |

最重要的三条真缺陷，按修复价值排序：

1. **A1 标签语义反转**（`ass_srt_pair.py:350-352` + `pipeline-spec.md:44`）
2. **A5 时间戳兜底定位**（`apply_fixes.py:110` `±0.5s`，`cross_check.py:64/77` 秒级 key）
3. **B4 验证默认驳回**（`auto-flow.md:191` 明写「adversarial 默认驳回」）

第 1 条是本次事故的**语义源头**，且 **issue #24 完全没碰**。

---

## 1. 逐条判定表

### 1.1 skill 真缺陷（9 条）

| # | 报告描述 | 代码位置（已核） | 判定 |
|---|---|---|---|
| **A1** | `SRT_HAS_ASS_NONE` 实为「配对失败」，被读成「ASS 缺行」 | `lib/ass_srt_pair.py:347-352`；`references/pipeline-spec.md:44` | ✅ 成立，且比报告说的更严重 |
| **A5** | `_find_dialogue` 按 SRT 时间戳 ±0.5s 定位，未命中静默退回最近行 | `apply_fixes.py:85-147`（`abs(e.start/1000 - target_start) <= 0.5`，第 110 行） | ✅ 成立 |
| **A4** | 三检无法证明「改动已发生」 | `verify_fixes.py` 有 `verify_entry`，但**走 `_find_dialogue`**，定位不到时返回 `None` 判失败而非 abort；且 `--manual-log` 路径同样走时间戳 | ⚠️ 部分成立：账实断言**已存在**（`act_body == exp_body`），但它依赖的定位器本身不可靠 |
| **B4** | verify 任务书预设「默认驳回」 | `references/auto-flow.md:191`：「**adversarial 默认驳回**：只有找不到反驳理由才确认」 | ✅ 成立，是文档明文规定 |
| **B7** | R9 自称标点已查、与读过的行矛盾 | `rounds-spec.md` 8 类清单**无「标点/排版」类**；`precheck_punct.py` 存在但命中项不阻断 | ✅ 成立 |
| **C1** | 台账重复写入（23 组） | `lib/log.py:20-45` `append_log` **无幂等键**，同一 `(batch,srt_id,track)` 可反复追加 | ✅ 根因成立（但直接肇事者是现场脚本，见 1.2） |
| **C4** | `align_audit` 静默剔除离群锚点 | `lib/align_core.py:242-258` `robust_reject` 只返回 `dropped` 计数，不返回清单与理由；`align_audit.py:318/351` 只打印数字 | ✅ 成立 |
| **D1** | `--report` 产物被覆盖、宽度截断 | `round_orchestrator.py:647` `[:16]`、`672` `[:18]`、`673` `[:20]`、`685` `[:20]` | ✅ 成立（截断仍在；覆盖问题已由 D4 解决） |
| **A2** | 两套切片并存且新旧颠倒 | `extract_slice.py` **无单一权威路径强制**；`--out` 默认 `slices` 但可任意指定；重建不删旧 | ✅ 成立 |

#### A1 特别说明：这是本次唯一「issue #24 完全没碰」的 P0

`ass_srt_pair.py:347-352` 的实际代码：

```python
# 漏译：有英文无中文（音效块除外）
if pb.english and not pb.chinese:
    anomalies.append("SRT_HAS_ASS_NONE")  # 中文行缺失
if not pb.english and not pb.chinese and not sb.is_sound_effect_only():
    # 非音效却两边都没匹配，标 SRT_HAS_ASS_NONE
    anomalies.append("SRT_HAS_ASS_NONE")
```

两个分支共用一个标签，但语义完全不同：

| 分支 | 真实含义 | 标签字面义 | 审计员会怎么读 |
|---|---|---|---|
| 有英文无中文 | **真的漏译** | SRT 有、ASS 没有 | 对 |
| **两边都空** | **配对彻底失败** | SRT 有、ASS 没有 | **错**，会去补不存在的内容 |

而 `pipeline-spec.md:44` 把这层错误语义固化成文档：

```
| `SRT_HAS_ASS_NONE` | srt 块在 ass 里找不到对应（漏译/丢行） |
```

它把「找不到对应」（配对失败）和「漏译/丢行」（内容缺失）写成了同一件事。

**R5 p1 报出 38 条「漏译」→ 重跑后 0 条**，根因就是这里。E02 那次是脚本走的时间窗配对（现场工具），但**同一个坑在 skill 自己的 `pair()` 里也存在**——只要 SRT 与 ASS 有漂移，两边都空就会批量打这个标签。

> **实施时补正（见 §7.1）**：上面这张表只有两行，实际要拆成**三行**。实测 S06E02 全片 869 块里被标「配对失败」的 47 条，**逐条回查 ASS 全部都有完整中英对照**——它们是起点差 0.50~1.92 s 的超容差，一条真缺失都没有。所以「配对彻底失败」这一格必须再分成「轴错位（有内容、超容差）」和「真缺内容（ASS 里压根没有）」，两者的处置完全相反。

---

### 1.2 E02 现场惹的（7 条）

这些脚本在 **`S06E02/.subtitle-polish/tools/`**，不在 skill 的 `scripts/` 里。它们是主会话当时为了绕开 SRT/ASS 漂移临时写的。

| # | 报告描述 | 肇事文件 | 为什么不是 skill 缺陷 |
|---|---|---|---|
| **C1 直接成因** | 台账 23 条重复 | `tools/record_text_edits.py:17,20` 常量硬编码，argparse 从被读过 | skill 里没有这个文件；但 `append_log` 无幂等键让它无从防（见 1.1 C1） |
| **C2** | `apply_text_edits.py` 出生时无回滚 | `tools/apply_text_edits.py`（`--rollback-batch` 后补） | skill 的 `apply_fixes.py` 回滚粒度 B3 已齐 |
| **B1** | R5 p1 把配对空洞误报漏译 | `tools/extract_slice_slots.py`（时间窗版） | skill 的 `extract_slice.py` 用文本锚定 `pair()` |
| **A3** | 523 错行一路通过 | `tools/run_round.py` / `verify_text_edits.py` | skill 无 `verify_text_edits.py`，对应的是 `verify_fixes.py` |
| **B3** | 任务书晚于会话启动 | `tools/render_prompts.py` / `build_round_prompt.py` | skill 无渲染器；`auto-flow.md` 只规定填哪些占位符，不含时序 |
| **B5** | R1 verify 汇总数与明细对不上 | 子代理手写汇总 | 这是 agent 行为，不是脚本 |
| **C3** | 快照命名与批次边界不一致 | `tools/run_round.py` | skill 无快照器 |

**这条区分很重要**：报告 §7 提的很多「根治方案」，其对象是现场脚本而非 skill。照着改 skill 会改错地方。

---

### 1.3 报告判断有误（3 条）

| # | 报告说法 | 核实结果 |
|---|---|---|
| **A2「新旧颠倒」** | `slices/`（v1）权威、`slices_v2/`（v2）坏 | 报告自己在 §2.1 标了「更正」。但**skill 里 `extract_slice.py` 输出的就是「文本锚定、0 空行」这一版**，与 v1 同构。所以「v1 才对」这个结论，其实是在说「skill 的默认行为才对」，报告没把这层点出来 |
| **A4「三检都无法证明改动已发生」** | 说 verify 只验「没多改」 | `verify_fixes.py:229` **确实逐条断言** `act_body == exp_body`，是**账实断言**。报告这条低估了现状。真问题是：断言依赖 `_find_dialogue` 定位，定位错了断言就验错了对象 |
| **C5「未按规则冻结」** | R1 轴修 FAIL 后「修到 PASS 再继续」 | 这属于流程执行偏差，`round_orchestrator` 的 `freeze_run` 机制**存在且可用**（`tests` 里有 `t_freeze_*` 全绿）。问题在「没人调用」，不是「没能力」 |

---

### 1.4 合理建议但非缺陷（1 条）

| # | 报告描述 | 判定 |
|---|---|---|
| **B8** | R8–R11 四轮净贡献仅 1 行 | 是**效率问题不是 bug**。收口轮做定向复核确实更省，但「全量重扫」是 v1.13 明确裁决过的（判断归 LLM，宁可多跑）。改这条要先推翻那个裁决 |

---

## 2. 三条 P0 的修法草案（待确认，不实施）

### 2.1 A1：拆标签 + 改配对失败行为

`ass_srt_pair.py`：

```python
# 有英文无中文 —— 这才是真·漏译
if pb.english and not pb.chinese:
    anomalies.append("ZH_MISSING")

# 两边都空 —— 配对失败，不是漏译
if not pb.english and not pb.chinese and not sb.is_sound_effect_only():
    anomalies.append(f"PAIRING_FAILED(srt_id={sb.index})")
```

配套三件事：

1. `pipeline-spec.md:44` 表格拆成两行，语义写清
2. `prompts/audit.tmpl:15` 的异常标记清单同步改，并加一句：**「看到 `PAIRING_FAILED` 时，第一反应是报告配对缺陷，不是补译」**
3. `extract_slice.py` 在 `PAIRING_FAILED` 比率超阈值时 abort（复用现有 `assert_not_empty` 的位置）

> 为什么不能只改文档：标签是**脚本打的**，文档改了脚本照样打错标，下一个读切片的 agent 照样被误导。

### 2.2 A5：`_find_dialogue` 只留文本锚定

这条有个**必须先解决的矛盾**：`_find_dialogue` 的整个存在理由就是「SRT 与 ASS 时间轴不同步时仍能定位」。删掉时间戳，它靠什么找行？

我倾向的路径（需要你定）：

| 方案 | 做法 | 代价 |
|---|---|---|
| **甲（推荐）** | 保留 ±0.5s 但**只在候选唯一时接受**；候选 0 或多条 → 改用 `current` 文本唯一匹配；两者都不成 → **abort** | 要改 `_find_dialogue` 的返回契约（现在返回 `Event \| None`，要能区分「没找到」和「不唯一」） |
| 乙 | 完全删时间戳，只留文本锚定 | 首轮 `apply_fixes` 就没有 `current` 可用（审计稿才刚产出），会把「文本有重复」的正常场景变成硬失败 |
| 丙 | 保留现状，但把「静默退回最近行」改成打印告警 | 最省事，但报告的核心批评（**静默**）只解决一半 |

报告 §7 说「删掉时间戳兜底，只允许唯一文本锚定，命中数 ≠ 1 即 abort」，方向对，但它没考虑首轮没有 `current` 的情况。**甲是它的可执行版。**

> **⚠️ 措辞修订（v1.15 第四轮，已裁决采纳）**
>
> 上表写的「abort，不猜」容易被读成「只要不是唯一文本命中就必须 abort」，那样会把
> **顺序映射**这种有证据的定位一起挡掉——顺序映射用两侧文本交叉验证得出 SRT 块 ↔
> ASS 行的对应关系，它的行号是**推出来的**，不是「猜的」。
>
> 正确的口径是「**不能无证据地猜**」：
>
> | 情形 | 是否有证据 | 能否落盘 |
> |---|---|---|
> | ±0.5s 窗内候选唯一 | 时间 | 能 |
> | `current` 文本唯一匹配 | 文本 | 能 |
> | 顺序映射 + 文本交叉验证通过 | 文本（邻块对齐关系） | **能** |
> | 文本对不上 / 候选不唯一又无文本证据 | 无 | **abort** |
>
> **⚠️ 顺序映射的前置条件（v1.15 第五轮，已裁决采纳）**
>
> 上表第三行不能无条件成立。顺序映射的成立前提是**两条轨都存在**：它靠「同一
> SRT 块在英、中两轨上各有恰好一行、且两侧文本能交叉验证」推出块 ↔ 行对应。
> 一旦某条轨整段缺失（纯中字素材、英文轨被前面某轮吞掉、或该块本来就只有一轨），
> 那个「邻块对齐关系」就只剩单侧证据，退化成**按行号数出来的猜**——
> 它仍然会给出一行，但那行是数出来的，不是验出来的。
>
> 所以第三行必须读成：
>
> | 情形 | 是否有证据 | 能否落盘 |
> |---|---|---|
> | 顺序映射 + **双轨都在** + 文本交叉验证通过 | 文本（邻块对齐关系） | 能 |
> | 顺序映射 + **单轨**（对侧轨缺失） | 无（只是行号数出来的） | **abort** |
>
> 判据在实现上应可机械检查：`index_align` 的每一项都应当同时对应英、中两轨的
> 行；只对应一侧的项不得进入 `index_align`。否则「顺序映射」会变成绕开 abort
> 的旁路——它看起来有证据，其实只有一半。
>
> 这一条与 H-2（`_monotonic_fallback` 在无英文轨时整块短路、47 块中文被升格成
> `PAIRING_OUT_OF_TOLERANCE`）是同一个病灶的两面：都假设「双轨齐全」。H-2 本轮
> 未修（裁决范围外），但顺序映射这一侧的前提必须先写清，否则修 H-2 时会被
> 「顺序映射能兜住」这句说法误导。
>
> 实现上对应 `_find_dialogue(..., strict=True)`：给了 `index_align` 但映射指向的起点
> 上找不到行、或候选不唯一又无文本证据时返回 `None`，而不是退回 ±0.5s 窗蒙一个。
> 区分「有证据的定位」与「无证据的猜」才是这一条要守住的东西，不是「必须唯一」。下文
> §7 批次 F 里的「abort 不猜」同此口径。

### 2.3 B4：verify 任务书中立化

`auto-flow.md:191` 现在是：

> **adversarial 默认驳回**：只有找不到反驳理由才确认。

改为：

> **逐条举证**：对每条发现回答「证据是否支持这个改动」，必须引用原文。**不为挫折而确认，也不为省事而驳回**。分歧必须给出反证原文，不接受「感觉不对」。

同时 `prompts/verify.tmpl` 里对应句子一起改——**文档和模板必须同时改**，只改一处等于没改。

---

## 3. 与 issue #24 的关系

| 报告问题 | issue #24 是否已覆盖 |
|---|---|
| A4 账实断言 | 部分（`verify_entry` 已有断言，A2 回读改进了 `current` 来源） |
| C4 剔除清单 | ❌ 未覆盖 |
| D1 截断 | ❌ 未覆盖（D4 只解决了「报告写哪」） |
| A1 标签语义 | ❌ **完全未覆盖** |
| A5 时间戳兜底 | ❌ 未覆盖（A2 只改了 `current` 来源，没改定位方式） |
| B4 默认驳回 | ❌ 未覆盖 |
| A2 单一切片路径 | ❌ 未覆盖 |

**结论：#24 修的是「采纳链路与门禁」，本次报告打的是「配对语义与定位方式」，是两批不同的洞。**

---

## 4. 建议的批次划分

| 批次 | 内容 | 依赖 | 风险 |
|---|---|---|---|
| **E** | A1 拆标签 + 三处文档同步 + 配对失败 abort | 无 | 低。改的是标记名与判据，不动定位 |
| **F** | A5 定位器改造（方案甲） | E（要先能区分「没配上」和「没找到」） | **高**。`_find_dialogue` 被 `apply_fixes` / `verify_fixes` / `cross_check` 三处共用，改契约要连带改三个调用方 |
| **G** | C4 剔除清单 + D1 去截断 + B4 中立化 | 无 | 低，纯输出层 |
| **H** | A2 单一切片路径 | 无 | 中。要决定旧切片怎么处理（删/归档/拒读） |

E + G 可以一起做，成本低、收效直接。F 单独做，要先补测试锁住现有行为。

---

## 5. 明确不做的

| 提议 | 为什么不做 |
|---|---|
| 按报告 §7 全面重写现场脚本 | 那些脚本不在 skill 里，重写它们对 skill 无益 |
| B8 收口轮改定向复核 | 与 v1.13「全量、不省 token」的裁决冲突。要改先开新 issue 推翻裁决 |
| 引入第三条独立时间源（报告 C4 建议） | 方向对但成本远超收益。当前问题不是「缺时间源」，是「剔除不透明」 |

---

## 6. 需要你定的事

1. **A5 走甲/乙/丙**？（我推荐甲）→ **已定：甲**（保留 ±0.5s 时间窗，只在候选唯一时接受；0 或多条改用 `current` 文本唯一匹配；都不成则 abort）。见 §7 批次 F。**口径已修订为「不能无证据地猜」**——顺序映射属有证据的定位，可以落盘；文本对不上才 abort。详见 §2.2 末尾的措辞修订。
2. **批次 E + G 要不要先做**？（低风险，能立刻解决「标签误导」和「报告不可读」）→ **已定：先做**。已完成，见 §7。
3. **A2 旧切片怎么处理**：删 / 移到 `slices_stale/` / 拒读？ → **已定：归档**。改名到 `<out>_stale_<YYYYmmdd_HHMMSS>/`，不删。已随 E 批次落地。

---

## 7. 实施记录

### 7.1 批次 E（已完成）

| 改动 | 文件 | 内容 |
|---|---|---|
| 拆标签（**三形态**） | `scripts/lib/ass_srt_pair.py` | `SRT_HAS_ASS_NONE` → `ZH_MISSING`（英文在、中文空，真漏译）/ `PAIRING_OUT_OF_TOLERANCE(off=±N.NNs)`（两边都空但 ASS 里有这句，只是起点差超容差）/ `PAIRING_FAILED(srt_id=N)`（两边都空且 30 s 内 ASS 无任何起点）。新增 `_nearest_ass_offset()` / `MAX_REPORTABLE_OFFSET = 30.0` / `TIME_TOLERANCE` 常量显式化 |
| 配对门禁 | `scripts/extract_slice.py` | 新增 `MAX_UNPAIRED_RATE = 0.10` / `pairing_failed_ids()` / `_pairing_tag()` / `pairing_offset()` / `_pairing_breakdown()` / `assert_pairing_ok()`。分子**两种形态都算**，abort 时按形态给不同处置建议。**位置在 `os.makedirs` 之前**，与 `assert_not_empty` 同一处；顺序固定为先空后零星 |
| 旧切片归档 | `scripts/extract_slice.py` | 新增 `archive_stale()`，`--out` 已有 `.txt` 时整目录 rename 到 `<out>_stale_<时间戳>`；碰撞自动加 `_1`/`_2` 后缀 |
| 文档同步 | `references/pipeline-spec.md` | 异常标记表由 2 行扩到 3 行 + 三形态判别顺序 + 「只拆前两种是不够的」的教训记录 |
| 文档同步 | `prompts/audit.tmpl` | 标记清单改三形态；每种形态单独说明「该报什么、**为什么不能补译**」（超容差补了会和 ASS 里已有的撞车；真缺失补了是凭空编） |
| 文档同步 | `references/auto-flow.md` | 头注清单改三形态；补「两道门禁（顺序固定）」「重建即归档」两条流程纪律 |
| 文档同步 | `references/manual-flow.md` | 补归档说明（A2 同步） |

**A1 的关键教训：第一版只拆成两个名字是不够的。**
第一版按「有英文无中文 / 两边都空」拆成 `ZH_MISSING` / `PAIRING_FAILED`，看起来已经分开漏译和配对失败了。实测 S06E02 全片 869 块，被标 `PAIRING_FAILED` 的 **47 条逐条回查 ASS，全部都有完整中英对照，一条真缺失都没有**——它们是 srt 与 ass 的起点差 **0.50~1.92 s**、超出 `TIME_TOLERANCE = 0.5s` 容差窗。
两者的处置**完全相反**：超容差是轴的问题（该校轴或放宽容差，补译是错的）；真缺失是素材的问题（该换素材）。合成一个标签，读的人只会一律当「漏译」处理——这正是 R5 p1 报 38 条假漏译的机制，只是换了个名字还在发生。

**另一个实测发现（不是 bug，写进 spec 了）**：`parse_ass:207/213` 两处 `continue` 会跳过空文本行，所以「ASS 行在但文本为空」在结构上不会进入配对——`PAIRING_FAILED` 只能由「ASS 里压根没有这段」触发。这也是为什么人为清空中文轨只会得到 `ZH_MISSING`。

**门禁阈值不能靠人为平移来验证**：把一批 Dialogue 整体后移 1.5 s 想造出超容差，结果 1/5 后移 → 4.7%、1/3 后移 → 4.0%，都低于 10% 阈值——平移后相邻块的英文行落进容差窗顶替上了，配上率反而上升。所以验证门禁用注入式单元夹具（P5/P6），不靠构造坏素材。

**一个实现细节**：`archive_stale` 用 `os.path.normpath()` 而非 `rstrip('/\\')`——`--out` 为相对路径且带尾斜杠时，后者会拼出 `//`，`os.path.dirname` 也可能返回 `""` 导致 `makedirs("")` 报错。`parent` 非空才 `makedirs`。

### 7.2 批次 G（已完成）

| 改动 | 文件 | 内容 |
|---|---|---|
| B4 中立化 | `prompts/verify.tmpl` | `:1` 去掉「adversarial / 尽力反驳」；`:7` 「**默认驳回**」→「逐条举证，双向可驳回」+「不对确认放水，也不对驳回放水」；`:44` 理由字段要求「无论确认还是驳回都要给原文依据，只写『感觉不对』不算理由」 |
| B4 同步 | `references/auto-flow.md:191` | 条目改名「逐条举证，双向驳回」，明写「不得设方向性默认值（原来的 adversarial 默认驳回已废弃）」 |
| B4 同步 | `references/prompt-injection.md` | `:7`、`:42` 去掉 adversarial 措辞；`:42` 加注说明第三轮实测的畸形确认率**是 prompt 塞答案导致的**，无论立场怎么设都会全确认，不能当「默认驳回失效」的证据 |
| B4 同步 | `references/subagent-delegation.md:44` | 「反驳误报 ‖ adversarial」→「逐条举证、判真伪 ‖ 复核」 |
| B4 同步 | `references/fluency-rubric.md:126` | 「adversarial 终审维度」→「终审维度，需逐条举证」 |
| C4 剔除清单 | `scripts/lib/align_core.py` | `robust_reject` 的 info 新增 `thr_mode`（`floor`/`k_mad`）、`k_mad`、`floor`、`drop_idx`、`rejected`（含 idx/start/delta/dev，按偏差绝对值降序）、`max_abs_dev`。新增 `format_reject_table()` |
| C4 输出 | `scripts/align_audit.py` | `print_summary` 打印清单（控制台前 20 条）；`build_report` 新增「离群剔除明细」小节，Markdown 表格给全量；`--json` 的 payload 加 `reject` 字段（原来 `keep, _ =` 直接丢弃 info） |
| D1 去截断 | `scripts/round_orchestrator.py` | 新增 `_md_cell()`（转义 `\|`、换行转 `<br>`、先转义反斜杠），替换四处 `[:16]/[:18]/[:20]`。`limit` 默认 0=不限 |

**C4 的 `thr_mode` 为什么要单独给**：`thr = max(floor, k_mad*mad)`，E02 实测 MAD 很小，实际生效的永远是 `floor=1.5`，`k_mad=6.0` 完全没参与。不点明这一点，看到「剔了 43 条」的人第一反应是调 `k_mad`，改了毫无变化。

**D1 为什么是去截断而不是换更聪明的截断**：改动总账里「原译」「终译」两列就是整份报告的存在理由。截到 20 字后，「He was going to say」和「He was going to say something」在表里长得一模一样，两条不同改动视觉上无法区分。要短得由调用方显式传 `limit`。

### 7.3.1 第五轮裁决与修复（H-1 / M-1 / M-2）

第五轮测试 agent 拿来两份文件（`S06E02实测3/问题汇总.md`、`答复.md`），Q1~Q7 全
判「符合」、Q8 判「不符」。逐条核实后按四项裁决执行：

| 裁决 | 内容 |
|---|---|
| H-1 | 硬拒 + 语言一致性检查（两道纵深防御），**不改写 current 照常写盘** |
| Q8 | 接受 agent 的三级证据表，并补「顺序映射仅双轨可用」前提（已写入 §2.2） |
| 批次范围 | 只做 H-1 + M-1 + M-2；**H-2 / M-3 / H-3 本轮不动** |
| L-2 | 只改 docstring 写清样本口径，**不改代码、不加时间门槛** |

**H-1 的两种实测形态**（都在 `%TEMP%/h1test` 复现，修前 RC=0、修后 RC=1）：

| 形态 | 输入 | 修前后果 | 修后 |
|---|---|---|---|
| 语种矛盾 | `track=英文` + `current='我明白了'` | 英文轨被写入中文译文 | reject，文件逐字未动 |
| 子串 current | `current='最基本的清理'`，实读 `'我会做最基本的清理 但它确实很脏'` | 整行换成 5 个字，后半句蒸发 | reject，不改写 current |

第二种更险：**不需要写错任何字段**，只要 current 不是逐字整行。而且两道下游检查
都接不住——verify 看「新文本是否落盘」（落盘即 PASS），cross_check 看重复/相似
（不报「英文轨里出现中文」）。

**为什么「原实现那道 `raise SystemExit(1)` 从来没生效过」**：撞车预检里那条
`if not any(clean_ass_text(x) == want …)` 检查的是**改写后**的 `current`。旧实现打
一行 `[?]` 就把 `fx["current"]` 换成回读值再照常写盘，改写让它恒真。

**一处必须配合的修正（本轮新发现）**：`current` 的「回读快照」不能塞回
`fx["current"]`。回读发生在整个文件循环**之前**，是「一条都没写时的快照」；同一
srt_id 上若前一条 replace 先写（R6 合并场景：replace 合并两行 + retime 延长时间
轴），后一条拿到的快照已经过期 → `_find_dialogue(prefer_text=…)` 对不上 → 返回
None → 定位失败，retime 静默不执行（现象：合并后 end 没延到 1428.91）。而且快照
带前导特效标签（`{\be3}…`），而匹配是拿 `clean_ass_text` 归一后的文本比的。
所以拆成两个字段：`current`（只有 fix 自己声明时才有）与 `_current_snapshot`
（只给撞车预检定位用）。

**M-1**：`_find_dialogue` 里 `prefer_text` 给了却一行都没对上 → `return None`，
不再退回「时间戳最近的那条」。注意 **strict 不是这里的开关**：strict 管的是
「映射缺失时不许退窗」，而这里 current 已经给了、只是对不上，无论是否 strict 都不该猜。

**M-2**：`run_rollback` 改为**全有或全无**。上一版是「能定位的照常写盘」：CASE-B
实测 `回滚 1 条，失败 1 条` 然后 `subs.save()`，成品里一半新文本、一半原文，而
调用方只看到一行「回滚 1 条」。这比「全失败」危险得多——全失败至少是「什么都没做」，
半成功是「做了一半、且没人知道是哪一半」。回滚的语义是「退回到某个时刻」，一个
时刻要么到达、要么没到达。

配套两点：`failed > 0` 时 `raise SystemExit(1)`（原来 `return count` 让「0 条成功」
和「部分成功」都返回 0，包装它的 `--rollback-to` 只看退出码），以及 `count -= file_ok`
（没写盘就不算回滚成功，别让汇总数字好看）。

**delete 的 continue 必须提到定位之前**：`delete` 的逆（重建一行）**必然**定位失败，
因为那行已经删了。放在定位之后，每条 delete 都先被算进「定位失败」，再撞上全有或
全无 → 整批回滚一律拒写，等于「只要这批里有 delete，就永远回滚不了」。已知限制 ≠ 失败：
重建不了是「回滚做不到这一条」，不是「这批数据坏了」，不计 failed。

### 7.3 回归结果

`tests/` 下 19 个 subtitle-polish 相关文件 **287 项全绿**，0 失败（G 批次后 251 项 + 本轮新增 `current_strict` 6 项 + 补齐此前未计入的 `cross_check`/`missing_file_key`/`whitespace_policy`/`zh_only`）：

```
axis_l0 17 / bugs 8 / cross_check 7 / cross_chunk 25 / current_strict 6 /
curve_fit 12 / delete_identity 5 / fluency 8 / inclusive 23 / manual_log_check 6 /
missing_file_key 6 / pairing_tags 7 / plan_chunk 19 / regression 41 / retime 10 /
rollback_identity 5 / rounds 19 / seed 32 / timeline_credential 14 /
verify_blindspot 6 / whitespace_policy 6 / zh_only 5
```

本轮 `current_strict` 的 6 项按「坏的拦住、好的放过」成对设计，只测一半等于没测：

| 用例 | 断言 |
|---|---|
| N1 语种矛盾 | `track=英文` + 中文 current → 文件 md5 逐字节未变 + RC≠0 |
| N2 子串 current | 行内片段非整行 → 文件 md5 逐字节未变 + RC≠0 |
| N3 自洽 fix（反向对照） | 中文轨 + 逐字整行 → 正常写入 + RC=0 |
| N4 行内碎片 delete | 片段**确实是一条独立行** → 放行（与 N2 的分界线：是不是行组里的一整条） |
| M1 回滚全有或全无 | 一条定位失败 → 整文件拒写 + RC≠0 |
| M2 回滚全部成功 | 正常写盘 + RC=0（防「靠全拒通过」） |

新增的 `test_subtitle_polish_pairing_tags.py` 用最小夹具锁三形态判别与门禁（不依赖真实字幕）：
先造三块 srt —— 一块正常、一块删掉中文行、一块 ass 起点偏 +1.20 s —— 再补一块附近 5 分钟什么都没有的，分别断言命中 `ZH_MISSING` / `PAIRING_OUT_OF_TOLERANCE(off≈+1.20s)` / `PAIRING_FAILED`；P4 断言音效块不打配对标记；P5 断言门禁分子含两种形态（3/10=30% → abort）；P6 断言 abort 发生在写盘前（目录不存在）。

`test_green_bugs.py` 4 passed / 2 failed 与 `test_red_bugs.py` 6 failed 均为**历史遗留**：两个文件的 `SKILL_ROOT` 指向 `glue-engineer`，测的不是本 skill。

### 7.4 剩下没做的

**第五轮明确留到后面的（裁决范围外，不是因为难才不修，是因为它们各自要单独定口径）：**

- **H-2 纯中字素材 47 块蒸发**：`_monotonic_fallback` 里 `if not srt_sorted or not en_rows: return {}` 把 `zh_rows`（`:387-388` 已算好）完全没用上。纯中字素材 47 块（5.4%）整块变空、被升格成 `PAIRING_OUT_OF_TOLERANCE`，而 `extract_slice` 报 `nonempty: 822/869（95%）` 看起来像合格。**要动对齐核心，风险最高**，且与 §2.2 新写的「顺序映射仅双轨可用」前提是同一病灶（都假设双轨齐全）——两者应当一起改，先改前提再改实现。
- **M-3 `working/` 台账从未写入**：真实根因不是「累积快照重复计数」。实测 10 个 `logs/rNN.jsonl` **每个恰好 3 行**（都是 r00 那三条），因为 `_sync_working()` 只在 `:396`（整轮回滚）调用，正常轮次从不调用 ⇒ `working/log.jsonl` 整轮结束时仍不存在 ⇒ `_merge_working_log` 早退 `return 0` ⇒ `src` 回退主台账 ⇒ 拷成快照。**与 `paths.py` 白名单设计互相打架**，要先定「working 是不是独立命名空间」。
- **H-3 retime 吃行尾空格**：`_retime_event` 之外的一处空白归一化，与「空白修剪不计入语义改动」口径有冲突，要单独核。
- **L-1**（no-op fix 也写 log）、**L-4~L-7**：都是记账口径问题，不写坏成品。

**更早留的：**

- **批次 F（A5 方案甲）**：`_find_dialogue` 现在返回 `Event | None`，改成三态要连带改 `apply_fixes` / `verify_fixes` / `cross_check` 三个调用方。**先补测试锁住现有行为再动**。方案甲的取舍已定（保留 ±0.5s 窗但只在候选唯一时接受；0 或多条改用 `current` 唯一文本匹配；都不成 abort——**口径按 §2.2 修订为「不能无证据地猜」，顺序映射算有证据，但仅限双轨都在时**），但**它和 A1 是同一类病**：现在的标签只说明「没配上」，说明不了「为什么没配上」，所以 F 落地时 `_find_dialogue` 的三态应当带上「候选 0 / 候选多条 / 时间窗命中但文本不符」这三种成因，否则又会重演 A1 的教训。
- **H 的路径引用同步**：`manual-flow.md` 已加归档说明；各脚本 `--help` 里若提到 `slices/` 固定路径需再核（当前未发现冲突引用）。
