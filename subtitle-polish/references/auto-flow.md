# 自动流程（阶段 0→11）

本文件是 subtitle-polish **自动模式**的流程。主 `SKILL.md` 路由到此。

输入 ASS 双语成品 + SRT 源，走 审计→人确认→修复 全流程。每阶段结束向用户报告进度。**门1（md 报告后）与门2（dry-run 后）停下等用户，不自动推进。**

## 0. 环境检查 + 时间轴闸门

- 系统有 python（默认）。检查 `pysubs2`：`python -c "import pysubs2"`，失败则 `python -m pip install pysubs2`。
- **时间轴闸门（默认拒绝）**：读 `<episode>.ts.json` 凭据，判定这批字幕能不能开工。

  ```bash
  python <skill>/scripts/timeline_gate.py <ass_dir> --media <片源目录或文件>
  ```

  | 退出码 | 含义 | 该怎么办 |
  |---|---|---|
  | 0 | 凭据有效且 PASS | 开工 |
  | 2 | 凭据判定 FAIL | 先 `align_patch` 修轴再复测 |
  | 3 | 无凭据 / 已失效 | 跑 `align_audit --write-credential` |
  | 4 | 多条候选轴无法区分 | 人工确认用的是哪条流 |

  **不给「静默跳过」留路**：文档里写「必须写明未验」是软约束，赶工时一定被跳过；只有退出码非零才会真的停下来。凭据细节见 `timeline-credential.md`。

  没有片源的批次跑不了闸门，此时按 UNVERIFIED 交付（见 11 节），不要把它当成「环境检查通过」。

- **L0 结构哨兵（可选，秒级）**：闸门之前想先看个大概，或手上还没有凭据：

  ```bash
  python <skill>/scripts/precheck_timeline.py <ass_or_dir> --media <片源> --baseline <条数/分>
  ```

  它只查包络越界、尾部缺口、长空洞、密度异常，不加载模型。**PASS 不等于轴对**，只表示没发现结构性错——别拿它代替 2.6。

## 1. 配对

- 多文件：用 `lib/ass_srt_pair.pair_dirs(ass_dir, srt_dir)` 同名配对。
- 单文件：直接用 `pair_files(ass_path, srt_path)`。
- 输出 `[(ass_path, srt_path), ...]` 给用户确认。

## 2. 提取切片

对每对文件跑：
```bash
python <skill>/scripts/extract_slice.py <ass> <srt> --out .subtitle-polish/slices/
```
- 按 srt 块序号切，~700 块/份 + 100 块 overlap。
- 输出 `.subtitle-polish/slices/<stem>_p<n>.txt`，一 block 一行：
  `<srt_id> | <ass_time> | <英文> | <中文> | <注释>`
- 头注列异常标记：ASS_HAS_SRT_NONE / SRT_HAS_ASS_NONE / ONE_TO_MANY / MULTI_SAME_LANG / ASS_TRACK_OVERWRITE

## 2.5. 标点预检

切片提取后、审计前，对成品 ASS 跑标点规范化预检（对照 translate_principle pipeline 的标点规则）：
```bash
python <skill>/scripts/precheck_punct.py <ass_file_or_dir> --out .subtitle-polish
```
- 默认 dry-run，输出 `.subtitle-polish/reports/precheck-punct.md`，列出中文行标点问题（`……`→`…` 残留、中文标点 `，。、`、非数字间英文 `.,`、连续空格、连续横杠、注释括号）。
- **只查中文行**：英文行是源片台词，连续空格/`--` 是口语特征，不检查。
- 这一步**不自动改文件**（默认 dry-run）。标点问题作为**第 7 类候选**喂给审计 agent（审计时若发现 precheck 报的行确实该改，归第 7 类进 optional-fixes）。
- 人若想精校前先统一标点，可在门 1 后单独 `--accept` 跑一次 precheck（独立 batch，可回滚），与主修 fixes 分开。
- **标点规则细节见 `punct-rules.md`；批次顺序（precheck --accept 必须在 apply_fixes 之前）见 `batch-ordering.md`**——顺序错了 precheck 会改掉主修写入的 `……`、删掉主修有意加的 `(EMU)` 译注。

## 2.6. 对齐审计（需片源；无片源则本条判据记为 UNVERIFIED）

