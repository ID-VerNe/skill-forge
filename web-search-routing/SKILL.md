---
name: web-search-routing
description: |
  Web 搜索路由器。当用户做任何 web 检索("搜一下/查一下/找一下/看看/检索一下 xxx"且指向网络信息)、最新动态查询、调研/对比/发现型查询(找几个工具、对比方案、有没有这类东西)时触发。按任务类型选最专工具:GitHub 仓库/issue 用 gh CLI;新鲜度/新闻/价格首选 keenable(内置 WebSearch 在本机不可用);单页抓取+引用用 wigolo。glue-engineer 是重 skill,用户显式调用,负责重量库检索/能力匹配,不自动加载。本 skill 是通用 web 检索的兜底路由;代码库/本地文件检索不在范围。
---

# Web 搜索路由 — 按任务类型选最专工具

不要用固定工具组合糊弄所有查询。按任务类型选最专工具。内置 WebSearch 在本机(IP 限制)不可用,别拿它当兜底——它返回兜底提示,不出结果。

## 工具分工

| 任务类型 | 首选工具 |
|------|------|
| GitHub repo 发现(轻量,3-7 个候选) | `gh search repos`(`--sort stars` 取前 N) |
| GitHub issue / discussion / PR 读取 | `gh issue view` / `gh api repos/.../discussions`(glue-engineer 无此能力) |
| GitHub repo 发现 + 评分 + 能力匹配 + 胶水代码(重量) | glue-engineer(用户显式调用,不自动加载) |
| 库/包注册表检索(版本/许可证/下载量) | glue-engineer(`polyglot scout`/`cross-search`,用户显式调用) |
| 新鲜度/新闻/发布/价格/状态(非 GitHub web 查询) | keenable `search_web_pages`(见下方说明) |
| 单页定向提问(已知 URL 抽字段) | keenable `fetch_page_content(prompt)` |
| 单页内容抓取 + 引用落库 | wigolo `fetch` |
| 站点爬取/文档索引 | wigolo `crawl` |
| 结构化抽取(表格/字段/JSON-LD) | wigolo `extract` |
| 多步综合研究 | wigolo `research` / `agent` |
| 页面变化监控 | wigolo `watch` / `diff` |
| 相关内容发现 | wigolo `find_similar` |
| 本地缓存复用/重查旧题 | wigolo `cache` |

## keenable 的角色(诚实定位)

keenable 不是 agent 默认会主动选的工具。实测 10 路并行(2026-09-09),agent 在新鲜度/新闻类查询上默认只跑 wigolo 单源,不会自动跑 keenable——即便 skill 写"必跑"也管不住。所以别把 keenable 当强制铁律,它做不到。

keenable 的真实价值:**内置 WebSearch 在本机不可用,keenable 是唯一可用的新鲜度+召回源**(2026-09-07 实测:同一查询 wigolo 5 条结果 4 条偏离,keenable 5 条直击当周新闻)。查最新动态/新闻/发布/价格这类**新鲜度导向**查询,主动调一次 `mcp__keenable__search_web_pages` 补召回+新鲜度,值得;但不是每个 web 查询都强求。

判断要不要 keenable 看查询形状:明显新鲜度导向(最新版本/刚发布/今天价格)→ 跑 keenable 补;静态调研(有没有这类工具、对比方案)→ wigolo 为主,keenable 可选补。

## 引用落库(唯一硬约束)

凡是要写进有引用的回答的 URL → 第一步必须是 wigolo `fetch` 落库,引用一律从 wigolo cache 取(带 `citation_id` + `source_span`)。keenable 发现的 URL 尤其要 fetch——keenable 输出是瞬时的(无缓存、无 `citation_id`、无 `source_span`),直接引用即丢失可审计性。gh CLI 抓的 issue/discussion 引用时带 issue 编号 + 仓库 URL 即可,gh 已是结构化源。

不要用"一次性调研过重"当借口跳过 wigolo fetch。同样 N 次 fetch,走 wigolo 拿到缓存+引用,走 keenable 只拿到瞬时文本——跳过 wigolo 不是省成本,是纯损失。

## 交叉验证

内置 WebSearch 不可用,交叉验证靠 **keenable + wigolo 双取**(两源都跑一遍,结果对照),或 **多来源 wigolo fetch 同一事实**(抓多个一手页对照)。别指望 WebSearch 兜底。

## 例外——单点事实查询

答案能在一条 snippet 内闭合、不交叉比对、不写进有引用的回答(如"今天 xx 价格多少""xx 发售了吗""xx 现在是什么版本号")。这类 keenable 单飞即可。判断标准看查询形状(单点事实 vs 多源综合),不看"会不会引用"——查询时无法预知最终是否引用。

## 默认链(凡要写进回答、要引用、要对比多源的 web 查询)

1. 发现(按查询形状选):
   - **wigolo 路(默认):** 先 `cache`(查本地,命中免费)→ 未命中跑 `search`(多关键词变体,结果带引用且落缓存)。
   - **keenable 路(新鲜度导向时补):** `search_web_pages` 补召回+新鲜度+厚 snippet,收集 URL + 发布日期。keenable 的 URL 稍后必须 wigolo `fetch` 落库才能引用。
   wigolo 强在可引用+缓存复用,keenable 强在新鲜度+召回;新鲜度查询两路都跑,静态调研 wigolo 为主。
2. 对每个值得用的 URL → `mcp__wigolo__fetch` 落本地缓存(keenable 发现的 URL 尤其要 fetch,它瞬时无引用)。
3. 所有引用/复用走 wigolo cache(带 `citation_id` + `source_span`)。绝不引用 keenable 的瞬时 snippet。

已有明确 URL 或重查旧题:跳过发现,直接 wigolo `cache`(命中免费)→ `fetch`(未命中补抓)。

## 为什么这么分

- **实测(2026-09-09,10 路并行压测,经 4 轮措辞迭代):** GitHub 查询走 `gh` 的 agent(归档工具、封号报告)产出最扎实,无需通用搜索;新鲜度查询不跑 keenable 的 agent 只剩 wigolo 单源,漏新鲜度——但 skill 写"keenable 必跑"也没能管住(4 轮措辞均失败),agent 是否跑 keenable 是概率性的,非措辞可控。内置 WebSearch 在本机全程返回兜底提示,不可用。
- **2026-09-07 实测:** 同一查询 "Anthropic Claude latest model release 2026",wigolo 5 条结果 4 条偏离,keenable 5 条全是当周新闻直击要点。keenable 胜在召回+新鲜度,wigolo 胜在可审计性(评分、citation、缓存)。互补,不冗余。
- **取舍:** 放弃"keenable 必跑"铁律(管不住,强行写只产生不实承诺),保留"引用落库"为唯一硬约束(这条实测稳定执行)。keenable 降为新鲜度导向查询的首选建议,agent 主动用更好,不用也不算 skill 失职。
