---
name: web-search-routing
description: |
  Web 搜索路由器。当用户做任何 web 检索("搜一下/查一下/找一下/看看/检索一下 xxx"且指向网络信息)、最新动态查询、调研/对比/发现型查询(找几个工具、对比方案、有没有这类东西)时触发。keenable(雷达:远程 LLM 增强,抓新鲜源+厚 snippet+发布日期,单页定向提问)和 wigolo(工作台:本地缓存+引用+深挖)串联:keenable 发现,wigolo 落库、抽取、引用、深挖。默认串联,仅单点事实查询例外。领域专用 skill 命中时以其为准:travel-ticket(票务)、glue-engineer(库/包检索与组合)。本 skill 是通用 web 检索的兜底路由;代码库/本地文件检索不在范围。
---

# Web 搜索路由 — keenable + wigolo 串联

两个 web 工具互补,不要当替代品。按任务类型分工,默认串联。

## 两个角色

- **keenable = 雷达。** 远程 LLM 增强搜索:最新新闻/发布/价格/状态,多段厚 snippet,真实 `Published` 日期。单页定向提问用 `fetch_page_content` 传 `prompt` 直接返回答案,省 token。一次性:无缓存、无监控、无引用元数据。不要直接从 keenable 引用或持久化。
- **wigolo = 工作台。** 本地优先:持久化+引用+深挖。`fetch` 把页落本地缓存,`extract` 做结构化/schema/表格/JSON-LD,`crawl` 索引站点,`find_similar` 从缓存扩展,`research`/`agent` 综合报告,`watch`/`diff` 监控变化,`cache` 复用旧抓取。

## 默认链(凡要写进回答、要引用、要对比多源的查询)

无论查询是"最新动态""有没有这类工具""对比 A 和 B""找几个能用的 X"——只要最终回答会引用来源或综合多源,默认走这条:

1. 双源发现(都必跑,各挖各的——两源索引覆盖不同,只跑一个会丢候选):
   - **wigolo 路:** 先 `cache`(查本地,命中免费,再查旧题必中)→ 未命中跑 `search`(多关键词变体,结果带引用且落缓存)。
   - **keenable 路:** `search_web_pages` 补召回+新鲜度+厚 snippet,收集 URL + 发布日期。keenable 的 URL 稍后必须 wigolo `fetch` 落库才能引用。
   wigolo 强在可引用+缓存复用,keenable 强在新鲜度+召回;先本地后远程省额度,但两路都跑,不准单飞。
2. 对每个值得用的 URL → `mcp__wigolo__fetch` 落本地缓存(keenable 发现的 URL 尤其要 fetch,它瞬时无引用)。
3. 所有引用/复用走 wigolo cache(带 `citation_id` + `source_span`)。绝不引用 keenable 的瞬时 snippet。

已有明确 URL 或重查旧题:跳过发现,直接 wigolo `cache`(命中免费)→ `fetch`(未命中补抓)。

## 按任务路由

| 任务 | 主用 |
|------|------|
| 找库/选库/包检索/跨生态组合(有没有现成的 X 库、对比 A 和 B 库、怎么组合实现某功能) | **glue-engineer**(`polyglot scout`/`discover`) |
| 最新新闻/发布/价格/状态 | keenable,再 wigolo `fetch` 落库(先 wigolo `cache`/`search` 看本地) |
| 调研/对比/发现型(找几个工具、对比方案、有没有这类东西) | 默认链 |
| 单页定向提问 | keenable `fetch_page_content(prompt)` |
| 引用/评分/source_span | wigolo |
| 站点爬取/文档索引 | wigolo `crawl` |
| 结构化抽取(表格/字段/JSON-LD) | wigolo `extract` |
| 多步综合研究 | wigolo `research` / `agent` |
| 页面变化监控 | wigolo `watch` / `diff` |
| 相关内容发现 | wigolo `find_similar` |

**库检索优先交 glue-engineer:** 通用 web 检索(keenable+wigolo)能搜到库,但 glue-engineer 是更专的库检索工具——`polyglot scout <lang> <keyword>` 做包级检索(找要装的库)、`polyglot discover` 做 repo 级检索(找有没有人做过整项目)、还能 cap-match/license 检查、deep 源码分析。凡查询核心是"找/选/对比库或包",直接走 glue-engineer,不重复跑通用链。两种场景例外,仍走本 skill 默认链:(1) 查某个库的**新闻/版本/发布动态**(glue-engineer 不抓新鲜度);(2) 查某个库的**用法/教程/社区讨论**(属 web 内容,glue-engineer 不索引)。

## 铁律与例外

**铁律 1 — 双源发现:** wigolo 和 keenable 的索引覆盖不同(实测:同一截图工具查询,两源各挖到不同候选),只跑一个会丢掉另一个能找到的东西。发现步骤两路都必跑,不准单飞。wigolo 先(省额度、本地命中免费)、keenable 后(补召回+新鲜度),但顺序不等于可跳过。

**铁律 2 — 引用落库:** 凡是要写进有引用的回答的 URL → 第一步必须是 wigolo `fetch` 落库,引用一律从 wigolo cache 取(带 `citation_id` + `source_span`)。keenable 发现,wigolo 锚定。keenable 的输出是瞬时的(无缓存、无 `citation_id`、无 `source_span`),直接引用即丢失可审计性。

不要用"一次性调研过重"当借口跳过 wigolo。同样 N 次 fetch,走 wigolo 拿到缓存+引用,走 keenable 只拿到瞬时文本——跳过 wigolo 不是省成本,是纯损失。调研/对比/发现型查询恰恰最该走完整链路。

**唯一例外——单点事实查询:** 答案能在一条 snippet 内闭合、不交叉比对、不写进有引用的回答(如"今天 xx 价格多少""xx 发售了吗""xx 现在是什么版本号")。这类 keenable 单飞即可,铁律 1/2 都不适用。判断标准看查询形状(单点事实 vs 多源综合),不看"会不会引用"——查询时无法预知最终是否引用。

## 为什么这么分(2026-09-07 实测)

同一查询 "Anthropic Claude latest model release 2026":
- **wigolo**:5 条结果,4 条偏离(Release notes / Opus 4.6 / 登录页 / 首页),核心 Fable 5.1 新闻排第 3 且 snippet 只有一句。15.6s,fetch 5/5 超时。
- **keenable**:5 条全是 9 月初的新闻/导览,直击 Fable 5.1 + Mythos 5.1,多段 snippet 带日期/价格/benchmark。

keenable 胜在召回+新鲜度+内容量;wigolo 胜在可审计性(评分、citation、缓存、多引擎遥测)。互补,不冗余。
