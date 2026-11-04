# 时间轴凭据与闸门

> 一句话：**「这条字幕的轴凭什么可信」必须是一个文件，不是一个假设。**

相关 issue：skill-forge #9（契约漏项）、#10（判定读不出来）。

## 为什么需要

`SKILL.md` 的输入契约原本只写「ASS 双语成品 + SRT 源（权威英文）」，对时间轴一个字没要求。于是「时间轴是对的」退化成常识假设——**常识假设不会有人验**。

代价：一批 8 集走完全流程，`verify_fixes` 0 失败、`cross_check` 全绿、报告写「8 集通过」，交付后被反馈「所有集都对不上轴，越往后偏得越多」。回头对音频测，E01/E07/E08 分别偏 **+2.44 / +2.79 / +2.91 秒**。

对比一下这两种写法的差别：

| 写法 | 后果 |
|---|---|
| 「SRT 是权威英文」（写进契约） | agent 会拿 SRT 校对 ASS 文本 |
| 「时间轴是对的」（没写） | agent 直接开始改译文 |

一个显式的契约会被执行，一个隐式的假设会被继承——包括继承它的错误。

## 凭据长什么样

`<episode>.ts.json`，与字幕同目录：

```json
{
 "version": 1,
 "episode": "S06E01",
 "media":  { "path": "/data/S06E01.mkv", "sha1": "3f2a…", "duration": 2712.4 },
 "source": { "kind": "embedded_stream", "index": 2,
             "title": "Original | English (United Kingdom)", "family": "UK" },
 "axis":   { "engine": "qwen3-forced-aligner", "anchors": 761, "total": 763,
             "mad": 0.18, "drift": -0.11, "window_span": 0.23, "tol": 0.3,
             "verdict": "PASS", "cross_checked": true, "l0": null,
             "confidence": { "status": "corroborated", "label_a": "qwen3-forced-aligner",
                             "label_b": "whisperx", "n_compared": 761,
                             "ts_median": 0.11, "ts_p90": 0.34, "ts_max": 0.72,
                             "offset_diff": 0.12, "slope_diff": 0.0004,
                             "verdict_agree": true } },
 "files":  [ { "path": "S06E01.ass", "sha1": "9c14…",
               "patched_at": null, "max_shift": 0.0, "patches": 0 } ],
 "computed_at": "2026-10-31T14:00:12.881"
}
```

四个字段各自防一类坑：

| 字段 | 防的是 |
|---|---|
| `media.sha1` | 片源换了（重压/换版），轴跟着失效 |
| `source.index` / `family` | 用的是 UK 还是 US，白纸黑字，不靠记忆 |
| `axis.verdict` | 没有 PASS 就不许进门 |
| `patched_at > computed_at` | **改过时间轴但没复测**，凭据自动失效 |

最后一条是实测里最容易犯的：E03 一轮修正后如果不复测，凭据就成了「上一版」的结论。

`files[]` 是数组而不是单个对象，因为 ASS 与 SRT 可能各自被 `align_patch` 施加过。

## 双对齐器可信度（`axis.confidence`）

`align_audit --asr-words-b` 提供第二路对齐器结果时，凭据会多记一块 `axis.confidence`。
它不是第四道门，**只回答「这条 PASS/FAIL 有没有被另一套对齐器印证」**。

口径是**比时间戳**：同一份现成英文文本，分别喂 whisperX 的 wav2vec2 对齐器与
qwen3-forced-aligner，两路各自产出词级时间戳，再比逐行起点差与各自的偏移/斜率结论。
**不需要独立转录**——两路都只是在做「文本 ↔ 音频」的强制对齐。

| `confidence.status` | 含义 | 怎么用 |
|---|---|---|
| `corroborated` | 两路偏移结论一致 | 该 PASS/FAIL 属高置信结论 |
| `divergent` | 时间戳或结论明显不一致 | 现有 PASS/FAIL 不可全信，报 AMBIGUOUS 或抽查音频 |
| `single_source` | 只有一路可用 | **不冒充双证**，按单源结论使用 |
| `no_data` | 两路都没有足够锚点 | 没有可信度信息 |

阈值（保守默认，待真实样片校准，见 `align-audit.md` §7.5）：逐行起点差中位
≤0.25 s、P90 ≤0.60 s、两路偏移中位之差 ≤0.25 s、斜率之差 ≤0.002 /s、每路至少
10 个锚点。

**判定顺序里没有 `confidence`。** 凭据是否可用于结案仍只看 `axis.verdict`；
`confidence` 只被 `round_orchestrator --report` 读去给时间轴结论加一句附注
（`divergent` 时写「未获双对齐器印证」，但不改 PASS/FAIL 的 code）。
缺省（没跑第二路）就是 `null`，不写成 `corroborated` 冒充验过。

