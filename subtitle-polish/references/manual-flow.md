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

```bash
python <skill>/scripts/extract_slice.py <ass> <srt> --out .subtitle-polish/slices/
```

参数是 `--out`（输出目录），不是 `--outdir`。

### 指令形态

指令的常见形态（主 agent 据此理解，不强求用户用固定格式）：

- **定位**：用户可能给 srt 块号、ass 时间戳（`0:01:16`）、英文原文片段、或当前中文片段。主 agent 定位到具体 srt_id + track + Dialogue 行：
  - 给时间戳 → `parse_srt` + `pair` 推 srt_id（时间戳 ±0.5s 容差，同自动配对算法）。
  - 给英文/中文片段 → 在切片文件里 `grep` 搜（切片每行 `<srt_id> | <ass_time> | <英文> | <中文> | <注释>`，grep 能直接看到 srt_id）；也可调 `lib/ass_srt_pair.find_srt_ids_by_text`。两者等价，grep 更直观。
  - 多行命中（片段太短，如"Thank you"对到多行）→ 用 AskUserQuestion 让用户消歧（附上每条命中的 ass_time + 现译），不要猜、不要默认取第一个。
  - **AskUserQuestion 消歧时不要重复已确认的取舍**——若用户已在上一轮 AskUserQuestion 里选了带权衡说明的选项（如"接受口型错位"），下一轮不要就同一问题再问。只问新出现的歧义。
  - **AskUserQuestion 选项要命中用户意图**——若用户拒绝了所有选项要求澄清（实测第 514 行用户拒绝 3 选项），不要重提同类选项，**直接用开放式问题问"你想要什么结果"**。提的选项都miss说明主 agent 对用户意图建模错了，再提同类还是 miss。
- **改什么**：用户说"把这句中文改成 XXX"、"删掉这行"、"这两行的中文换一下"——映射到 `action ∈ replace | delete | swap | insert`。
  - `replace` 改某行文本；`delete` 删整行；`swap` 两行文本互换（不换时间戳）。
  - `insert` 新增一行，典型场景是给某个 srt 时段加注释轨（`track=注释`）。`final_new` 写注释正文（纯文本不带 ASS 标签，同 replace 规则），挂在 `srt_id` 对应时段。样式由脚本按 track 从 ASS `[V4+ Styles]` 自动解析（找 `style_to_track(name)==track` 的样式名）；**ASS 无对应样式则脚本报错停下，不自动建样式**——用户需先在 ASS 里定义好 `注释` 等样式。`id`/`audit_id` 空间同 replace（`<shortname>#<srt_id>`）。
- **批量**：用户一次给多条指令 → 全部进同一个 fixes.json。

### 括注 / 表演提示 / 译注：不混进字幕正文

用户口述里常带括注（`（触电痛呼）`、`(EMU)`、`(机务段)`、`（旁白）`）——这些是表演提示或译注，**不该混进 `replace` 的 `final_new` 落到主字幕区**。主字幕区（`中文` 样式，底屏）只放给观众看的台词正文；括注混进去会带括号显示在底部。

主 agent 收到带括注的指令时，**先问用户**走哪种：

1. **剥除**（默认推荐）：`final_new` 只留台词正文，括注丢弃。例：`这是按摩模式，啊！`（去掉 `（触电痛呼）`）。
2. **走 insert 加注释轨**：`final_new` 写台词正文，**另起一条 fix**（`action=insert`、`track=注释`、`final_new=触电痛呼`），挂在同一 srt_id 时段。要求 ASS 已定义 `注释` 样式（`\an8` 顶屏）。两条 fix 共享 audit_id，用 a/b 后缀区分。
3. **保留在正文**（用户明确要）：才把括注写进 `final_new`，但要在 dry-run 自检时主动告知用户"括注会显示在底部主字幕区"。

判据：括注是给观众看的（译注，如 `(EMU)` 解释缩写）→ 走注释轨 insert；是表演提示（如 `(触电痛呼)` 描述动作）→ 剥除或走注释轨。**不要默认混进正文**。

### ASR 听写错误的英文源

