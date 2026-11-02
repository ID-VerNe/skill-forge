---
name: subtitle-polish
version: 1.13.0
description: 字幕精校,支持手动/对轴/自动审校三种模式。用户说"精校字幕"、"字幕审计"、"修字幕"时触发。手动模式:用户直接给修改指令,主 agent 翻译成 fixes.json 后 dry-run→accept→verify 一气呵成。对轴模式:拿片源对齐时间轴(align_audit/align_patch/align_audit --compare)。自动审校模式:输入 ASS 双语成品 + SRT 源,按 10(默认)或 11 轮疗程逐轮审计修复,每轮一个 batch_id、快照可整轮回滚;加 --auto 走无监管自动跑完并出总账。**审计判断一律由并行 subagent 通读全文后自己做,脚本(scan_seed/scan_inclusive)只出定位线索、不当判据**;修复由脚本执行(dry-run/accept/rollback)。也支持 /subtitle-polish 命令。
---

# subtitle-polish 字幕精校 Skill

本 skill 有**三种模式**,由用户调用时的措辞决定(见下「模式选择」)。三种模式共享同一套脚本与 `.subtitle-polish/` 工作目录。**修复手段都只调脚本,不直接 Edit ASS。**

- **手动模式**:用户直接口述要改什么(如"把 0:01:16 的中文改成 XXX"),主 agent 翻译成 fixes.json 后 dry-run→accept→verify 一气呵成。流程 M0→M6,见 `references/manual-flow.md`。
- **对轴模式**:用户给片源,要建/修时间轴,或判「这条字幕跟音频对不对得上」。不走文本审计。流程 A0→A5,见 `references/align-flow.md`(骨架,先读)+ `references/build-timeline.md`(判轴优先)+ `references/align-audit.md`(判据与手段)。
- **自动审校模式**:输入 ASS 双语成品 + SRT 源,按轮次疗程逐轮审计修复。一轮内部的阶段 0→11 见 `references/auto-flow.md`;**多轮之间怎么排、怎么记账、怎么回滚**见 `references/rounds-spec.md`。

**模式是一个轴,监管是另一个轴。** 「跑几轮」和「每道门停不停」互相独立:
自动审校模式 × 逐步(默认,门 1/门 2 每轮停)与自动审校模式 × 无监管(`--auto`,11 轮一次跑完、最后出总账)
是**同一个流程的两个开关**,不是两种新模式。详见 `references/rounds-spec.md` 开头表。

## 适用范围

- 输入:ASS 双语成品(英文行 + 中文行成对,track 取值 `英文/中文/注释`)+ SRT 源(权威英文)
- **时间轴契约**:输入字幕的时间轴**必须可信,且必须能证明**。证明形式是 `<episode>.ts.json` 凭据,
  由 `align_audit --write-credential` 产出,由 `timeline_gate.py` 在阶段 0 校验。
  没有凭据 = 没验 = 不许按「通过」结案。详见 `references/timeline-credential.md`
- 可选:片源(MKV/MP4 或已抽好的 wav)。给了才能验时间轴,详见 `references/align-audit.md`
- **翻译前的第 0 步**:若手上只有片源,先用 `extract_subs.py` 抽内嵌字幕流 + `align_audit --compare` 判轴,
  拿到一条与音频同轴的英文 SRT 再开工。时间轴应在翻译前建立,不是交付前抢救——见 `references/build-timeline.md`
- 不适用:无 SRT 源(拒绝运行)、VTT/单语成品、SRT 双语(不处理)
- 修复手段:文本改走 extract_slice / apply_fixes / global_replace,时间改走 align_patch,
  **不直接 Edit ASS**

## 调用约定

```
/subtitle-polish <mode_keyword>:<ass_dir_or_file> 其对应的srt是 <srt_dir_or_file>
```

`<mode_keyword>` 可选,用关键词表明模式:

- `精校` / `自动` / `审计` → **自动审校模式**(如"精校:C:\xxx 其对应的srt是 C:\yyy")
- `手动修` / `改` / `手动` → **手动模式**(如"手动修:C:\xxx.ass 其对应的srt是 C:\xxx.srt")
- `对轴` / `打轴` / `对齐` / `测轴` → **对轴模式**(如"对轴:C:\xxx.ass 片源是 C:\xxx.mkv")