标点预检后、审计前。这不是「可选」步骤，是**第三条结案判据的来源**：

| 情形 | 结论 | 能不能结案 |
|---|---|---|
| 跑了，PASS | 轴可信 | 能 |
| 跑了，FAIL | 轴有问题 | 不能，先修 |
| 没跑 / 没片源 | 不知道 | **不能**，只能按 UNVERIFIED 交付 |

没片源不是「跳过」，是「记为 UNVERIFIED」——两者在报告里的分量完全不同，见 `align-audit.md` 的结案节。

```bash
python <skill>/scripts/align_audit.py --sub <ass> --media <mkv|mp4|wav> \
    --report .subtitle-polish/reports/align-<stem>.md \
    --json .subtitle-polish/align/<stem>.json \
    --write-credential --source-index <n> --source-family UK
```

`--write-credential` 写 `<episode>.ts.json`（见 `timeline-credential.md`）。**PASS 和 FAIL 都写**：只写 PASS 的话，FAIL 在闸门眼里会退化成「没有凭据」，「验过不对」和「没验过」又混在一起了。

退出码：PASS 0 / FAIL 2 / UNVERIFIED 3。批处理里直接看退出码，别靠读 stdout。

- 多集就每集各跑一次，汇总成一张表进报告（锚点数 / MAD / 斜率 / 分时段极差 / 判定）。
- 判据是**分时段中位极差**，不是 delta 是否接近 0——delta 天然带 +0.1~0.2s 提前量，绝对值没有意义。
- 阈值按引擎：whisper 0.5s / qwen 0.3s。**whisper 判 FAIL 先换 `--engine qwen` 复核再动手**，0.3~0.5s 区间几乎全是引擎噪声。
- 要改时间轴走 `align_patch.py`（默认 dry-run，自动 `.bak`），不要手改时间戳。
- 想复用已转好的 ASR 结果就存下 `--json`/词级缓存，复测秒出。
- **完整口径见 `align-audit.md`**：为什么不能对字幕流验、轴归属判定、三种修复手段、三个坑。

## 2.7. 三轨预审（可选开关）

标点预检后、审计前，**可选**跑三轨预审（gemini-3.1 + glm-5.2 + 规则检查）给 Claude 子 agent（stage 3）提供总览线索。用户显式 `--pre-audit` 或说"先预审"才跑，默认不开。
```bash
python <skill>/scripts/pre_audit.py <slice.txt> --context .subtitle-polish/context.md --n 5 --out .subtitle-polish/reports
```
- 轨 1 gemini-3.1（5 passes intersection）：快稳，信达雅强。轨 2 glm-5.2（5 passes intersection）：慢但抓语义反转/语境错译。轨 3 check_fluency（规则）：书面语残留对照英文字段来源 / 机翻特征（issue #7：`So`→「所以」这类忠实直译不报）。
- 两 LLM 正交（重叠 <15%），并集才能覆盖全。模型可用性 ping 探测，缺 `GLM_API_KEY` 的轨跳过不崩。
- **输出只是线索，不进 fixes.json / audit-report.md**。专名类标 `needs_web_verify`（GLM 专名建议 100% 编造），字符损坏类丢弃。Claude 子 agent 收到总览须独立判断，不得盲信 LLM 建议。
- **用法/总览字段/安全闸/模型强弱图/带歪风险见 `pre-audit.md`**。

## 3. 审计（自适应起 agent）

- 每文件份数 = `max(1, round(块数/700))`。
- **小文件短路**：单文件块数 ≤ 200 时，主 agent 可直接审计该切片，不必另起子 agent（省成本）。> 200 必须起子 agent。边界明确，不要因"已读完整切片"自行放宽阈值。
- 每份起一个子 agent，prompt 用 `prompts/audit.tmpl`，填入 `{slice_path}`、`{start_block}`、`{end_block}`、`{project_context}`。
- project_context 来源（按优先级）：① 用户 prompt 里写的背景；② `.subtitle-polish/context.md`；③ **两者都没有时，主 agent 读 SRT 前 50 块 + ASS 样式自动合成一段项目背景**（领域、话题、疑似专名列表）。
- 子 agent 后台跑期间，**主 agent 用 grep/正则独立预扫可疑点**（专名不一致、异常字符、ASR 错词模式），子 agent 返回后合并两边发现。
- 子 agent 报告：附 [start_block, end_block] 范围 + 问题列表（srt_id/ass_time/类别/严重度/英文/现译/问题/建议）。
- **prompt 构造约束见 `prompt-injection.md`**：项目背景只放中性领域事实，不放翻译判断结论；预扫发现只供主 agent 合并用，不喂给审计 agent。

