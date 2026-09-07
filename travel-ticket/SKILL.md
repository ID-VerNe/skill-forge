---
name: travel-ticket
description: 查火车票和机票。火车票：余票、票价、中转换乘、车站搜索、经停站。机票：航班价格、时刻、中转、往返、机场城市搜索。支持单程/往返、多币种、中转数与排序控制。
---

# 出行票务查询 Skill

> 整合火车票 (12306) + 机票 (Kiwi.com) 查询，一口令查所有出行方式。

---

## 使用方式

### 在 Claude Code 中

```
/travel-ticket train query 深圳 上海 2026-07-25
/travel-ticket flight search SZX PVG 2026-07-28
/travel-ticket flight search 广州 墨尔本 2026-11-20 --stops 1 --sort price
/travel-ticket flight search CAN MEL anytime              # 任意时间最便宜
/travel-ticket flight roundtrip SZX PVG 2026-07-28 2026-08-01
/travel-ticket flight airport melbourne                   # 机场/城市搜索
/travel-ticket query 深圳 上海 2026-07-25
/travel-ticket search 广州 墨尔本 2026-11-20
```

### 命令行直接调用

```bash
# 火车票
python travel.py train query 深圳 上海 2026-07-25
python travel.py train transfer 深圳 上海 2026-07-25 --via 南昌
python travel.py train station 深圳
python travel.py train route G2790 深圳 上海虹桥 2026-07-25

# 机票
python travel.py flight search SZX PVG 2026-07-28
python travel.py flight search 深圳 上海浦东 2026-07-28 --seat business
python travel.py flight search 广州 墨尔本 2026-11-20 --stops 1 --sort price
python travel.py flight search CAN MEL anytime --currency eur
python travel.py flight roundtrip SZX PVG 2026-07-28 2026-08-01
python travel.py flight airport melbourne
python travel.py flight airlines

# 快捷方式
python travel.py query 深圳 上海 2026-07-25        # = train query
python travel.py search CAN MEL 2026-11-20         # = flight search
```

---

## 命令一览

### 火车票 (train)

| 命令 | 参数 | 说明 |
|------|------|------|
| `train query <from> <to> <date>` | 出发站/到达站/日期 | 查询余票 + 票价 + 时刻 |
| `train price <from> <to> <date>` | 同上 | 查询各车次票价 |
| `train transfer <from> <to> <date>` | 同上 | 中转换乘方案（余票+票价） |
| `train transfer ... --via <station>` | 指定中转站 | 指定中转站换乘 |
| `train station <keyword>` | 关键词 | 搜索车站（中/拼/简拼/三字码） |
| `train route <code> <from> <to> <date>` | 车次/站/日 | 列车经停站时刻表 |

### 机票 (flight)

| 命令 | 参数 | 说明 |
|------|------|------|
| `flight search <from> <to> [date]` | 出发机场/到达机场/日期 | 查询单程航班（价格、时刻、中转、航司） |
| `flight roundtrip <from> <to> <depart> <return>` | 往返日期 | 查询往返航班（去程+返程完整航班） |
| `flight airport <keyword>` | 关键词 | 搜索机场/城市（中文名/拼音/IATA） |
| `flight airlines` | - | 列出航空公司代码对照表 |

### flight 选项

| 选项 | 值 | 说明 |
|------|-----|------|
| `--seat` | `economy` / `premium-economy` / `business` / `first` | 舱位（默认 economy） |
| `--passengers` | 数字 | 乘客数（默认 1） |
| `--stops` | 数字 | 最大中转数（默认 2，0 = 仅直达） |
| `--sort` | `quality` / `price` / `duration` / `date` | 排序（默认 quality） |
| `--currency` | `cny` / `usd` / `eur` / `gbp` / `aud` / `jpy` / `hkd` / `sgd` | 币种（默认 cny） |

### 日期与任意时间

`flight search` 的 `date` 参数可选：
- 指定日期（`2026-11-20`）：查当天航班
- 省略或 `anytime`：查未来最便宜的航班（Kiwi 跨数月搜索）

### 快捷方式

| 命令 | 等价于 | 说明 |
|------|--------|------|
| `query <from> <to> <date>` | `train query ...` | 查火车票 |
| `search <from> <to> [date]` | `flight search ...` | 查机票 |
| `airlines` | `flight airlines` | 航空公司代码 |

---

## 安装

```bash
pip install mcp-server-12306        # 火车票（12306 官方 API）
# 机票模块仅依赖 Python 标准库，无需额外安装
```

---

## 数据来源

### 火车票
- 数据来源：**12306 官方 API**（`kyfw.12306.cn/otn/leftTicket/queryI`）
- 库：`mcp-server-12306`
- 自动处理 302 重定向 + 浏览器模拟请求头

### 机票
- 数据来源：**Kiwi.com GraphQL API**（`api.skypicker.com/umbrella/v2/graphql`）
- 查询：`SearchOneWayItinerariesQuery`（单程）、`SearchReturnItinerariesQuery`（往返）、`PlacesQuery`（机场搜索）
- 直连，无需鉴权、无需代理，仅用 Python 标准库 `urllib`
- 支持中转、自转、隐藏城市等 Kiwi 全部结果类型
- 价格含币种符号，时长单位为分钟（由秒换算）

---

## 机场代码（常用）

| 中文名 | IATA |
|--------|------|
| 深圳宝安 | SZX |
| 上海浦东 | PVG |
| 上海虹桥 | SHA |
| 北京首都 | PEK |
| 北京大兴 | PKX |
| 广州白云 | CAN |
| 成都双流/天府 | CTU / TFU |
| 杭州萧山 | HGH |
| 武汉天河 | WUH |
| 重庆江北 | CKG |
| 南京禄口 | NKG |
| 厦门高崎 | XMN |
| 三亚凤凰 | SYX |
| 昆明长水 | KMG |
| 西安咸阳 | XIY |
| 香港国际 | HKG |
| 墨尔本 | MEL |
| 悉尼 | SYD |
| 东京 | HND / NRT |
| 新加坡 | SIN |
| 曼谷 | BKK |
| 吉隆坡 | KUL |
| 首尔仁川 | ICN |
| 巴黎 | CDG |
| 伦敦 | LHR |
| 纽约 | JFK |
| 洛杉矶 | LAX |

## 火车站代码（常用）

| 车站 | 三字码 |
|------|--------|
| 深圳 | SZQ |
| 深圳北 | IOQ |
| 福田 | NZQ |
| 上海 | SHH |
| 上海虹桥 | AOH |
| 北京 | BJP |
| 北京南 | VNP |
| 广州南 | IZQ |
| 武汉 | WHN |
| 南昌 | NCG |

---

## 注意事项

1. 火车票查询日期范围：今天起 14 天内
2. 机票查询无日期限制，Kiwi 支持任意未来日期与跨月「任意时间」搜索
3. 机票价格仅供参考，实际价格以航司和购票平台为准
4. 中转停留标记「换站」表示需在不同机场/车站之间转移，「重取行李」表示需重新办理托运
5. `--stops 0` 仅查直达航班；Kiwi 的「自转」(self-transfer) 方案需自行确认签证与重取行李
6. 中文城市名搜索命中有限（如「墨尔本」「新加坡」可能 0 命中），建议用拼音或 IATA 三字码
7. 本 skill 仅供学习研究使用
