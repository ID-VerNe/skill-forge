---
name: web-search-routing
description: |
  Web 搜索路由器。当用户说"搜一下 xxx"、"查一下 xxx"、"找一下最新 xxx"、"看看 xxx 现在怎么样"、"xxx 最新版本是什么"等模糊的新鲜度导向搜索时触发。把 keenable(雷达,远程 LLM 增强,抓新鲜源+厚 snippet+发布日期)和 wigolo(工作台,本地缓存+引用+深挖)串联使用:keenable 负责发现最新源,wigolo 负责把值得用的 URL 落库、抽取、引用、深挖。不要把两者当替代品单独用。注意:纯新鲜度且不引用的查询(如"今天xx价格多少")可只走 keenable。
---

# Web 搜索路由 — keenable + wigolo 串联

两个 web 工具互补,不要当替代品。按任务类型分工,默认串联。

## 两个角色

- **keenable = 雷达。** 远程 LLM 增强搜索:最新新闻/发布/价格/状态,多段厚 snippet,真实 `Published` 日期。单页定向提问用 `fetch_page_content` 传 `prompt` 直接返回答案,省 token。一次性:无缓存、无监控、无引用元数据。不要直接从 keenable 引用或持久化。
- **wigolo = 工作台。** 本地优先:持久化+引用+深挖。`fetch` 把页落本地缓存,`extract` 做结构化/schema/表格/JSON-LD,`crawl` 索引站点,`find_similar` 从缓存扩展,`research`/`agent` 综合报告,`watch`/`diff` 监控变化,`cache` 复用旧抓取。

## "搜一下 xxx" 默认流程

1. `mcp__keenable__search_web_pages` —— 首轮发现,收集 URL + 发布日期。
2. 对每个值得用的 URL → `mcp__wigolo__fetch` 落本地缓存。
3. 所有引用/复用走 wigolo cache(免费,有 `citation_id` + `source_span`)。绝不引用 keenable 的瞬时 snippet。

## 按任务路由

| 任务 | 主用 |
|------|------|
| 最新新闻/发布/价格/状态 | keenable,再 wigolo `fetch` 落库 |
| 单页定向提问 | keenable `fetch_page_content(prompt)` |
| 引用/评分/source_span | wigolo |
| 站点爬取/文档索引 | wigolo `crawl` |
| 结构化抽取(表格/字段/JSON-LD) | wigolo `extract` |
| 多步综合研究 | wigolo `research` / `agent` |
| 页面变化监控 | wigolo `watch` / `diff` |
| 相关内容发现 | wigolo `find_similar` |

## 铁律

keenable 发现的每个值得用的 URL → 第一步是 wigolo `fetch` 落库。keenable 发现,wigolo 锚定。

**例外:** 纯新鲜度、不引用的查询(如"今天xx价格多少"、"xx 发售了吗"),keenable 单飞即可,跳过 wigolo 步骤。

## 为什么这么分(2026-09-07 实测)

同一查询 "Anthropic Claude latest model release 2026":
- **wigolo**:5 条结果,4 条偏离(Release notes / Opus 4.6 / 登录页 / 首页),核心 Fable 5.1 新闻排第 3 且 snippet 只有一句。15.6s,fetch 5/5 超时。
- **keenable**:5 条全是 9 月初的新闻/导览,直击 Fable 5.1 + Mythos 5.1,多段 snippet 带日期/价格/benchmark。

keenable 胜在召回+新鲜度+内容量;wigolo 胜在可审计性(评分、citation、缓存、多引擎遥测)。互补,不冗余。