用户纠正的 ASR 错误（如 `big closet`→`big chested`、`fifth toe`→`fat arse`、`A!`→`Ah!`、`He has hardness`→`It gets hard`、`sips`→`bobbles`）是"英文源本身错、中文译文跟着错"的场景。skill 默认只改中文轨（`track=中文`），**英文轨和 SRT 源不动**——SRT 在本 skill 里是权威英文源，改它意味着推翻源；英文轨改不改是另一次决定。

主 agent 必须**主动告知用户**这个边界，并询问是否另开一批改 ASS 英文轨：

- 默认主修只改 `track=中文`。fixes.json 里每条 `track=中文`。
- 用户若要同步改英文轨 → 另开一批，fixes.json 里 `track=英文`，同 srt_id 定位英文行。`final_new` 写正确的英文台词。
- SRT 源**不改动**（skill 不写 SRT）。若用户要改 SRT，自行用编辑器改，skill 不介入。

**ASR 错误的最终责任在用户**——skill 不做音频核对，无法验证"原话到底是哪个词"。用户给的纠正就是权威，主 agent 不要凭语音相似度反驳用户判断（如"fifth toe 与 fat arse 语音差很远"这种保留意见可以提，但最终按用户说的写）。

### 同源连环误译的扩展

用户给的指令若触及一个连环误译案（如"毛球链"涉及 srt 310/312/313/317/321/322），主 agent **定位阶段主动 grep 同义词链 / 同 ASR 错误源**，找出该连环案里所有相关 srt_id，用 AskUserQuestion 问用户"这条连环案里还有 N 行没在你的指令里，要一并修吗"。不要只改用户明说的那几行，留下连环案半截。

判据：用户给的指令里出现"X 译法应统一为 Y"或"X 是 ASR 听错，应为 Z"——主 agent grep 整个切片找含 X（或其变体）的行，列出来让用户确认是否一并改。

### 一句拆多行的默认规则

用户给的一整句建议要拆到多个 srt 块时（如 srt 375-378 总结句拆 4 行），主 agent 用 AskUserQuestion 问拆法，但**给默认推荐选项**减少用户负担：

1. **按英文断句拆**（默认推荐）：以英文原文的标点/从句为切分点，每行对应一个语义片段。
2. **按时长均分**：按各 srt 块时长比例分配字数，避免某行塞不下。
3. **用户自定义**：用户自己指定每行内容。

拆条后 id 用 `<audit_id>a`/`<audit_id>b`/`<audit_id>c`...，共享 audit_id 为父。回滚"这次重排"按 audit_id 一把退。

### 时长容量校验

主 agent 在 M3 构造 fixes 时，对每条 `replace` 算一下 `final_new` 字数 vs srt 块时长（CPS，字符/秒）。中文行合理上限约 8-12 字/秒（字幕行业惯例 15 字/秒封顶，留余量）。

- **超长**（如 0.9 秒塞 11 字 = 12.2 CPS）：**不要自行拆字/移字/改写新译**（违反"final_new = 用户给的译文"契约）。停下用 AskUserQuestion 把冲突抛回用户，附该行 ass_time + 现译 + 用户建议新译 + 冲突原因（CPS 超限），让用户决定拆法/换词/改时长。
- **临界**（10-12 CPS）：可以接受但要在 dry-run 自检时提一句"该行较满，注意口型"。

### 兜底：脚本定位不到时允许 Edit

`_find_dialogue` 取最近时间戳匹配，但相邻 srt 块时间差 < 0.5s 时仍可能撞同一物理行（dry-run 会报"撞车预警"）。这种情况脚本分不开两条 fix，主 agent 允许**破例 Edit ASS**，但必须：

1. **dry-run 先报撞车**：apply_fixes.py 的 dry-run 会输出"撞车预警"，主 agent 看到后**先尝试拆开**（合一条 fix 用 a/b 后缀、改 insert 注释轨、或调时间戳）。拆不开才走 Edit。
2. **Edit 后用脚本补记 log**：用 `apply_fixes.py --manual-log` 子命令补记一条 `action=manual_edit` 的日志，不要手写 JSON 追加（实测手写 JSON 易错、且 Write 覆盖 log.jsonl 会被拒）：
   ```bash
   python <skill>/scripts/apply_fixes.py --manual-log \
       --file <ass> --srt-id <id> --track 中文 \
       --old "原文本" --new "新文本" \
       --category "语境错译" --reason "撞车兜底,用户确认破例 Edit" \
       --batch-id <ts>_manual
   ```
