# 手动流程（M0→M6）

本文件是 subtitle-polish **手动模式**的流程。主 `SKILL.md` 路由到此。

自动模式的审计/验证/人确认门全部跳过。用户已经知道要改什么，主 agent 把口述指令翻译成 fixes.json，然后 dry-run→accept→verify 一气呵成，中间不停等确认（定位错了用 `--rollback` 退，`.bak` 也在）。

## M0. 环境检查

同自动阶段 0：确认 `python` + `pysubs2` 可用。

## M1. 配对

同自动阶段 1。解析 prompt 提取 ass/srt 路径，单文件直接用、多文件同名配对。手动模式通常单文件。

## M2. 接收修改指令

用户在调用里或在后续对话里给出修改指令。**主 agent 必须等用户给出具体指令后再构造 fixes**——若只给了路径没说改什么，停下问"要改哪些行/改什么"。

手动模式不涉及子 agent / 审计 agent。M2 定位、M3 构造、M4 自检全由主 agent 完成，不论文件大小——不引用自动模式的"小文件短路"阈值（那是自动阶段 3 起审计子 agent 的判断，与手动模式无关）。

**多轮迭代时，每轮 M2 开始前重新跑 extract_slice.py**——切片是提取时的快照，上一批 accept 后 ASS 已变，旧切片的"现译"列是过期数据，直接 grep 会导致 dry-run 自检时现译与用户描述不符。第一轮无需重提（ASS 未动）。

指令的常见形态（主 agent 据此理解，不强求用户用固定格式）：

- **定位**：用户可能给 srt 块号、ass 时间戳（`0:01:16`）、英文原文片段、或当前中文片段。主 agent 定位到具体 srt_id + track + Dialogue 行：
  - 给时间戳 → `parse_srt` + `pair` 推 srt_id（时间戳 ±0.5s 容差，同自动配对算法）。
  - 给英文/中文片段 → 在切片文件里 `grep` 搜（切片每行 `<srt_id> | <ass_time> | <英文> | <中文> | <注释>`，grep 能直接看到 srt_id）；也可调 `lib/ass_srt_pair.find_srt_ids_by_text`。两者等价，grep 更直观。
  - 多行命中（片段太短，如"Thank you"对到多行）→ 用 AskUserQuestion 让用户消歧（附上每条命中的 ass_time + 现译），不要猜、不要默认取第一个。
  - **AskUserQuestion 消歧时不要重复已确认的取舍**——若用户已在上一轮 AskUserQuestion 里选了带权衡说明的选项（如"接受口型错位"），下一轮不要就同一问题再问。只问新出现的歧义。
- **改什么**：用户说"把这句中文改成 XXX"、"删掉这行"、"这两行的中文换一下"——映射到 `action ∈ replace | delete | swap`。
- **批量**：用户一次给多条指令 → 全部进同一个 fixes.json。

## M3. 构造 fixes.json

按用户每条指令生成一条 fix，schema 同自动阶段 7（见 `pipeline-spec.md`）：

- `id = audit_id = <shortname>#<srt_id>`（短名从文件名取，如 `e04#16`）。
- `file` / `srt_id` / `track` / `action` / `final_new`（=用户给的译文）/ `srt_path` 显式写。
- **`final_new` 写纯文本，不带 ASS 标签**（如 `{\be3}`、`{\an8}`）。脚本自动保留原 Dialogue 行的前导标签（`extract_leading_tags`），只替换文本部分。不要在 `final_new` 里手写标签。
- `category` 填实际分类（语境错译/语义反转/翻译腔/低严重度等，见 `category-taxonomy.md`），不填笼统的"手动修改"——真实分类利于追溯。`reason` 填用户口述的理由（一句话）。
- 手动模式无"误报/特意/跳过"裁定——用户给的指令就是要执行，`enabled=true`、`status=accepted`。
- 一条指令涉及多个 srt_id 时区分两种情形：
  - **一个整句建议拆到多行**（如"这三行重排成 A/B/C"）→ id 用 `<audit_id>a`/`<audit_id>b`/`<audit_id>c`，audit_id 为父（如 `jm#70a`/`jm#70b`/`jm#70c`，audit_id 均为 `jm#70`）。回滚"这次重排"时按 audit_id 一把退。
  - **多行各自独立改**（三句不相关的话各改各的）→ id 各自 `jm#70`/`jm#71`/`jm#72`，audit_id 各自独立。
  - 判据：用户给的是"一个整句建议拆到多行"还是"多行各自独立改"。拿不准按前者（a/b/c），便于追溯。
  - swap（两行文本互换，不改时间戳）用 swap action + `swap_with`，单独一条 fix。

**落盘**：写到 `.subtitle-polish/fixes.json`（覆盖式，手动模式每批一份新的）。

## M4. dry-run

```bash
python <skill>/scripts/apply_fixes.py .subtitle-polish/fixes.json --dry-run
```

输出 `.subtitle-polish/reports/dry-run.md`。主 agent **读 dry-run.md 自检**，逐条核对三点：

1. **定位**：无 `（定位失败）`，时间戳对得上用户说的那句。
2. **现译**：现译与用户描述的"当前中文"吻合（多轮时尤其要核——上一批改过的行现译应是改后的）。
3. **新译 == 用户建议**：dry-run 里的"新译"必须与用户口述的建议译文**逐字一致**。**工程冲突（时段塞不下、行数与建议字数不配等）不自行拆字/移字/改写新译**——若发现某条新译无法原样落盘（如 1.3 秒时段塞不下 23 字），停下用 AskUserQuestion 把冲突抛回用户（附该行 ass_time + 现译 + 用户建议新译 + 冲突原因，让用户决定拆法/换词/改时长），不自作主张。手动模式的契约是 `final_new = 用户给的译文`，agent 只动手不二次创作。

三点全过 → 进 M5。任一点不过 → 停下告知用户，问清后再走，不盲目 accept。

## M5. accept + verify 连跑

dry-run 自检通过后直接连跑（用户的指令即授权，不再单独问）：

```bash
python <skill>/scripts/apply_fixes.py .subtitle-polish/fixes.json --accept --batch-id <ts>
python <skill>/scripts/verify_fixes.py --batch-id <ts>
```

- accept 写 ASS + 备份 `.bak` + 记 log.jsonl。
- verify 读盘核对每条 new_text 是否真的落盘。输出 `.subtitle-polish/reports/verify-fixes.md`。
- **verify 全过** → 完成，把 dry-run.md + verify-fixes.md 两个路径报给用户，说明改了哪些行（ass_time + 现译→新译）。
- **verify 有失败条目** → 停下，把失败条目（期望/实际/原因/ass_time）报给用户，用 `--rollback batch=<ts>` 退掉这批后排查（定位算法偏差、track 不匹配等），修正 fixes.json 重跑。不自行结案。

## M6. 多轮迭代

用户看完 verify 报告若还要再改，继续给指令 → 主 agent 追加/覆盖 fixes.json → 重跑 M4→M5。每批独立 batch_id，互不干扰，旧批可用 `--rollback batch=<旧id>` 单独退。