ass 与 srt 可以是目录或单文件:
- 多文件:默认同名配对(去扩展名 stem 相等),`--strip-suffix` 去指定后缀
- 单文件:用户给详细地址,直接用

可选项目背景写在 prompt 里(如"这是汽车节目,注意底盘术语"),或放项目根 `.subtitle-polish/context.md`。

## 模式选择(路由)

技能激活后:

1. **先判有没有具体修改指令,再判模式**。优先级从高到低:

   | 用户措辞长什么样 | 走哪 | 理由 |
   |---|---|---|
   | **点名了要改成什么**(如"把 0:01:16 改成 XXX"、"第 12 行译错了"、"处女航改成首航") | **手动模式**,即使同时出现 `精校`/`审计` 字样 | 人已经把判据给出来了,再跑审计轮只会把这条指令淹没在几十条建议里 |
   | 含 `对轴`/`打轴`/`对齐`/`测轴`,或给了片源且明说要看时间轴 | 对轴模式 | — |
   | 含 `手动修`/`改`/`手动` | 手动模式 | — |
   | 含 `精校`/`自动`/`审计` | 自动审校模式 | — |
   | 都没命中 | 自动审校模式(默认) | — |

2. **解析 prompt**:提取 ass 路径、srt 路径、片源路径、可选项目背景。
3. **校验**:自动审校模式与手动模式若无 srt 路径 → 停下,告知"需要 SRT 源才能跑"。手动模式下若无具体修改指令 → 停下,告知"手动模式需要你告诉我要改什么"。对轴模式若无片源 → 停下,告知"对轴必须有片源"。
4. **按模式读对应 reference 再动手**,不要凭记忆执行:
   - 手动 → `references/manual-flow.md`(M0→M6)
   - 对轴 → `references/align-flow.md`(A0→A5 骨架) + `references/build-timeline.md`(判轴优先) + `references/align-audit.md`(判据/引擎/修复手段)
   - 自动审校 → `references/auto-flow.md`(一轮 0→11)+ `references/rounds-spec.md`(多轮编排)
5. **门的处置按监管轴分叉**:
   - **逐步(默认)**:自动审校模式每轮在门 1(audit 报告后)与门 2(dry-run 后)**停下等用户**;手动模式 M4 dry-run 自检通过后 accept+verify 连跑不停。
   - **无监管(`--auto`)**:自动审校模式 R1→R11 一次跑完,中途不停,最后出 `final-report.md` 交人逐条否决。仅自动审校模式支持。

### 自动审校模式的三个开关

| 开关 | 作用 | 默认 |
|---|---|---|
| (无) | R1–R8 + R10,共 **9 轮** | ✅ |
| `--with-low` | 追加 R9(第 7 类低严重度) | 关 |
| `--with-inclusive` | 追加 R11(第 8 类中立与合规:性别/宗教/政治/法律四子域) | 关 |
| `--with-spelling` | 把第 6 类**并入** R1–R3 与 R10 | 关 |
| `--auto` | 无监管:不停门,跑完出总账 | 关 |

全开 = R1–R11 共 11 轮。**默认不跑第 6/7/8 类是设计决定,不是遗漏**——`final-report.md`
强制有「本次未覆盖」一节把它写出来。

**类别专轮一律全量出片,不切片取样。** token 不是本项目的稀缺资源,精确才是目标。
详见 `references/rounds-spec.md` §2,这条是硬约束。

## 回滚(三种模式共用)

```bash
# 按整 batch
python <skill>/scripts/apply_fixes.py --rollback batch=<batch_id>
# 按单条
python <skill>/scripts/apply_fixes.py --rollback id=<srt_id> --file <ass_path>
# 按时间点(回滚该时间之前所有)
python <skill>/scripts/apply_fixes.py --rollback before=<ts>
# 按轮次(自动审校模式专用,整文件快照还原,ASS 与 log 一起还原)
python <skill>/scripts/round_orchestrator.py --run <stamp> --rollback-to r03
```