3. **verify 兜底**：`verify_fixes.py --batch-id <ts>_manual` 验 manual_edit 条目（按 new_text fallback 定位核对）。
4. **回滚**：`--rollback batch=<ts>_manual` 同样支持。

规约"修复手段都只调脚本"在撞车场景下有这条例外条款。**首选仍是脚本**，Edit 是 last resort。

## M3. 构造 fixes.json

按用户每条指令生成一条 fix，schema 同自动阶段 7（见 `pipeline-spec.md`）：

- `id = audit_id = <shortname>#<srt_id>`（短名从文件名取，如 `e04#16`）。
- `file` / `srt_id` / `track` / `action` / `final_new`（=用户给的译文）/ `srt_path` 显式写。
- **`final_new` 写纯文本，不带 ASS 标签**（如 `{\be3}`、`{\an8}`）。脚本自动保留原 Dialogue 行的前导标签（`extract_leading_tags`），只替换文本部分。不要在 `final_new` 里手写标签。
- **`final_new` 不带括注**（`（触电痛呼）`、`(EMU)` 这类）——括注走剥除或另起 insert 加注释轨，见 M2「括注 / 表演提示 / 译注」节。
- `category` 填实际分类（语境错译/语义反转/翻译腔/低严重度等，见 `category-taxonomy.md`），不填笼统的"手动修改"——真实分类利于追溯。`reason` 填用户口述的理由（一句话）。
- 手动模式无"误报/特意/跳过"裁定——用户给的指令就是要执行，`enabled=true`、`status=accepted`。
- 一条指令涉及多个 srt_id 时区分两种情形：
  - **一个整句建议拆到多行**（如"这三行重排成 A/B/C"）→ id 用 `<audit_id>a`/`<audit_id>b`/`<audit_id>c`，audit_id 为父（如 `jm#70a`/`jm#70b`/`jm#70c`，audit_id 均为 `jm#70`）。回滚"这次重排"时按 audit_id 一把退。
  - **多行各自独立改**（三句不相关的话各改各的）→ id 各自 `jm#70`/`jm#71`/`jm#72`，audit_id 各自独立。
  - 判据：用户给的是"一个整句建议拆到多行"还是"多行各自独立改"。拿不准按前者（a/b/c），便于追溯。
  - swap（两行文本互换，不改时间戳）用 swap action + `swap_with`，单独一条 fix。
  - insert（新增行，如注释轨）用 insert action，无现译行可继承标签，`final_new` 就是落盘文本。一条 fix 对应一行。

**落盘**：写到 `.subtitle-polish/fixes.json`（覆盖式，手动模式每批一份新的）。

**撞车预警**：apply_fixes --dry-run 会检测同 batch 内是否有多条 fix 写到同一物理 ASS 行（srt_id 时间戳过近，`_find_dialogue` 取最近也分不开）。看到"撞车预警"必须先拆开 fixes（合一条用 a/b 后缀、改 insert 注释轨、或调时间戳），拆不开才走 M2 兜底节里的 Edit。

## M4. dry-run

```bash
python <skill>/scripts/apply_fixes.py .subtitle-polish/fixes.json --dry-run
```

输出 `.subtitle-polish/reports/dry-run.md`。主 agent **读 dry-run.md 自检**，逐条核对：

1. **定位**：无 `（定位失败）`，时间戳对得上用户说的那句。**insert 特例**：insert 无现译行，ass_time 从 srt 块取，"定位"= srt_id 时段可解即可，不要求有现译行。
2. **现译**：现译与用户描述的"当前中文"吻合（多轮时尤其要核——上一批改过的行现译应是改后的）。**insert 无此点**（新行无现译）。
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