## 4. 验证轮1（按类别打包）

- 把同类问题打包给一个验证 agent，prompt 用 `prompts/verify.tmpl`（支持 `{findings}` 列表，多条独立给结论）。
- 输入：每条问题 + 前后各 5 块上下文 + srt 原文。**上下文用 `scripts/build_verify_ctx.py` 构造**（输入 findings.json + 切片文件 + srt，输出 verify_ctx.txt，主 agent 把输出 inline 进 `{findings}` 占位符，不靠 SendMessage 二次喂、不让 verify agent 自己 Read ctx 文件）。
- **adversarial 默认驳回**：只有找不到反驳理由才确认。**prompt 构造见 `prompt-injection.md`**：verify prompt 不放项目背景段（verify.tmpl 本身没有该占位符），主 agent 不得在模板外私加。
- 验证 agent 发现 srt_id 与 srt 原文不符时，输出 `corrected_srt_id`（发现报的 id 错但英文真实存在时）；发现**喂来的上下文块 srt_id 与实际不符**时，输出 `context_error`（结构化字段，描述哪个上下文块 id 错了）。主 agent 见到 `context_error` 必须重读切片构造上下文重跑 verify，不能埋掉。
- 补 agent 触发（绝对阈值，**超过即必须补，不得加软条件跳过**）：某文件验证驳回率 > 40%，或确认问题密度 > 1/100 块 → 补 agent 重看**整个文件**。最多补 2 轮。单文件场景阈值同样适用。详见 `pipeline-spec.md` 补 agent 节。

## 5. 合并报告

- 主 agent 用 `prompts/synthesize.tmpl` 合并，按 (file, srt_id, category) 去重。
- 输出 `.subtitle-polish/reports/audit-report.md`（小节式，按严重度排序）。
- 多文件：每文件一个 `.subtitle-polish/reports/<stem>-detail.md`（不合并到一个文件）。
- 每条格式（**id 用 audit_id；每条带 ass_time 时间戳**）：
  ```
  ### <audit_id> — <类别>（严重度）
  - ass_time: <0:01:16.56-0:01:18.00>
  - 英文: <原文>
  - 现译: <当前中文>
  - 问题: <一句话>
  - 建议: <建议译文>
  ```
- id 空间：统一 `<shortname>#<srt_id>`（如 `e02#152`），单文件也用此格式，不用全局 `1..N`。详见 `pipeline-spec.md`。
- **第 7 类（低严重度）必须单独写** `.subtitle-polish/reports/optional-fixes.md`，**同时**生成 `.subtitle-polish/optional-fixes.json`（同 fixes.json schema，机器读）。不能只出 .md 不出 .json，也不能塞进 audit-report.md 的附注里。audit-report.md 的"未报项说明"只放核验后排除的疑似项（经字节核验 Unicode 正确的疑似错字、经查证确认合法的 ASR 用法），不放第 7 类润色项。详见 `pipeline-spec.md`。
- **第 7 类每条必须在报告里标「改动类型」（issue #4）**，取值：
  - `虚词删除` — 动的是正是/其实/果然/竟然这类虚词或标点/语序，删了语义不变，可顺手批
  - `义项重选` — **动的是实词的意思，这时它不是第 7 类，应升级为第 4 类语境错译进主修**，并附英文原句与上下文
  - `程度微调` — 程度副词方向没反但分量偏

  判据：**这个词是虚词还是实词？删掉之后，原来那个实词的意思还对吗？** 实词删不掉 = 义项问题 = 译错了 = 第 4 类。不确定时默认按第 4 类处理。详见 `fluency-rubric.md`「第 7 类 vs 第 4 类的边界」。
  反例（S06E04 第 6 轮）：「这正是菲尔的强项」→「这就是菲尔的地盘」，只看了虚词「正是」，没判 `bag` 的义项（英式 = 拿手领域），把对的改成错的。

