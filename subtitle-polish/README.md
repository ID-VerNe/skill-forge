# subtitle-polish

> ASS 双语字幕精校 Skill —— 审计 → 人确认 → 修复，修复由脚本执行（dry-run / accept / rollback）

## 用途

输入 ASS 双语成品（英文行 + 中文行成对）+ SRT 源（权威英文），自动走完整精校流程：

1. **提取切片**：ass + srt 配对，按 srt 块序号切（~700 块/份 + 100 块 overlap），一 block 一行带 srt_id
2. **并行审计**：每份切片起一个子 agent，按 7 类分类法找硬伤
3. **验证轮**：按类别打包起 adversarial 验证 agent（默认驳回），过滤幻觉误报
4. **合并报告**：主 agent 去重合并，按严重度排序输出 md 报告
5. **人确认门1**：人 review 报告，说"修哪些 id"
6. **生成 fixes.json**：AI 按人选的 id 生成结构化修复清单
7. **脚本 dry-run**：输出可读预览，人确认
8. **执行修复**：脚本按 srt_id + track 定位写入 ASS，记 log.jsonl
9. **可回滚**：按 batch_id / srt_id / 时间点 三种粒度回滚

## 调用

```
/subtitle-polish 精校：<ass_dir_or_file> 其对应的srt是 <srt_dir_or_file>
```

ass 与 srt 可以是目录或单文件。多文件默认同名配对（去扩展名 stem 相等）。

## 7 类问题分类法

| 类别 | 严重度 | 默认修 |
|------|--------|--------|
| 1 结构性生产缺陷（配对错位/英文轨覆盖/重复/截断/漏译） | 高 | 是 |
| 2 漏译 | 高 | 是 |
| 3 语义反转（否定/时态/程度/胜负颠倒） | 高 | 是 |
| 4 语境错译（词选对但场景不符） | 中 | 是 |
| 5 专名错误/不一致 | 中 | 是 |
| 6 原文拼写错误（undertrain→undertray） | 中 | 是 |
| 7 低严重度（重复译文/语序/用词不自然） | 低 | 否（进 optional-fixes） |

详见 `references/category-taxonomy.md`。

## 关键设计

- **不带术语表**：作为第三者审校，不预设专名映射。每个专名基于上下文与领域知识判断前后是否一致。项目背景可通过 prompt 参数或 `.subtitle-polish/context.md` 注入。
- **SRT 是权威英文源**（除拼写错误——srt 与 ass 同源，拼写靠子 agent 判断）。
- **不 Edit ASS**：所有修改走脚本，skill 只编排流程。
- **特效标签自动还原**：replace/swap 时自动提取并保留原行 `{\be3}`、`{\an8}` 等前导标签，与 `final_new` 自带标签合并去重。
- **标点预检**：`precheck_punct.py` 对照 translate_principle pipeline 的标点规则，精校前先规范化中文行（`……`→`…`、`，。、`→空格、数字间 `.` `,` 保留等），英文行不动。

## 脚本

| 脚本 | 功能 |
|------|------|
| `scripts/extract_slice.py` | ass+srt → 按 srt 块切片，输出 `<srt_id> | <ass_time> | <英文> | <中文> | <注释>`，标异常 |
| `scripts/precheck_punct.py` | 标点规范化预检（中文行，保留 ASS 标签） |
| `scripts/apply_fixes.py` | replace/delete/swap，dry-run/accept/rollback，自动还原特效标签 |
| `scripts/verify_fixes.py` | 执行后验证：读 log.jsonl 按 srt_id 重读 ASS，核对 new_text 落盘 |
| `scripts/global_replace.py` | 跨文件统一专名，可选 track |
| `scripts/lib/` | time_fmt / ass_srt_pair / log / tags / paths 工具 |

## 产出（项目侧，不进 skill）

```
.subtitle-polish/
├── slices/              # 切片（审计中间产物）
├── reports/             # audit-report.md / detail / dry-run.md / precheck-punct.md / verify-fixes.md
├── fixes.json            # 主修清单（1-6 类）
├── optional-fixes.json   # 第 7 类低严重度
└── log.jsonl            # 操作日志（不进 git）
```

## 依赖

- Python 3（系统 python）
- `pysubs2`（skill 启动时自动 `pip install pysubs2`）

## 范围与边界

- **适用**：ASS 双语成品 + SRT 源。track 取值 `英文/中文/注释`。
- **不适用**：无 SRT 源（拒绝运行）、VTT/单语成品、SRT 双语。
- 其他语言对要改 track 名需改 prompts 模板与脚本配置。
