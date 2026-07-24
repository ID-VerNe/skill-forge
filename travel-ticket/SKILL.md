export const meta = {
  name: 'travel-ticket',
  description: '查火车票和机票。火车票：余票、票价、中转换乘、车站搜索、经停站。机票：航班价格、时刻、机型、碳排放。支持单程/往返。',
  metadata: { requires: [python] },
};

# 出行票务查询 Skill

> 整合火车票 (12306) + 机票 (Google Flights) 查询，一口令查所有出行方式。

---

## 使用方式

### 在 Claude Code 中

```
/travel-ticket train query 深圳 上海 2026-07-25
/travel-ticket flight search SZX PVG 2026-07-28
/travel-ticket flight roundtrip SZX PVG 2026-07-28 2026-08-01
/travel-ticket query 深圳 上海 2026-07-25
/travel-ticket search 深圳 上海浦东 2026-07-28
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
python travel.py flight roundtrip SZX PVG 2026-07-28 2026-08-01
python travel.py flight airlines

# 快捷方式
python travel.py query 深圳 上海 2026-07-25        # = train query
python travel.py search SZX PVG 2026-07-28         # = flight search
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
| `flight search <from> <to> <date>` | 出发机场/到达机场/日期 | 查询单程航班（价格、时刻、机型、碳排放） |
| `flight roundtrip <from> <to> <depart> <return>` | 往返日期 | 查询往返航班总价 |
| `flight airlines` | - | 列出航空公司代码对照表 |

### flight 选项

| 选项 | 值 | 说明 |
|------|-----|------|
| `--seat` | `economy` / `premium-economy` / `business` / `first` | 舱位（默认 economy） |
| `--passengers` | 数字 | 乘客数（默认 1） |

### 快捷方式

| 命令 | 等价于 | 说明 |
|------|--------|------|
| `query <from> <to> <date>` | `train query ...` | 查火车票 |
| `search <from> <to> <date>` | `flight search ...` | 查机票 |
| `airlines` | `flight airlines` | 航空公司代码 |

---

## 安装

```bash
pip install mcp-server-12306 fast-flights
```

---

## 数据来源

### 火车票
- 数据来源：**12306 官方 API**（`kyfw.12306.cn/otn/leftTicket/queryI`）
- 库：`mcp-server-12306`
- 自动处理 302 重定向 + 浏览器模拟请求头

### 机票
- 数据来源：**Google Flights**（`www.google.com/travel/flights`）
- 库：`fast-flights` v3.0.2
- 价格单位为人民币元（CNY），碳排放单位为 kg CO₂

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
2. 机票查询依赖 Google Flights，中国大陆网络环境可能需要代理
3. 机票价格仅供参考，实际价格以航司和购票平台为准
4. 中转换乘结果显示 `transfer at 武汉-汉口` 表示需在武汉站与汉口站之间换乘（地铁约 40 分钟）
5. 本 skill 仅供学习研究使用

## 已知问题

- `fast-flights v3.0.2` 解析器有空价格数组 bug，本工具已内置补丁自动跳过无价格条目
- 往返查询暂只显示去程航班详情，返程航班信息在 Google Flights 数据中但解析方式不同