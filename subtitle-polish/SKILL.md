---
name: subtitle-polish
version: 1.1.0
description: 字幕精校,支持自动/手动两种模式。用户说"精校字幕"、"字幕审计"、"修字幕"时触发。自动模式:输入 ASS 双语成品 + SRT 源,走 审计→人确认→修复 全流程,修复由脚本执行(dry-run/accept/rollback)。手动模式:用户直接给修改指令,主 agent 翻译成 fixes.json 后 dry-run→accept→verify 一气呵成。也支持 /subtitle-polish 命令。
---

# subtitle-polish 字幕精校 Skill

本 skill 有**两种模式**,由用户调用时的措辞决定(见下「模式选择」)。两种模式共享同一套脚本(extract_slice / apply_fixes / global_replace / verify_fixes)与 `.subtitle-polish/` 工作目录。**修复手段都只调脚本,不直接 Edit ASS。**

- **自动模式**:输入 ASS 双语成品 + SRT 源,走 审计→人确认→修复 全流程(阶段 0→11)。详细流程见 `references/auto-flow.md`。
- **手动模式**:用户直接口述要改什么(如"把 0:01:16 的中文改成 XXX"),主 agent 翻译成 fixes.json 后 dry-run→accept→verify 一气呵成。详细流程见 `references/manual-flow.md`。

## 适用范围

- 输入:ASS 双语成品(英文行 + 中文行成对,track 取值 `英文/中文/注释`)+ SRT 源(权威英文)
- 不适用:无 SRT 源(拒绝运行)、VTT/单语成品、SRT 双语(不处理)
- 修复手段:只调脚本(extract_slice / apply_fixes / global_replace),**不直接 Edit ASS**

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

## 文件结构

```
<skill>/
├── SKILL.md                    # 本文件,路由
├── references/
│   ├── auto-flow.md            # 自动流程阶段 0→11
│   ├── manual-flow.md          # 手动流程 M0→M6
│   ├── pipeline-spec.md        # 数据流/fixes.json schema/log/回滚规范
│   ├── batch-ordering.md       # 脚本批次顺序与 verify 失败处理
│   ├── category-taxonomy.md    # 7 类分类法
│   ├── glossary-handling.md    # 不带术语表原则
│   ├── punct-rules.md          # 标点规则细节
│   ├── pre-audit.md            # 三轨预审用法
│   └── prompt-injection.md     # prompt 构造约束
├── prompts/                    # audit/verify/synthesize 模板
└── scripts/                    # extract_slice.py / apply_fixes.py / global_replace.py + lib/
```

项目产物(不进 skill):
```
.subtitle-polish/
├── slices/            # 切片
├── reports/           # audit-report.md / detail / dry-run.md / optional-fixes.md
├── fixes.json
├── optional-fixes.json
└── log.jsonl          # 不进 git,.gitignore 加它
```

## 重要约束

- **不带术语表**:作为第三者审校,不预设专名映射。详见 `references/glossary-handling.md`。
- **7 类分类法**:结构性生产缺陷/漏译/语义反转/语境错译/专名错误不一致/原文拼写错误/低严重度。详见 `references/category-taxonomy.md`。
- **不 Edit ASS**:所有修改走脚本。
- **srt 是权威英文源**(除拼写错误,srt 与 ass 同源,拼写靠子 agent 判断)。
- **异常标记**:提取脚本自动标 ASS_HAS_SRT_NONE 等,这些本身是审计线索。
- **不要幻觉**:审计 agent 拿不准就别报,宁可漏报不要误报(有验证轮兜底)。
