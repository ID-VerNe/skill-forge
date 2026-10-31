---
name: subtitle-polish
version: 1.7.0
description: 字幕精校,支持自动/手动两种模式。用户说"精校字幕"、"字幕审计"、"修字幕"时触发。自动模式:输入 ASS 双语成品 + SRT 源,走 审计→人确认→修复 全流程,修复由脚本执行(dry-run/accept/rollback)。手动模式:用户直接给修改指令,主 agent 翻译成 fixes.json 后 dry-run→accept→verify 一气呵成。给了片源时可对音频做时间轴审计与修复(align_audit/align_patch)。也支持 /subtitle-polish 命令。
---

# subtitle-polish 字幕精校 Skill

本 skill 有**两种模式**,由用户调用时的措辞决定(见下「模式选择」)。两种模式共享同一套脚本(extract_slice / apply_fixes / global_replace / verify_fixes)与 `.subtitle-polish/` 工作目录。**修复手段都只调脚本,不直接 Edit ASS。**

- **自动模式**:输入 ASS 双语成品 + SRT 源,走 审计→人确认→修复 全流程(阶段 0→11)。详细流程见 `references/auto-flow.md`。
- **手动模式**:用户直接口述要改什么(如"把 0:01:16 的中文改成 XXX"),主 agent 翻译成 fixes.json 后 dry-run→accept→verify 一气呵成。详细流程见 `references/manual-flow.md`。

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

- `精校` / `自动` / `审计` → **自动模式**(如"精校:C:\xxx 其对应的srt是 C:\yyy")
- `手动修` / `改` / `手动` → **手动模式**(如"手动修:C:\xxx.ass 其对应的srt是 C:\xxx.srt")

ass 与 srt 可以是目录或单文件:
- 多文件:默认同名配对(去扩展名 stem 相等),`--strip-suffix` 去指定后缀
- 单文件:用户给详细地址,直接用

可选项目背景写在 prompt 里(如"这是汽车节目,注意底盘术语"),或放项目根 `.subtitle-polish/context.md`。

## 模式选择(路由)

技能激活后:

1. **判断模式**:按用户调用措辞——
   - 含 `精校`/`自动`/`审计` → 自动模式,**Read `references/auto-flow.md` 后按其中阶段 0→11 执行**。
   - 含 `手动修`/`改`/`手动` → 手动模式,**Read `references/manual-flow.md` 后按其中 M0→M6 执行**。
   - **两者都没有** → 默认自动模式。用户一句话里若明确写"自动对字幕做精校"或"手动对字幕做精校"也按此判断。
2. **解析 prompt**:提取 ass 路径、srt 路径、可选项目背景(两种模式都要)。
3. **校验**:若无 srt 路径 → 停下,告知"需要 SRT 源才能跑"。手动模式下若无具体修改指令 → 停下,告知"手动模式需要你告诉我要改什么"。
4. **自动模式**:每阶段结束向用户报告进度。门1(md 报告后)与门2(dry-run 后)**停下等用户**,不自动推进。
5. **手动模式**:M4 dry-run 自检通过后 accept+verify 连跑,中间不停等确认。

## 回滚(两模式共用)

```bash
# 按整 batch
python <skill>/scripts/apply_fixes.py --rollback batch=<batch_id>
# 按单条
python <skill>/scripts/apply_fixes.py --rollback id=<srt_id> --file <ass_path>
# 按时间点(回滚该时间之前所有)
python <skill>/scripts/apply_fixes.py --rollback before=<ts>
```
所有操作都留 log.jsonl 记录,支持单条/整 batch/时间点三种粒度回滚。**global_replace 与 precheck_punct 当前不单独支持 `--rollback`**(argparse 未注册),其改动靠 `.bak` 文件手动还原,或用 `apply_fixes.py --rollback batch=<它们的 batch_id>`(若该 action 被认)。详见 `references/pipeline-spec.md` 回滚节与 `references/batch-ordering.md`。

## 破例 Edit 兜底(两模式共用)

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

## 结案条件(两模式共用)

```bash
python <skill>/scripts/verify_fixes.py --batch-id <ts>   # 盘面 == log
python <skill>/scripts/cross_check.py   --batch-id <ts>  # 中英对照复核
python <skill>/scripts/align_audit.py   --sub <ass> --media <片源> --write-credential  # 对音频对齐
python <skill>/scripts/timeline_gate.py <ass> --media <片源>        # 凭据闸门(毫秒级)
```