## 6. 人确认门1

- 把 audit-report.md 路径告诉用户，**停下**。
- 用户回复形式："修 <id列表>，<id> 是误报，<id> 特意翻的"。
- **回复自相矛盾时**（如"6 字幕正确"+"修 1-4 和 6"）**不要猜**，用 AskUserQuestion 对矛盾的 id 逐条澄清：accepted / misreport / intentional / skipped。自然语言报 id 列表容易自带矛盾，逐条结构化澄清能从源头消除。
- **用户新指示触及 audit-report 之外的 id 时**（如"查 X 类译名""统一 Y 术语"），联网/查证后**必须回门 1 用 AskUserQuestion 逐条确认**这些 id 的 status（accepted/skipped），不能自行升级进 fixes.json——"查译名"不等于"升级到 main fix"。
- 区分 `status` 字段（fixes.json 里记）：`accepted`（修）、`misreport`（误报，不该报）、`intentional`（特意翻的，译文本就对的）、`skipped`（暂不处理）、`deferred_to_global`（转给 global_replace 处理，本条不执行避免重复改）。所有非 accepted 的都 `enabled=false` 不执行，但 status 记原因。
- 用户也可能直接给意见让重审某条。

## 7. 生成 fixes.json

- 按用户在门 1 对每条发现的裁定生成 `.subtitle-polish/fixes.json`。
- **门 1 涉及的每个 id 都要进 fixes.json**，包括用户标"误报/特意/跳过"的——这些条目 `enabled=false`、`status` 填 `misreport`/`intentional`/`skipped`，不执行但留追溯（否则 fixes.json 与 audit-report 对不上，回滚时也无这些条目的决策记录）。
- 每条：`{id, audit_id, file, srt_id, track, action, suggested_new, final_new, category, reason, enabled, status, srt_path}`
  - `id = audit_id`（多文件用 `<shortname>#<srt_id>`，如 `e02#152`；单文件也用此格式）。fixes.json / dry-run.md / audit-report.md 三处 id 一致，人 review 一眼对上，**不用全局 1..N 序号**。
  - 一条审计发现可拆多条 fix，id 用 `<audit_id><suffix>`（如 `e02#152a`/`e02#152b`），audit_id 为父。
  - `final_new` 缺省 = `suggested_new`；用户改过则覆盖。
  - `enabled=true` 仅给 status=accepted 的；其余 `enabled=false`。
  - `action` ∈ replace | delete | swap | insert（swap 换文本不换时间戳，附 `swap_with`；insert 新增一行如注释轨，样式按 track 自动解析）。
  - `srt_path` 显式写，避免脚本找不到配对 srt。
- id 空间与 status 取值详见 `pipeline-spec.md`。
- 第 7 类进 `.subtitle-polish/optional-fixes.json`，默认不并入主修。

## 8. 脚本 dry-run

```bash
python <skill>/scripts/apply_fixes.py .subtitle-polish/fixes.json --dry-run
```
- 输出 `.subtitle-polish/reports/dry-run.md`（每条 audit_id/ass_time/srt_id/现译→新译/类别，现译与新译都显示含标签的真实文本，带时间戳方便人对照视频）。

## 9. 人确认门2

- 把 dry-run.md 路径告诉用户，**停下**。
- 用户显式 accept 后才执行。**门1的"修 1-5"只授权生成 fixes.json 和跑 dry-run，不等于门2通过**。除非用户在门1明确说"全修并直接执行"（合并语义），否则必须等门2独立确认。
- 用 AskUserQuestion 让用户选译文时，**选项 label 必须唯一**；省略号统一全角 `……` 或半角 `…`，不要混用（视觉差异极小易被当重复，上一轮实测因此触发校验报错要重试）。

## 10. 执行

```bash
python <skill>/scripts/apply_fixes.py .subtitle-polish/fixes.json --accept --batch-id <ts>
```
- 按 srt_id + track 定位（srt_id→timestamp→ass Dialogue）。
- 每条写 `.subtitle-polish/log.jsonl`（ts/batch_id/action/file/srt_id/track/old_text/new_text/category/reason）。
- 备份原文件为 `.bak`。
- **批次顺序见 `batch-ordering.md`**：precheck --accept 必须在 apply_fixes 之前；global_replace 可在主修前或后。