所有操作都留 log.jsonl 记录,支持单条/整 batch/时间点三种粒度回滚。**global_replace 与 precheck_punct 当前不单独支持 `--rollback`**(argparse 未注册),其改动靠 `.bak` 文件手动还原,或用 `apply_fixes.py --rollback batch=<它们的 batch_id>`(若该 action 被认)。详见 `references/pipeline-spec.md` 回滚节与 `references/batch-ordering.md`。

**多轮叠加后不要用 `--rollback batch=` 逐轮往回退**:会撞上 retime 浮点残差、delete 无法重建、
global_replace 交叉三个限制。回退轮次用 `round_orchestrator.py --rollback-to rNN`,
它是整字节快照。详见 `references/rounds-spec.md` §5.3。

## 破例 Edit 兜底(三种模式共用)

脚本 `_find_dialogue` 在相邻 srt 块时间差 < 0.5s 时取最近也分不开(dry-run 会报"撞车预警")。撞车场景下允许破例 Edit ASS,但必须用脚本补记 log:

```bash
python <skill>/scripts/apply_fixes.py --manual-log \
    --file <ass> --srt-id <id> --track 中文 \
    --old "原文本" --new "新文本" \
    --category "语境错译" --reason "撞车兜底" \
    --batch-id <ts>_manual
python <skill>/scripts/verify_fixes.py --batch-id <ts>_manual  # 验 manual_edit
python <skill>/scripts/apply_fixes.py --rollback batch=<ts>_manual  # 回滚
```
首选仍是脚本,Edit 是 last resort。详见 `references/manual-flow.md` 兜底节。

## 结案条件(三种模式共用)

```bash
python <skill>/scripts/verify_fixes.py --batch-id <ts>   # 盘面 == log
python <skill>/scripts/cross_check.py   --batch-id <ts>  # 中英对照复核
python <skill>/scripts/align_audit.py   --sub <ass> --media <片源> --write-credential  # 对音频对齐
python <skill>/scripts/align_audit.py   --sub <ass> --media <片源> --engine qwen \
       --model <qwen3-aligner 目录>    # 精测(分块按显存自动选,不要手写 240)
python <skill>/scripts/timeline_gate.py <ass> --media <片源>        # 凭据闸门(毫秒级)
```

三条判据的结论只有四态:**PASS(0) / FAIL(2) / UNVERIFIED(3) / AMBIGUOUS(4)**。`UNVERIFIED` 不是「通过」,
是「没验」——报告里不许写成「全部通过」。