三条判据的结论只有三态:**PASS(0) / FAIL(2) / UNVERIFIED(3)**。`UNVERIFIED` 不是「通过」,
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

## 文件结构

```
<skill>/
├── SKILL.md                    # 本文件,路由
├── references/
│   ├── auto-flow.md            # 自动流程阶段 0→11
│   ├── manual-flow.md          # 手动流程 M0→M6（含括注/ASR/兜底节）
│   ├── pipeline-spec.md        # 数据流/fixes.json schema/log/回滚规范
│   ├── batch-ordering.md       # 脚本批次顺序与 verify 失败处理
│   ├── category-taxonomy.md    # 7 类分类法
│   ├── glossary-handling.md    # 不带术语表原则
│   ├── punct-rules.md          # 标点规则细节
│   ├── pre-audit.md            # 三轨预审用法
│   ├── align-audit.md          # 对音频的时间轴审计与修复
│   ├── timeline-credential.md  # 时间轴凭据(sidecar)与阶段 0 闸门
│   ├── build-timeline.md       # 翻译前先从片源建立可信时间轴
│   └── prompt-injection.md     # prompt 构造约束
├── prompts/                    # audit/verify/synthesize 模板
└── scripts/                    # extract_slice / apply_fixes / global_replace
                                #   / verify_fixes / cross_check / precheck_punct / pre_audit
                                #   / extract_subs / align_audit / align_patch
                                #   / timeline_gate / precheck_timeline + lib/
```

脚本速查:

| 脚本 | 用途 | 模式 |
|---|---|---|
| `extract_slice.py` | ASS+SRT 配对切片,标异常 | 自动 |
| `precheck_punct.py` | 中文行标点归一(默认 dry-run) | 自动 |
| `pre_audit.py` | 三轨预审(需显式开启) | 自动 |
| `apply_fixes.py` | 执行 fixes.json / 回滚 / `--manual-log` | 两模式 |
| `global_replace.py` | 跨文件纯文本替换 | 两模式 |
| `verify_fixes.py` | 核验 log 已落盘 | 两模式 |
| `cross_check.py` | 中英对照复核 + 撞车预警 | 两模式 |
| `extract_subs.py` | 列/抽片源内嵌字幕流(判轴的前置) | 前置 |
| `align_audit.py` | 对音频测时间偏差(whisper/qwen 双引擎) | 两模式 |
| `align_patch.py` | 按偏移量改时间轴(线性/曲线/重定时);写 log、`--revert` 撤销 | 两模式 |
| `timeline_gate.py` | 读凭据判时间轴能否用于开工(不跑模型) | 两模式 |
| `precheck_timeline.py` | L0 结构哨兵:秒级时间轴体检(不加载模型) | 前置 |

项目产物(不进 skill):
```
.subtitle-polish/
├── slices/            # 切片
├── reports/           # audit-report.md / detail / dry-run.md / optional-fixes.md
├── fixes.json
├── optional-fixes.json
├── log.jsonl          # 不进 git,.gitignore 加它
└── (字幕同目录) <episode>.ts.json   # 时间轴凭据,进 git
```

## 重要约束

- **不带术语表**:作为第三者审校,不预设专名映射。详见 `references/glossary-handling.md`。
- **7 类分类法**:结构性生产缺陷/漏译/语义反转/语境错译/专名错误不一致/原文拼写错误/低严重度。详见 `references/category-taxonomy.md`。
- **不 Edit ASS**:所有修改走脚本。**例外**:相邻 srt 块时间差 < 0.5s 时脚本 `_find_dialogue` 取最近也分不开(dry-run 会报"撞车预警"),允许破例 Edit ASS 兜底,但必须用 `apply_fixes.py --manual-log` 子命令补记 log.jsonl,不能手写 JSON。详见 `references/manual-flow.md` 兜底节。
- **srt 是权威英文源**(除拼写错误,srt 与 ass 同源,拼写靠子 agent 判断)。**ASR 听写错误**(如 `big closet`→`big chested`)算英文源本身错,默认只改中文轨,英文轨改不改是另一次决定,SRT 源始终不动。详见 `references/manual-flow.md` ASR 节。
- **异常标记**:提取脚本自动标 ASS_HAS_SRT_NONE 等,这些本身是审计线索。`MULTI_SAME_LANG` 在配对算法去重后,只有真同时间戳重复行才标(不再因 ±0.5s 容差误配产生)。
- **不要幻觉**:审计 agent 拿不准就别报,宁可漏报不要误报(有验证轮兜底)。
