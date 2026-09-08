# travel-ticket — 出行票务查询

> 整合火车票 (12306) + 机票 (Kiwi.com) 查询，一口令查所有出行方式。机票直连 Kiwi GraphQL、无需代理，机型经 FlightRadar24 补全。

## 数据来源

| 域 | 来源 | 接入方式 | 依赖 |
|----|------|---------|------|
| 火车票 | 12306 官方 API（`kyfw.12306.cn`）| `mcp-server-12306` 库，自动 302 重定向 + 浏览器 UA | `mcp-server-12306` |
| 机票 | Kiwi.com GraphQL（`api.skypicker.com/umbrella/v2/graphql`）| 标准库 `urllib` 直连，无鉴权、无代理 | 仅标准库 |
| 机型 | FlightRadar24（`flightradar24.com/data/flights/`）| `curl_cffi` 模拟 Chrome TLS 指纹过 Cloudflare | `curl_cffi`（可选）|

Kiwi GraphQL 端点公开，三种查询：
- `SearchOneWayItinerariesQuery` → 单程
- `SearchReturnItinerariesQuery` → 往返（outbound + inbound 完整航班）
- `PlacesQuery` → 机场/城市搜索

机型查询为可选能力：`curl_cffi` 未安装或 FR24 无记录时，机型标 `N/A`，不阻断主流程。

## 结构

```
travel-ticket/
├── travel.py              # CLI 入口（火车票 + 机票命令路由）
├── SKILL.md               # Claude Code skill 定义（命令一览、用法、选项）
├── README.md              # 本文件
└── travel/
    ├── __init__.py
    ├── train.py           # 火车票：query/price/transfer/station/route（12306）
    ├── flight.py          # 机票：oneway/roundtrip/airport + 机型查询（Kiwi + FR24）
    └── utils.py           # 机场别名、航司表、币种映射、格式化函数
```

## 安装

```bash
pip install mcp-server-12306     # 火车票（必需）
pip install curl_cffi            # 机型查询（可选，无则机型标 N/A）
# 机票主流程仅依赖 Python 标准库，无需额外安装
```

## 使用

### 命令行

```bash
# 火车票
python travel.py train query 深圳 上海 2026-07-25
python travel.py train transfer 深圳 上海 2026-07-25 --via 南昌
python travel.py train station 深圳
python travel.py train route G2790 深圳 上海虹桥 2026-07-25

# 机票
python travel.py flight search SZX PVG 2026-07-28
python travel.py flight search 广州 墨尔本 2026-11-20 --stops 1 --sort price
python travel.py flight search CAN MEL anytime              # 任意时间最便宜
python travel.py flight search CAN MEL 2026-11-20 --currency eur
python travel.py flight roundtrip SZX PVG 2026-07-28 2026-08-01
python travel.py flight airport melbourne
python travel.py flight airlines

# 快捷方式
python travel.py query 深圳 上海 2026-07-25        # = train query
python travel.py search CAN MEL 2026-11-20         # = flight search
```

### Claude Code 中

通过 skill junction 到 `~/.claude/skills/` 后，用 `/travel-ticket` 调用：

```
/travel-ticket train query 深圳 上海 2026-07-25
/travel-ticket flight search 广州 墨尔本 2026-11-20 --stops 1 --sort price
/travel-ticket flight search CAN MEL anytime
/travel-ticket flight roundtrip SZX PVG 2026-07-28 2026-08-01
/travel-ticket flight airport melbourne
```

## 命令一览

### 火车票 (train)

| 命令 | 说明 |
|------|------|
| `train query <from> <to> <date>` | 余票 + 票价 + 时刻 |
| `train price <from> <to> <date>` | 各车次票价 |
| `train transfer <from> <to> <date> [--via X]` | 中转换乘方案 |
| `train station <keyword>` | 搜索车站（中/拼/简拼/三字码） |
| `train route <code> <from> <to> <date>` | 列车经停站时刻表 |

### 机票 (flight)

| 命令 | 说明 |
|------|------|
| `flight search <from> <to> [date]` | 单程航班（价格、时刻、中转、机型） |
| `flight roundtrip <from> <to> <depart> <return>` | 往返航班（去程+返程完整） |
| `flight airport <keyword>` | 搜索机场/城市 |
| `flight airlines` | 航空公司代码对照表 |

### flight 选项

| 选项 | 值 | 说明 |
|------|-----|------|
| `--seat` | `economy` / `premium-economy` / `business` / `first` | 舱位（默认 economy） |
| `--passengers` | 数字 | 乘客数（默认 1） |
| `--stops` | 数字 | 最大中转数（默认 2，0 = 仅直达） |
| `--sort` | `quality` / `price` / `duration` / `date` | 排序（默认 quality） |
| `--currency` | `cny` / `usd` / `eur` / `gbp` / `aud` / `jpy` / `hkd` / `sgd` | 币种（默认 cny） |

`date` 省略或写 `anytime` 时，查未来最便宜的航班（Kiwi 跨数月搜索）。

## 输出示例

```
======================================================================
  航班查询: 广州 → 墨尔本  2026-11-20  economy  ≤1中转  price  cny
======================================================================
  共 15 个航班，价格从 ¥2,225 起

   1. 总价     ¥2,225  总时长  17h50m
  CAN 11-20 03:20 → MNL 11-20 06:30    3h10m  5J (宿务太平洋) 287  [A333]
  MNL 11-20 12:55 → MEL 11-21 00:10    8h15m  5J (宿务太平洋) 49  [A333]
      中转停留 6h25m
```

机型以 ICAO 代码显示（如 `A333` = 空客 A330-300、`B789` = 波音 787-9），已执行航班附注册号（如 `[B789 9V-OJG]`）。

## 技术细节

### Kiwi GraphQL 变量名对齐

query 文本里的变量名（`$search`/`$filter`/`$options`）必须与 variables dict 的 key 完全一致，否则 Kiwi 静默返回 `AppError: 'search' field is mandatory.`（变量被解析为 null）。代码里统一用长名。

### 城市与机场 id

`resolve_airport()` 返回 Kiwi id：
- 中文名/别名 → `City:guangzhou_cn`（含周边机场）
- 三字 IATA → `Station:airport:CAN`

两者 Kiwi 都接受。中文城市名搜索命中有限（如「墨尔本」「新加坡」可能 0 命中），建议用拼音或 IATA。

### 时长单位

Kiwi 返回秒，`fmt_duration()` 自动识别：≥1000 视为秒（Kiwi 航班时长），否则视为分钟（12306）。

### 机型查询缓存

`_fetch_aircraft()` 以 `(carrier_iata, flight_no)` 为 key 进程级缓存，同一航班号在一次查询里多次出现只请求 FR24 一次。

## 限制

- 火车票查询日期范围：今天起 14 天内（12306 限制）
- 机票无日期限制，Kiwi 支持任意未来日期与跨月「任意时间」搜索
- 机型覆盖：FR24 对中国国内航司（ZH/CZ）和国际主流航司（HX/TR/VJ/AK）有数据；部分支线/代码共享航班（如 5J289、SQ857）查不到，标 N/A
- 机票价格仅供参考，实际以航司和购票平台为准
- 中转停留标记「换站」表示需在不同机场/车站转移，「重取行李」表示需重新办理托运

## License

MIT