**`verify_fixes` 0 失败不等于成品正确。** 它比的是「盘面 == log 里的 new_text」,
是恒等式:只要字写进去就必然通过,与译文对不对无关。实测一轮 99 条修复 verify 报
0 失败,其中 15 条把原本正确的译文换成了邻行/同场景另一句的译文(skill-forge issue #1)。

所以结案条件是:

- `verify_fixes` 0 失败 —— 证明「改了的东西确实写进去了」;
- `cross_check` 中英对照逐块读过 —— 证明「写进去的是这一句该有的译文」;
- `align_audit` 分时段中位极差在阈值内 —— 证明「写进去的东西出现在对的时间」。

前两条都不读时间字段,**文本全对、时间轴整集偏 2.9 秒的成品照样全绿**(skill-forge issue #8)。
第三条也不能用「对本片内嵌字幕流」代替——内嵌流自己可能就错轴。详见 `references/align-audit.md`。

无片源时第三条跑不了,但必须在报告里写明「本次未验时间轴」,不能默认它是对的。

`cross_check` 会输出撞车预警(新译文 ≈ ±3 邻块现有中文)。误报率实测为 0,
**每条预警都要人看**;但它召回只有 4/15(其余是「同场景换句」「缩译掩盖漏译」,
字符串判据抓不到),所以预警表干净**不能**当作全文正确。详见 `references/auto-flow.md` 11b 节。

另外两条判据都只看**当前盘面**,没有「这一行上一轮刚被改过」这个事实。于是同一行
可能被连续几轮来回改,而每轮 verify 0 失败、cross_check 0 预警——**没有任何信号
能发现这个来回**(skill-forge issue #5 #6)。所以**每轮动工前**先读台账:

```bash
python <skill>/scripts/regression_check.py --ledger --conflicts --no-reason
```

台账整段贴进审计 prompt,并要求「判为错误时须说明当时那条理由错在哪」。
详见 `references/auto-flow.md` 11c 节。

## 文件结构

```
<skill>/
├── SKILL.md                    # 本文件,路由
├── references/
│   ├── auto-flow.md            # 自动审校:一轮内部阶段 0→11
│   ├── rounds-spec.md          # 自动审校:多轮编排/六道闸/定格/快照/最终报告
│   ├── manual-flow.md          # 手动流程 M0→M6（含括注/ASR/兜底节）
│   ├── align-flow.md           # 对轴流程 A0→A5（骨架，先读这个）
│   ├── pipeline-spec.md        # 数据流/fixes.json schema/log/回滚规范
│   ├── batch-ordering.md       # 脚本批次顺序与 verify 失败处理
│   ├── category-taxonomy.md    # 8 类分类法
│   ├── inclusive-language.md   # 第 8 类(中立与合规)A/B/C/D 四子域 × L1-L4;清单是起点不是判据
│   ├── subagent-delegation.md  # 谁来做判断:脚本定位 vs LLM 审计的分工、切片切分、失效模式
│   ├── glossary-handling.md    # 不带术语表原则
│   ├── punct-rules.md          # 标点规则细节
│   ├── pre-audit.md            # 三轨预审用法
│   ├── align-audit.md          # 对音频的时间轴审计与修复
│   ├── timeline-credential.md  # 时间轴凭据(sidecar)与阶段 0 闸门
│   ├── build-timeline.md       # 翻译前先从片源建立可信时间轴
│   ├── pitfalls.md             # 踩坑清单:厘秒精度/track 中文串/bash 吃反斜杠/大文件分片/结构先于语义
│   └── prompt-injection.md     # prompt 构造约束
├── prompts/                    # audit/verify/synthesize 模板
└── scripts/                    # extract_slice / apply_fixes / global_replace
                                #   / verify_fixes / cross_check / regression_check
                                #   / precheck_punct / pre_audit
                                #   / extract_subs / align_audit / align_patch
                                #   / timeline_gate / precheck_timeline
                                #   / scan_seed(出锚点) / scan_inclusive(词表判定)
                                #   / structure_check(结构前置门禁) / show_ids(对照表)
                                #   / round_orchestrator + lib/
```

脚本速查:

| 脚本 | 用途 | 模式 |
|---|---|---|
| `extract_slice.py` | ASS+SRT 配对切片,标异常 | 自动审校 |
| `precheck_punct.py` | 中文行标点归一(默认 dry-run) | 自动审校 |
| `pre_audit.py` | 三轨预审(需显式开启) | 自动审校 |
| `scan_seed.py` | 出锚点（命中词/白名单候选/感叹·贬义·主权形态 + 上下文段），贴进审计 prompt。**只定位，不判断** | 自动审校(R11, 也用于 1–7 类查漏) |
| `scan_inclusive.py` | 第 8 类词表判定:按子域 A/B/C/D 分段出命中;C 子域只 flag 不改,L4 白名单优先丢弃。**首列是 srt_id**,可直接进 fixes.json。**词表 0 命中 ≠ 干净** | 自动审校(R11) |
| `structure_check.py` | 结构前置门禁:轨道枚举/起点重合/时长异常/索引偏差画像/残片重复。ABORT(20) 不许开工、SUSPECT(21) 放行待看。**偏差小 ≠ 配对了** | 自动审校(开工前) |
| `show_ids.py` | `srt_id → 英文/中文/时间` 对照表,`--ids/--range/--grep/--empty` 过滤。裁决时逐条核对位置用 | 三模式 |
| `round_orchestrator.py` | 轮次编排:排轮次表/记轮次/整轮快照回滚/定格/出 final-report | 自动审校 |
| `apply_fixes.py` | 执行 fixes.json / 回滚 / `--manual-log` | 三模式 |
| `global_replace.py` | 跨文件纯文本替换 | 三模式 |
| `verify_fixes.py` | 核验 log 已落盘 | 三模式 |
| `cross_check.py` | 中英对照复核 + 撞车预警 + 动到历史结论 | 三模式 |
| `regression_check.py` | 跨轮次台账/连续改动/批次沉住度(只读 log,不跑模型) | 三模式 |
| `extract_subs.py` | 列/抽片源内嵌字幕流(判轴的前置) | 对轴 |
| `align_audit.py` | 对音频测时间偏差(whisper/qwen 双引擎);qwen 分块按显存规划并跑两档,跨档不一致报 AMBIGUOUS | 对轴 |
| `align_patch.py` | 按偏移量改时间轴(线性/曲线/重定时);写 log、`--revert` 撤销 | 对轴 |
| `timeline_gate.py` | 读凭据判时间轴能否用于开工(不跑模型) | 对轴 + 自动审校阶段 0 |
| `precheck_timeline.py` | L0 结构哨兵:秒级时间轴体检(不加载模型) | 前置 |

项目产物(不进 skill):
```
.subtitle-polish/
├── slices/            # 切片
├── reports/           # audit-report.md / detail / dry-run.md / optional-fixes.md
├── fixes.json
├── optional-fixes.json
├── runs/<stamp>/      # 自动审校无监管模式:轮次快照 + manifest + final-report.md
├── log.jsonl          # 不进 git,.gitignore 加它
└── (字幕同目录) <episode>.ts.json   # 时间轴凭据,进 git
```

## 重要约束

- **不带术语表**:作为第三者审校,不预设专名映射。详见 `references/glossary-handling.md`。
- **8 类分类法**:结构性生产缺陷/漏译/语义反转/语境错译/专名错误不一致/原文拼写错误/低严重度/中立与合规(性别·宗教·政治·法律)。详见 `references/category-taxonomy.md`。**默认修 ≠ 默认跑**——第 6/7/8 类有判据但默认不进疗程,见上「三个开关」。
- **第 8 类 C 子域只标注**:政治与主权表述(大陆/台湾/西藏/时政)一律 `action: flag`,不进 `fixes.json`。具体时政条目不入词表——本 skill 只做发现与标注,不做立场判定。
- **第 8 类白名单是默认值,不是禁区**:`母头/公头/处女座/夫妻肺片/大陆架/台湾地区` 等词在 L4 白名单里,默认判「不是问题」。agent 通读后若认为确实该改,只能写 L3 并给理由,**不得自行生成替换词绕过白名单**;要改白名单本身得改 `references/inclusive-language.md` 并由 `tests/test_subtitle_polish_inclusive.py` 交叉校验。
- **判断归 agent,脚本只定位**(适用于全部 8 类):`scan_seed.py` 出的锚点只表示「这里出现了某种形态」,不表示「这里是问题」;`scan_inclusive.py` 返回 0 条候选也不代表干净,只代表词表没命中。**任何一类都不许拿脚本命中当结论**。全文通读与最终判定由并行 subagent 做,分工与切分规则见 `references/subagent-delegation.md`。
- **不 Edit ASS**:所有修改走脚本。**例外**:相邻 srt 块时间差 < 0.5s 时脚本 `_find_dialogue` 取最近也分不开(dry-run 会报"撞车预警"),允许破例 Edit ASS 兜底,但必须用 `apply_fixes.py --manual-log` 子命令补记 log.jsonl,不能手写 JSON。详见 `references/manual-flow.md` 兜底节。
- **srt 是权威英文源**(除拼写错误,srt 与 ass 同源,拼写靠子 agent 判断)。**ASR 听写错误**(如 `big closet`→`big chested`)算英文源本身错,默认只改中文轨,英文轨改不改是另一次决定,SRT 源始终不动。详见 `references/manual-flow.md` ASR 节。
- **异常标记**:提取脚本自动标 ASS_HAS_SRT_NONE 等,这些本身是审计线索。`MULTI_SAME_LANG` 在配对算法去重后,只有真同时间戳重复行才标(不再因 ±0.5s 容差误配产生)。
- **不要幻觉**:没把握说某行是问题就别报;但「判过了、认为不是问题」要写成 `false_positive` 记下来——清单与规则靠它迭代,沉默等于让清单只增不减。
