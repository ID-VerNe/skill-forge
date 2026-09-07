# 信达雅判据（第 7 类细则）

字幕精校第 7 类（低严重度）覆盖"信达雅"三轴。SKILL.md stage 5 与 category-taxonomy.md 路由到此。预审脚本（pre_audit.py）的两条 LLM 轨也用此三轴。

**第 7 类是润色不是硬伤**：意思对、不影响理解，但润色后更自然。默认不修，进 `optional-fixes.json`。与 1-6 类的边界：1-6 是"译错"（语义反转/漏译/专名错），7 是"译对但不够好"。

## 三轴

### 信（忠实度微偏，非硬伤）

意思大体对，但程度/语气微偏。区别于第 3 类（语义反转是意思译反；信轴是意思对但分量/语气偏）。

- **程度副词方向没反但分量不足/过头**：`a bit of a mistake`→"大错"（程度放大，但没到反转）；`slightly`→"完全"
- **情绪标记丢失**：`Oh`/`Well`/`Honestly`/`Ugh`/`Right` 等语气词没还原成"哦""嗯""说真的""呃""对"
- **语气强度被磨平**：讽刺/兴奋/烦躁没译出对应语气（如英式吐槽被译成正经陈述）
- **未说完的半句被补全**：`You're a man of...`（没说完）译成"你是个有品位的人"（补了具体词，曲解原意）。字幕惯例：半句应反映不完整，不宜补全

### 达（通顺/无翻译腔）

译文生硬、机翻腔重、不符合中文习惯。

- **书面语残留**（check_fluency.py 黑名单，确定性检查，召回 100%）：
  进行/实施/开展/予以/给予/关于/针对/基于/鉴于/显著/充分/有效/积极/此外/因此/所以/然而
  口语对白里出现这些 = 翻译腔。例外：客观陈述/旁白/正式场合可用。
- **机翻特征**（check_fluency.py 正则）：`的的`/`了了`/重复标点
- **冗余连接词**：然后/所以/这个 过度堆砌
- **欧式句法**：长定语从句直译、名词堆砌、动名词结构当动词用（`making a car`→"进行制作一辆车"）
- **长度异常**（check_fluency.py，低置信辅助）：译文 < 原文×0.25 或 > ×2.0

### 雅（地道/口语化）

用词/语序/风格不口语化。

- **用词书面不口语**：`购置`→`买`、`返程`→`回去`、`便捷的解决方案`→`快速搞定/小修小补`
- **不符合中文语序**：定语过长、主从句顺序别扭
- **俚语/口语梗被译成书面陈述**：`No shit, Sherlock`→"废话连篇"丢了讽刺俚语味；`mag-bloody-nificent` 的英式俏皮没体现
- **生造词**：`行芳驾`（无此词）、`小小鬼`（Hillman Imp 的 Imp 该译"小精灵"）
- **机翻音译**：`heritage line`→"利涅"（line 不该音译）、`non-palisade`→"非帕利塞德"

## 与 translate_principle pipeline 的关系

判据来源（不重复实现，引用其规则）：

- **`prompts/review_and_polish_v2.prompt`**（`C:\Users\VerNe\Downloads\Documents\translate_principle\subtitle pipeline source\subtitle\prompts\`）：口语优先/情绪还原/节奏把控/文化本地化/人物一致性五原则；禁用书面语 `进行`/`实施`/`开展`
- **`core/quality_checker.py`**（同 pipeline）：`TranslationQualityChecker` 类，书面语黑名单 + 机翻特征正则 + 长度比。skill 的 `scripts/check_fluency.py` 照搬此规则（收窄了长度比阈值以适应字幕单行）
- **`prompts/post_check.prompt`**：第 5 维"语域匹配与机翻腔消除"（adversarial 终审维度）
- **`prompts/webui_step_3.prompt`**：语感分析"指出翻译腔过重的长难句"+ 边界界定（事实区死守/情感区放开）

## 报表约束

- **明显不自然才报，可接受的非最优不报**。口语化风格（James May 的"压根/破烂/刷一下"）是风格不是问题——baseline 报告明确判为风格非问题。
- 第 7 类进 `optional-fixes.md` + `optional-fixes.json`，不进主 `audit-report.md`（除"未报项说明"放核验后排除的疑似项）。
- 预审脚本（pre_audit.py）的信达雅候选**只是线索**，Claude 子 agent 独立判断后才能进 optional-fixes。

## LLM 预审的信达雅表现（probe 实测）

- **gemini-3.1-flash-lite**：信达雅三轴判断质量好，5 passes 完美稳定（intersection≈union），擅长翻译腔/俚语/委婉语
- **glm-5.2**：软语境信达雅可，但单 pass 不稳（取 intersection）；专名/字符损坏类禁令后仍残留假阳
- **规则检查（check_fluency.py）**：书面语/机翻特征召回 100%，两 LLM 都只有 6-11%——确定性翻译腔必须靠规则兜底
- **两 LLM 正交**：gemini 抓的与 glm 抓的重叠 <15%，并集才能覆盖全
