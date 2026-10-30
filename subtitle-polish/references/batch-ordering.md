# 批次顺序与 verify_fixes 失败处理

精校流程里多个脚本会改 ASS 文件（precheck_punct / apply_fixes / global_replace），它们跑的先后顺序有硬约束。SKILL.md 阶段 2.5/11 引用本文件。

## 问题

第三轮实测（会话 8ea54874）暴露：主 agent 在主修 apply_fixes（批 A）**之后**又跑了 precheck_punct --accept（批 C2），导致：
- 主修写入的 `……` 被 precheck 的 `……`→`…` 规则再处理（3 条）
- 主修有意写入的译注 `(EMU)` 被 precheck 的"删注释括号"规则删掉（1 条真损失，srt_id 588）
- verify_fixes.py 按 A 的日志比对当前盘面，报 4 条假失败，主 agent 用"预期差异"自行结案，真损失被埋掉

## 硬约束：precheck --accept 必须在 apply_fixes 之前

```
正确顺序：
  precheck_punct --accept（批 1，标点归一）
  → global_replace（批 2，如需统一专名，纯替换类）
  → apply_fixes --accept --batch-id（批 3，主修）
  → verify_fixes --batch-id（核对主修落盘）
```

**原因**：
- precheck 的 `……`→`…` 会改掉主修写入的 `……`（主修 final_new 若带 `……`，apply_fixes 写入后，precheck 再跑会归一）。
- precheck 的注释括号规则会删掉主修有意加的译注（如 `(EMU)`/`(机务段)`）。
- 主修应基于"已经标点归一过的"ASS 写 final_new，避免写入后再被 precheck 改。

**所以**：先 precheck 把标点理顺，再 apply_fixes 在干净盘面上写主修，主修的 final_new 就是最终态，不再被后续标点 pass 改动。verify_fixes 比对主修日志与当前盘面，0 失败。

## 例外：global_replace 的位置

global_replace 做纯文本替换（如 `法兰西斯`→`弗朗西斯`），不改标点、不删括号，可在主修前或后。但若主修的某条 fix 被 global_replace 覆盖（如 e02#13 Francis 由 global_replace 统一处理），那条 fix 在 fixes.json 里标 `status=deferred_to_global`/`enabled=false`，不重复执行。global_replace 建议在主修前跑，避免主修写入后又被 global_replace 改动文本。

## 一句拆多条 Dialogue：合并碎片行必须带 `current`

生产环节会把一句话拆成**多条独立 Dialogue**（同 start/end、同 track），这时要修就得「1 条 replace 合并 + N 条 delete 删碎片」，全都落在同一个 srt_id 上。

**每条 fix 都必须写 `current`（该行原文）**，apply_fixes 据此精确定位：

```json
[
  {"id": "e03#148a", "srt_id": 148, "track": "中文", "action": "replace",
   "current": "MX-5 是的", "suggested_new": "MX-5 是的"},
  {"id": "e03#148b", "srt_id": 148, "track": "中文", "action": "delete",
   "current": "是的"}
]
```

不带 `current` 时，`--accept` 会直接拒写（issue #2）。原来它只是往 dry-run.md 写一条预警，然后照写不误、退出码 0，最后得到「合并了一半」的残骸：英文行被删、碎片行留着。

> 历史坑（已修，别改回去）：`subs.events.remove(e)` 走 `==`，而 pysubs2 的 `SSAEvent.__eq__` **只比较 start/end**。所以删中文碎片行时删掉的是同时间戳的英文行。现在统一用 `_remove_event()`（按 `is` 身份删）。`tests/test_subtitle_polish_delete_identity.py` 有护栏。

（如 `法兰西斯`→`弗朗西斯`），不改标点、不删括号，可在主修前或后。但若主修的某条 fix 被 global_replace 覆盖（如 e02#13 Francis 由 global_replace 统一处理），那条 fix 在 fixes.json 里标 `status=deferred_to_global`/`enabled=false`，不重复执行。global_replace 建议在主修前跑，避免主修写入后又被 global_replace 改动文本。

## verify_fixes 失败的处理

verify_fixes.py 报失败时，**不得用"预期差异"自行结案**。每条失败都必须：

1. **读盘核对**：读 ASS 当前文本，看期望 vs 实际差异是什么。
2. **分类**：
   - 标点差异（`……`→`…`）：说明批次顺序错了（precheck 在主修后跑），回滚 precheck batch 或按正确顺序重跑。
   - 译注被删（`(EMU)` 丢失）：真损失，必须补回——回滚主修那条，final_new 改成 precheck 归一后的文本（`…` 而非 `……`、不带会被删的括号），重新 apply_fixes；或在主修后单独补一条 apply_fixes 把译注加回。
   - 文本不符：真 bug，回滚主修那条重做。
3. **0 失败才结案**：全部修到 verify_fixes 0 失败，才能向用户报告完成。不得写"28 通过 / 4 失败，但 4 条是预期差异"这种话术。