## 11. 执行后验证

结案条件是**三条都满足**：`verify_fixes` 0 失败 **AND** `cross_check` 中英对照复核通过 **AND** `align_audit` 极差在阈值内。
第一条证明「改的东西写进去了」，第二条证明「写进去的是这一句该有的译文」，第三条证明「它出现在对的时间」。只跑第一条不算验完，前两条都不读时间字段。

```bash
python <skill>/scripts/verify_fixes.py --batch-id <ts>
python <skill>/scripts/cross_check.py   --batch-id <ts>
python <skill>/scripts/align_audit.py   --sub <ass> --media <片源>   # 有片源时必跑
```

第三条缺片源时跑不了，**结案结论必须是 UNVERIFIED，不能写「通过」**。报告里不许出现「全部通过」「验证完毕」这类措辞。**不要用「对本片内嵌字幕流」代替**——实测 8 集里有 3 集的内嵌流自己就偏 2.4~2.9 秒，拿它当基准等于自证。

写结论前先跑闸门，它读凭据、不跑模型，毫秒级：

```bash
python <skill>/scripts/timeline_gate.py <ass_or_dir> --media <片源>
# 0 PASS / 2 FAIL / 3 UNVERIFIED / 4 AMBIGUOUS
```

凭据失效（片源换了、文件被改过、改过时间轴没复测）同样判 UNVERIFIED——过期的 PASS 不是 PASS。

- 读 log.jsonl，按 srt_id + track 用 ass_srt_pair 重读 ASS，逐条核对每条操作记录的 new_text 是否真的落盘（delete 验该行已不存在）。输出带 ass_time 方便人对照视频。
- 输出 `.subtitle-polish/reports/verify-fixes.md`。有失败条目则列出期望/实际/原因/ass_time，agent 或人据此排查。
- **失败时不得用"预期差异"自行结案**，见 `batch-ordering.md`——每条必须读盘核对、分类（标点差异/译注被删/文本不符）、回滚或修复至 0 失败。真损失（如 `(EMU)` 被删）必须补回。
- 不依赖 agent 手写 pysubs2 脚本或硬编码时间戳——上一轮实测手写验证因时间戳算错 5/6 条 NOT FOUND，改为脚本兜底。
- 用户对仍存疑条目可再起验证 agent（用 verify.tmpl）复查语义，但落盘核验走本脚本。

### 11b. 中英对照复核（必做，不可跳过）

> **`verify_fixes` 0 失败 ≠ 成品正确。** 它比对的是「盘面 == log 里的 new_text」，
> 是恒等式：只要字写进去就必然通过，**与译文对不对毫无关系**。
> 实测：一轮 99 条 fix，verify 报 104 通过 / 0 失败，其中 15 条把原本正确的
> 译文换成了邻行的/同场景另一句的译文。详见 skill-forge issue #1。

因此 verify 通过后**必须再跑一次以英文为锚的对照**：

```bash
python <skill>/scripts/cross_check.py --batch-id <ts>
```

- 输出 `.subtitle-polish/reports/cross-check.md`：本批每个改动块的「英文 / 中文 / 本批改动」，外加**撞车预警表**。
- 撞车预警 = 新译文与本块 ±3 邻块现有中文的相似度 ≥ 0.55（`difflib` 纯字符串，无模型）。
  实测该判据：坏条命中 4/15，好条误报 **0/84**——误报率为 0，所以**每条预警都必须人工看**，不能当噪声忽略。
- 预警只是提示，**不是结论**。剩下的错位（11/15）不是抄邻块，而是换成同场景另一句话，
  任何字符串判据都抓不到。所以复核的正确姿势是：**读 cross-check.md 里每一块的英文与中文，问一句「如果我是译者，看了这句英文会写出这句中文吗」**。
- 复查时必须按 srt_id 对齐，**不要用「这行像不像上一行的译文」判断**——连续对白里相邻块语义相关是正常的，这正是上一轮误判的根源。
- 复核结果写进报告，明确说明「本次验证覆盖范围」（落了盘 + 中英对照抽检了哪些块），不要让「N 通过」被当成「全文正确」。

### 11c. 误判自我强化的防治