## 判定顺序（不要改）

```
1. 凭据不存在                        -> UNVERIFIED  3
2. 凭据绑定了片源但没给 --media       -> UNVERIFIED  3   不能假装验过
3. media.sha1 ≠ 当前片源              -> UNVERIFIED  3   换片了
4. files[].sha1 ≠ 当前文件            -> UNVERIFIED  3   文件被外部改过
5. files[].patched_at > computed_at  -> UNVERIFIED  3   改过没复测
6. axis.verdict = FAIL               -> FAIL        2
7. 其余                              -> PASS        0
```

**陈旧性必须排在 verdict 前面。** 一份写着 PASS 的凭据，如果文件之后又被改过，它描述的是过去的状态——此时原来 PASS 还是 FAIL 都不作数。顺序写反会得到「凭据过期了但照样放行」。

第 2 条是同一个道理：凭据声明了什么，就必须验证什么。记了 `media.sha1` 却没给片源，就不能假装验过了。

## 三个命令

```bash
# 1. 产出凭据（PASS 与 FAIL 都写）
python <skill>/scripts/align_audit.py --sub S06E01.ass --media S06E01.mkv \
    --write-credential --source-index 2 --source-family UK

# 2. 开工前过闸门（毫秒级，不跑模型）
python <skill>/scripts/timeline_gate.py S06E01.ass --media S06E01.mkv

# 3. 批量
python <skill>/scripts/timeline_gate.py ./subs --json gate.json
```

为什么 FAIL 也要写凭据：只写 PASS 的话，FAIL 在闸门眼里会退化成「没有凭据」，于是「验过、不对」和「没验过」又变成同一种状态——那正是这张 issue 要消灭的二义性。

## 退出码是唯一可靠的信号

```
0 PASS         可以开工
2 FAIL         轴有问题，必须先修
3 UNVERIFIED   没验 / 凭据失效，先跑 align_audit
4 AMBIGUOUS    验了但判不出来（多条候选轴无法区分，见 issue #11）
```

`align_audit --no-strict` 可以让它永远 exit 0，但**只用于本地调试**。文档里不推荐、流程里不许用——它一出现就会变成新的「可选」。

## 无片源的合法降级

没有片源就跑不了审计，这是允许的，但要按规矩来：

```
无片源 → 允许交付，但：
  a) 结案结论写 UNVERIFIED，交付说明里注明「未验时间轴」
  b) 报告里不允许出现「全部通过」「验证完毕」这类措辞
  c) 该批次没有凭据，下次拿到片源必须重验
```

(a) 和 (b) 是一条的两面：只要报告里还写着「通过」，读者就不会去看那行小字。

`round_orchestrator --report` 的时间轴结论**以凭据为准，不以 `--init` 时的 `--media` 为准**（issue #28）：

- 凭据新鲜 → 按 `axis.verdict` 写 PASS / FAIL / AMBIGUOUS；
- `--init` 没给 `--media` 但凭据记录过片源 → 用凭据里的路径复核「没换片」，不要写 UNVERIFIED；
- 凭据缺失或失效 → 才写 UNVERIFIED，并在「本次未覆盖」里列出失效原因。

这样「先跑文本轮、后补验轴」的批次也能在最终报告里如实写成 PASS。

## 与修复动作的联动

`align_patch` 改完时间轴后调 `credential.touch_patch()`：

- 同步 `files[].sha1`（否则会先撞上「文件被外部改过」，报错指向错误的原因）
- 写 `patched_at`（于是 `patched_at > computed_at` 生效，闸门立刻转 UNVERIFIED）

这个顺序保证了「改完必须复测」是**自动的**，不依赖任何人记得。

## 常见问题

**Q：每集都要写凭据，会不会很烦？**
A：`--write-credential` 是 `align_audit` 的一个开关，审计本来就要跑，多写一个 json 不增加操作。真正省事的是闸门：它毫秒级，可以在每次开工前都跑。

**Q：凭据要不要进 git？**
A：要。它记录的是「这一集的轴被验过、用的是哪条流」，是交付物的一部分。`.bak` 不进 git，凭据进。

**Q：字幕改了一句译文，文件 sha1 就变了，凭据不也失效了？**
A：会失效，这是对的——但只在你**直接改文件**时。正常走 `apply_fixes` 的话，文本改动不该让时间轴凭据失效。目前的实现偏保守（任何内容变化都判 stale），后续可以改为「只比对时间字段的 sha1」。在那之前，文本改完重跑一次审计即可（有 `--asr-words` 缓存时是秒级）。
