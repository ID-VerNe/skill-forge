# stage 2.7 三轨预审

stage 2.5（标点预检）之后、stage 3（审计）之前的**可选预处理**。廉价广撒网首轮，给 Claude 子 agent（stage 3）提供总览线索。SKILL.md stage 2.7 引用本文件。

脚本：`scripts/pre_audit.py`

## 何时用

- 大文件（>200 块）想先有总览再决定审计侧重
- 想用免费本地 LLM 补 Claude 的盲区（Claude 裸跑实测会漏 baseline 的【AI】标签类硬伤）
- 用户主动要求省成本广撒网

默认**不开**。用户显式 `--pre-audit` 或在 prompt 里说"先预审"才跑。不开时 skill 照常走 stage 3 Claude 子 agent 全量审计。

## 三轨

| 轨 | 模型/方式 | N | 取值 | 速度 | 长处 |
|---|---|---|---|---|---|
| 1 | gemini-3.1-flash-lite | 5 passes | intersection | ~5s/pass | 翻译腔/俚语/委婉语，稳 |
| 2 | glm-5.2 (reasoning=none) | 5 passes | intersection | ~17-60s/pass | 语义反转/语境错译 |
| 3 | check_fluency.py（规则） | 1 | 全收 | 秒级 | 书面语/机翻特征 100% 召回 |

**两 LLM 正交**（重叠 <15%，实测 e05 1/15、test1 1/7、e02 1/7）：单用任一个都漏一半真问题，必须并集。

## 模型强弱图（probe 实测）

| 维度 | gemini-3.1 | glm-5.2 | 规则 |
|---|---|---|---|
| 稳定性 | 完美（intersection≈union，每 pass 恒定） | 差（pass2 偶爆 36 条） | 确定 |
| 速度 | 5-10s | 17-60s | 秒级 |
| 语义反转 | 弱 | 强 | 抓不到 |
| 语境错译 | 中 | 强 | 抓不到 |
| 翻译腔(进行/所以) | 中 | 弱(6-11%) | **强(100%)** |
| 俚语/委婉语 | 强 | 中 | 抓不到 |
| 专名纠正 | 禁令后归零 | **0%（全假阳，编造型号）** | 抓不到 |
| 字符损坏 | 少量 | **82% 假阳（读 CJK 读错）** | 抓不到 |

**禁令 prompt**：脚本内置收窄版 prompt，显式禁字符损坏/专名/原文拼写三类（probe 验证降假阳 82%）。与 audit.tmpl 的 Claude 版不同。

**排除的模型**（probe 实测不可靠）：
- DeepSeek-V4-Flash：大 prompt 空返回 + 502
- sensenova-6.8：350s 超时 + finish=length
- gemini-3.5：不稳（11/3/11 波动）

## 总览输出

输出到 `.subtitle-polish/reports/`：
- `pre-audit-<stem>.json`（机器读）：三轨 raw + 高置信候选 + 已丢弃
- `pre-audit-<stem>.summary.md`（subagent 读）：总览摘要

总览字段：
- **高置信候选**：gemini intersection ∪ glm intersection ∪ 规则命中
- **中置信候选**：vote≥3（5 passes 里≥3 次报）
- **按类别分布**：专名集中→提示需联网核实；翻译腔集中→提示信达雅项多
- **每条标 source**（gemini-3.1 / glm / rule）+ 轨内稳定性（vote/N）
- **专名类标 needs_web_verify**

## 安全闸（防带歪）

三轨输出**只是线索**，不进 fixes.json，不进 audit-report.md。Claude 子 agent 必须独立审计 + verify（带 web access 核专名）后才能进报告。

1. **不直进报告**：预审候选只写 pre-audit json/md，不写 audit-report.md，不生成 fixes.json。
2. **专名类强制独立核实**：总览里专名/品牌/车型/人名候选标 `needs_web_verify: true`。Claude 见此标记必须自己联网核实，**不得直接采纳 LLM 建议译文**（GLM 专名建议 100% 编造，probe 实测：Ferrari Luce→"Luxion"、Jaguar Type 01→Type 00 全错）。
3. **字符损坏类丢弃**：聚合阶段直接丢弃 category=字符损坏/异体字/错别字/原文拼写 的候选（GLM 这类 82% 假阳）。写进"已丢弃"段供人抽查，不进高置信。
4. **audit.tmpl 约束**：收到 pre-audit 总览时，它是线索不是结论。独立判断每条，尤其专名类不得盲信 LLM 建议。
5. **带歪实测**（验证阶段）：带总览的 Claude 子 agent 审 test2，对比裸跑。带歪率超 10% 则 audit.tmpl 加更强约束。

## 带歪风险（实测推断）

Claude 子 agent 裸跑 test2 实测：
- 在语义/语境类**有独立判断力**——srt 73/133 自己独立发现并报，没靠总览。这类不太被带跑。
- 真正风险在**专名假阳**：总览标"X 该改 Y"（GLM 假阳），Claude 会不会盲信？裸跑无法验证，必须带总览实测。

裸跑还暴露：Claude **漏了 baseline 的 #1【AI】标签**（显眼结构缺陷）。预审总览能补这个——三轨会标出 baseline 风格的硬伤候选，Claude 看到"总览标了 X 但我没报"会重看一眼。

## 环境变量

- `GLM_API_KEY`：必填（两 LLM 轨共用）。缺则 LLM 轨全跳过，只跑规则轨。
- `GLM_API_URL`：默认 `http://localhost:37183/v1/chat/completions`
- `GLM_MODEL`：默认 `glm-5.2`
- `GEMINI_MODEL`：默认 `gemini-3.1-flash-lite`

启动时 ping 探测模型可用性，不可用（404/502/超时）的轨跳过并 log，不崩。符合"缺 key 的轨直接不跑，其余轨照常"。

## 用法

```bash
# 三轨全跑（默认）
python <skill>/scripts/pre_audit.py <slice.txt> \
    --context .subtitle-polish/context.md \
    --n 5 --out .subtitle-polish/reports

# 只跑规则轨（无 key 时降级）
python <skill>/scripts/pre_audit.py <slice.txt> --no-gemini --no-glm

# 只跑 gemini（快，不要 glm 的慢）
python <skill>/scripts/pre_audit.py <slice.txt> --no-glm --no-rule
```