错位一旦写进盘面，下一轮审计 agent 会**基于坏盘面**把「恢复成错的那句」当成建议报上来，误判自我强化。

**每轮开工前先读台账**（skill-forge issue #5 #6）：

```bash
python <skill>/scripts/regression_check.py --ledger --conflicts --window 3
```

输出 `.subtitle-polish/reports/regression.md`，三样东西：

- **台账**：近 3 轮哪些行被改过、改成什么、当时的理由。**整段贴进审计 prompt**，
  要求「若判为错误，必须说明当时那条理由错在哪」——否则 agent 会把上一轮刚做的决定当新发现重报一遍。
- **连续改动**：同一行被 ≥2 轮改过。
- **批次沉住度**：每一轮改的行里，后来又被改过的比例。比例高 = 那批判断被推翻得多。
  实测 S06E04：r7 那轮 3 条全部被后续推翻（100%），r10 的 40 条只有 1 条被推翻（2%）。

> **报告里没有「已收敛」这一项，这是故意的。** log 只记改动、不记「看过了、同意」——
> 一致是不留痕的，所以「已经收敛」不可观测。「连续两轮给出相同 new_text」这个判据在
> 一致的日志里永远为假：相邻两条满足 `old[i] == new[i-1]`，若再有 `new[i] == new[i-1]`，
> 则 `old[i] == new[i]`，那是一条空改动。能观测的是反面——改完之后又被人动了。
- **疑似反向**：新一轮的文本与**更早那版**的相似度高于与上一版的（`difflib` ≥0.85 且领先 0.15）。
  这是确定性判据，不是语义判断——**翻回去有时是对的**，上一轮确实可能改错了。

真实案例（issue #6，S06E04 的 #343）：

```
R6 这正是菲尔的强项 → 这就是菲尔的地盘     （只看虚词「正是」，没判 bag 的义项）
R7 这就是菲尔的地盘 → 这正是菲尔的强项     （改回来）
R8 这正是菲尔的强项 → 这就是菲尔的地盘     （又改回去）
```

三轮 `verify_fixes` 都是 0 失败、`cross_check` 都是 0 预警——**没有任何一条判据发现了这个来回**，
因为每条判据都只看「当前盘面」，没有「上一轮改过什么」这个事实。
现在 `cross_check` 会附带一张「动到了历史刚定下的内容」表，只报不阻断：

> 这些行的**当前内容**是第 X 轮刚定下的，本轮把它改掉了。改不一定错，但先看第 X 轮为什么那么定。

`--regression-window` **默认 0 = 全部历史**。不是 3——S06E04 里 r15 推翻的是 r7 的结论，
隔了 8 轮，窗口取 3 完全看不见（实测：窗口 3 → 0 条，全历史 → 1 条，命中的正是 r7）。
要关掉用负数。

还有一条卡死的口径：**只比更早的批次**。按「不在当前批次里」筛会把未来批次拉进来，
报告于是写出「第 X 轮 = r11」，而 r11 在 r10 之后——因果倒置。真实数据上就是这么错的。

其余仍需人做的事：

- 重跑审计前，先确认上一轮 verify + 对照复核都过了；不过就回滚，不要把坏状态当基线。
- 每轮开始前**保留一份快照**（如 `.subtitle-polish/<run>/S06E04.eng.ass.before.bak`），与执行后做 diff；
  差异里出现「中文行内容等于其邻块内容」的，直接判为回归。
- 报告里写明本轮相对快照改了多少行（中文/英文各几行），便于下一轮比对。


## 全局替换（跨文件统一专名）

审计后若发现专名不一致（如 维多利亚皇冠 9 处应统一为 皇冠维多利亚）：
```bash
python <skill>/scripts/global_replace.py <pattern> <replacement> --track 中文 --files <glob> --dry-run
python <skill>/scripts/global_replace.py <pattern> <replacement> --track 中文 --files <glob> --accept
```
默认只改中文行，`--track 英文` 改英文行。**纯文本替换走 global_replace；每行需语境调整的（补字、换词性）走 fixes.json 逐条 replace**——global_replace 做不到每行微调。定位"某术语在哪些 srt_id 出现"用 `lib/ass_srt_pair.find_srt_ids_by_text`，不要手写 timestamp 匹配脚本。
