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
| **甲（推荐）** | 保留 ±0.5s 但**只在候选唯一时接受**；候选 0 或多条 → 改用 `current` 文本唯一匹配；两者都不成 → **abort，不猜** | 要改 `_find_dialogue` 的返回契约（现在返回 `Event \| None`，要能区分「没找到」和「不唯一」） |
| 乙 | 完全删时间戳，只留文本锚定 | 首轮 `apply_fixes` 就没有 `current` 可用（审计稿才刚产出），会把「文本有重复」的正常场景变成硬失败 |
| 丙 | 保留现状，但把「静默退回最近行」改成打印告警 | 最省事，但报告的核心批评（**静默**）只解决一半 |

报告 §7 说「删掉时间戳兜底，只允许唯一文本锚定，命中数 ≠ 1 即 abort」，方向对，但它没考虑首轮没有 `current` 的情况。**甲是它的可执行版。**

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

1. **A5 走甲/乙/丙**？（我推荐甲）
2. **批次 E + G 要不要先做**？（低风险，能立刻解决「标签误导」和「报告不可读」）
3. **A2 旧切片怎么处理**：删 / 移到 `slices_stale/` / 拒读？