### 反向盲区：0 失败 ≠ 正确

上面整节讨论的都是「该写进去的没写进去」。另有一类失败曾经**verify_fixes 报不出来**：

**写入成功，但写的内容是错的。**

因为 verify 比对的是 `expected_new`（取自 log 的 `new_text`，即 apply_fixes 自己刚写的值）与盘面，两者天然相等——是恒等式。只要写盘成功就必然通过。

实测（skill-forge issue #1）：一轮 99 条 fix，verify 报 104 通过 / 0 失败，其中 15 条把原本正确的译文换成了邻行的、或是同场景另一句的译文。这些条目在 verify 里全部是 PASS。

issue #1 修复后（2026-10-30），verify_fixes 内建了两条**可判定的**硬判据，上述 15 条里能自动抓到 4 条：

- **D1 硬约束**：中文轨译文为空/只有标点、或整句塞了英文原文（≥4 个连续英文词）→ 判失败。只判可证明的「对不上」，不假装能判语义。
- **E 邻块撞车**：新译文与 ±3 邻块（排除本次写入那条）现有译文相似度 ≥0.55 → 判失败并指出撞了哪个 srt_id。实测召回 4/15，好条误报 0/84。

`apply_fixes.py --dry-run` 也会在写盘前用同一判据打「⚠ 撞车预警」，accept 前逐条读英文确认。

**但这不代表盲区没了。** 剩下 11 条是「换成同场景另一句」，任何字符串判据都抓不到。所以本节的「0 失败才结案」仍然**不是结案条件，只是结案的必要条件**。真正的结案条件是：

```
verify_fixes 0 失败  AND  cross_check 中英对照复核通过
```

`cross_check.py` 见 `auto-flow.md` 11b 节。它做两件事：把本批改动的「英文/中文」摊开供逐条判断，以及用纯字符串相似度列出**撞车预警**（新译文 ≈ 邻块译文，实测误报 0、召回 4/15）。

常见错位形态与对策：

| 形态 | 表现 | 能否被字符串判据抓到 |
|---|---|---|
| 抄邻块 | 新译文 ≈ 相邻块的现有译文 | 能（verify E / dry-run 撞车预警） |
| 只剩英文 | 中文轨塞了英文原文、或译文清空 | 能（verify D1） |
| 串到邻行 | 写成了邻块的内容，但邻块本身还保留着自己的译文，两者不完全相等 | 部分（相似度可能 0.6 左右） |
| 同场景换句 | 换成同一场景下另一句话（如四句压成一句、改了代词指代） | **不能**，只能中英对照 |
| 缩译掩盖漏译 | 英文三句，译文只留一句 | 不能 |

结论：**自动化只能拦截「逐字能判错」的形态，语义对不对仍然必须靠中英对照。** 任何"verify 0 失败"的表述，报告里都要写清它没覆盖语义错译——不要把绿色当成正确。


## 第三轮实测 588 (EMU) 真损失案例

主修 id 23（e05#588）要求写入 `那些电力动车组(EMU)在吵 97型机车也是`。apply_fixes 写入成功（log.jsonl 记录）。随后 precheck_punct --accept 跑，把 `(EMU)` 当注释括号删掉，盘面变成 `那些电力动车组在吵 97型机车也是`。verify_fixes 报 588 失败（期望含 `(EMU)`，实际不含）。主 agent 在汇报里承认"丢了 (EMU) 注释"但没回滚也没修复，当成"预期差异"埋掉。

**正确处理**：588 报失败时，应回滚 precheck batch（或单独补一条 apply_fixes 写回 `(EMU)`），改 precheck 规则（注释括号收窄，见 references/punct-rules.md）后重跑，verify_fixes 0 失败再结案。

## 回滚说明

apply_fixes --rollback 读 log.jsonl 反向应用 old_text，支持 batch/id/before 三种粒度。global_replace 与 precheck_punct 当前**不单独支持 --rollback**（argparse 未注册），其改动靠：
- `.bak` 文件手动还原（apply_fixes 执行时备份原文件），或
- 若 global_replace/precheck 的 log.jsonl 条目能被 apply_fixes --rollback 认（按 action 字段），则用 apply_fixes --rollback batch=<它们的 batch_id>；需先核 apply_fixes --rollback 是否过滤 action。

apply_fixes --rollback 不过滤 action 字段——`replace`/`delete`/`swap`/`insert`/`manual_edit`/`precheck_punct` 都能回滚（`manual_edit` 按 old_text 写回，`delete` 回滚时打印"无法自动重建"提示人工补，`insert` 回滚删该行）。global_replace 若用了与 apply_fixes 一致的 action 字段记 log，也能用同一 rollback。

未来若给 global_replace/precheck 加 --rollback，复用 lib/log.py 的 read_log + filter_log 反向应用 old_text 即可。
