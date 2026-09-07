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

## verify_fixes 失败的处理

verify_fixes.py 报失败时，**不得用"预期差异"自行结案**。每条失败都必须：

1. **读盘核对**：读 ASS 当前文本，看期望 vs 实际差异是什么。
2. **分类**：
   - 标点差异（`……`→`…`）：说明批次顺序错了（precheck 在主修后跑），回滚 precheck batch 或按正确顺序重跑。
   - 译注被删（`(EMU)` 丢失）：真损失，必须补回——回滚主修那条，final_new 改成 precheck 归一后的文本（`…` 而非 `……`、不带会被删的括号），重新 apply_fixes；或在主修后单独补一条 apply_fixes 把译注加回。
   - 文本不符：真 bug，回滚主修那条重做。
3. **0 失败才结案**：全部修到 verify_fixes 0 失败，才能向用户报告完成。不得写"28 通过 / 4 失败，但 4 条是预期差异"这种话术。

## 第三轮实测 588 (EMU) 真损失案例

主修 id 23（e05#588）要求写入 `那些电力动车组(EMU)在吵 97型机车也是`。apply_fixes 写入成功（log.jsonl 记录）。随后 precheck_punct --accept 跑，把 `(EMU)` 当注释括号删掉，盘面变成 `那些电力动车组在吵 97型机车也是`。verify_fixes 报 588 失败（期望含 `(EMU)`，实际不含）。主 agent 在汇报里承认"丢了 (EMU) 注释"但没回滚也没修复，当成"预期差异"埋掉。

**正确处理**：588 报失败时，应回滚 precheck batch（或单独补一条 apply_fixes 写回 `(EMU)`），改 precheck 规则（注释括号收窄，见 references/punct-rules.md）后重跑，verify_fixes 0 失败再结案。

## 回滚说明

apply_fixes --rollback 读 log.jsonl 反向应用 old_text，支持 batch/id/before 三种粒度。global_replace 与 precheck_punct 当前**不单独支持 --rollback**（argparse 未注册），其改动靠：
- `.bak` 文件手动还原（apply_fixes 执行时备份原文件），或
- 若 global_replace/precheck 的 log.jsonl 条目能被 apply_fixes --rollback 认（按 action 字段），则用 apply_fixes --rollback batch=<它们的 batch_id>；需先核 apply_fixes --rollback 是否过滤 action。

未来若给 global_replace/precheck 加 --rollback，复用 lib/log.py 的 read_log + filter_log 反向应用 old_text 即可。
