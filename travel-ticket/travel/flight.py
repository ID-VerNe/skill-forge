"""机票查询模块 — 直连 Kiwi.com GraphQL API (api.skypicker.com)

数据来源：Kiwi.com 前端调用的公开 GraphQL 端点，无需鉴权、无需代理。
单程走 onewayItineraries，往返走 returnItineraries（含 outbound + inbound），
机场/城市搜索走 places。
"""

import json
import re
import urllib.error
import urllib.request

from .utils import (
    CURRENCY_MAP,
    fmt_duration,
    fmt_iso_datetime,
    get_airline_name,
    resolve_airport,
)

AVAILABLE = True  # 机票查询仅依赖标准库，永远可用

# ── 机型查询：curl_cffi 可选依赖 ──────────────────────────────────
# FlightRadar24 用 Cloudflare 反爬，标准库 urllib 会被 403 挡在挑战页。
# curl_cffi 模拟 Chrome 的 TLS 指纹能过。未安装时机型标 N/A，不阻断主流程。
try:
    from curl_cffi import requests as _cf_requests
    _CF_AVAILABLE = True
except ImportError:
    _CF_AVAILABLE = False

# ── GraphQL 端点 ──────────────────────────────────────────────────
_API_BASE = "https://api.skypicker.com/umbrella/v2/graphql"

_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.kiwi.com",
    "Referer": "https://www.kiwi.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
}

# ── 查询模板 ──────────────────────────────────────────────────────
# 注意：query 文本里的变量名 ($search/$filter/$options) 必须与 variables
# dict 的 key 完全一致，否则 Kiwi 静默返回 AppError('search' field is mandatory)。
# Sector 内部字段（不含外层 sector/outbound/inbound 包装）。
# 单程: itinerary.sector 是 Sector 字段 → 用 `sector { %s }`
# 往返: outbound/inbound 本身就是 Sector → 直接用 `%s`
_SECTOR_INNER = """\
sectorSegments {
  segment {
    source { station { code name city { name } } localTime }
    destination { station { code name city { name } } localTime }
    duration
    type
    code
    carrier { code name }
    operatingCarrier { code name }
  }
  layover { duration isStationChange isBaggageRecheck }
}"""

_ONEWAY_QUERY = """\
query($search: SearchOnewayInput, $filter: ItinerariesFilterInput, $options: ItinerariesOptionsInput) {
  onewayItineraries(search: $search, filter: $filter, options: $options) {
    __typename
    ... on Itineraries {
      itineraries {
        ... on ItineraryOneWay {
          id
          price { amount roundedFormattedValue currency { code } }
          duration
          sector { %s }
        }
      }
    }
    ... on AppError { error: message }
  }
}
""" % _SECTOR_INNER

_RETURN_QUERY = """\
query($search: SearchReturnInput, $filter: ItinerariesFilterInput, $options: ItinerariesOptionsInput) {
  returnItineraries(search: $search, filter: $filter, options: $options) {
    __typename
    ... on Itineraries {
      itineraries {
        ... on ItineraryReturn {
          id
          price { amount roundedFormattedValue currency { code } }
          duration
          outbound { %s }
          inbound { %s }
        }
      }
    }
    ... on AppError { error: message }
  }
}
""" % (_SECTOR_INNER, _SECTOR_INNER)

_PLACES_QUERY = """\
query($search: PlacesSearchInput) {
  places(search: $search) {
    __typename
    ... on PlaceConnection {
      edges {
        node {
          __typename
          id
          name
          slug
          rank
          ... on City { code airportsCount country { code name } }
          ... on Station { code city { id name } country { code name } }
          ... on Country { code }
        }
      }
    }
  }
}
"""


# ── HTTP 层 ───────────────────────────────────────────────────────

def _post(query: str, variables: dict, feature: str) -> dict:
    """POST GraphQL 请求，返回解析后的 dict。"""
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    url = f"{_API_BASE}?featureName={feature}"
    req = urllib.request.Request(url, data=body, headers=_HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        # 4xx：读 body 里的 GraphQL errors
        try:
            err_body = e.read().decode("utf-8", "replace")
            parsed = json.loads(err_body)
            msg = parsed.get("errors", [{}])[0].get("message", err_body)
        except (ValueError, json.JSONDecodeError):
            msg = f"HTTP {e.code}"
        raise RuntimeError(f"Kiwi API 错误: {msg}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}") from None


# ── 变量构造 ──────────────────────────────────────────────────────

def _passengers(adults: int) -> dict:
    return {
        "adults": adults, "children": 0, "infants": 0,
        "adultsHoldBags": [0] * adults, "adultsHandBags": [0] * adults,
        "childrenHoldBags": [], "childrenHandBags": [],
    }


def _cabin_class(seat: str) -> dict:
    # 本 skill 用的 seat 名 (economy/premium-economy/business/first) → Kiwi enum
    mapping = {
        "economy": "ECONOMY", "premium-economy": "PREMIUM_ECONOMY",
        "premium_economy": "PREMIUM_ECONOMY", "premium": "PREMIUM_ECONOMY",
        "business": "BUSINESS", "first": "FIRST_CLASS",
    }
    return {"cabinClass": mapping.get(seat, "ECONOMY"), "applyMixedClasses": False}


def _filter(stops: int, sort: str, limit: int = 15) -> dict:
    return {
        "maxStopsCount": stops,
        "transportTypes": ["FLIGHT"],
        "contentProviders": ["KIWI", "FRESH"],
        "flightsApiLimit": 25,
        "limit": limit,
    }


def _options(currency: str, sort: str) -> dict:
    cur = currency.lower()
    cm = CURRENCY_MAP.get(cur, CURRENCY_MAP["cny"])
    return {
        "sortBy": sort.upper(),
        "mergePriceDiffRule": "INCREASED",
        "contentProviders": ["KIWI", "FRESH"],
        "currency": cur,
        "locale": cm["locale"],
        "market": cm["market"],
        "partner": "skypicker",
        "partnerMarket": cm["partner_market"],
        "affilID": "skypicker",
        "storeSearch": False,
        "searchStrategy": "REDUCED",
    }


def _date_range(date: str) -> dict:
    """'2026-11-20' → {start,end} 当天 00:00 - 23:59:59"""
    return {"start": f"{date}T00:00:00", "end": f"{date}T23:59:59"}


# ── 查询函数 ──────────────────────────────────────────────────────

def search_oneway(from_id: str, to_id: str, date: str = "",
                  seat: str = "economy", adults: int = 1,
                  stops: int = 2, sort: str = "QUALITY",
                  currency: str = "cny") -> list:
    """单程查询，返回 itinerary 列表。date 为空时查任意时间（最便宜的未来航班）。"""
    itinerary = {
        "source": {"ids": [from_id]},
        "destination": {"ids": [to_id]},
    }
    if date and date.lower() != "anytime":
        itinerary["outboundDepartureDate"] = _date_range(date)

    variables = {
        "search": {
            "itinerary": itinerary,
            "passengers": _passengers(adults),
            "cabinClass": _cabin_class(seat),
        },
        "filter": _filter(stops, sort),
        "options": _options(currency, sort),
    }
    result = _post(_ONEWAY_QUERY, variables, "SearchOneWayItinerariesQuery")
    data = result["data"]["onewayItineraries"]
    if data.get("__typename") == "AppError":
        raise RuntimeError(f"Kiwi 查询失败: {data.get('error', '未知错误')}")
    return data.get("itineraries", [])


def search_roundtrip(from_id: str, to_id: str, depart_date: str, return_date: str,
                     seat: str = "economy", adults: int = 1,
                     stops: int = 2, sort: str = "QUALITY",
                     currency: str = "cny") -> list:
    """往返查询，返回 itinerary 列表（含 outbound + inbound 完整航班）。"""
    variables = {
        "search": {
            "itinerary": {
                "source": {"ids": [from_id]},
                "destination": {"ids": [to_id]},
                "outboundDepartureDate": _date_range(depart_date),
                "inboundDepartureDate": _date_range(return_date),
            },
            "passengers": _passengers(adults),
            "cabinClass": _cabin_class(seat),
        },
        "filter": _filter(stops, sort),
        "options": _options(currency, sort),
    }
    result = _post(_RETURN_QUERY, variables, "SearchReturnItinerariesQuery")
    data = result["data"]["returnItineraries"]
    if data.get("__typename") == "AppError":
        raise RuntimeError(f"Kiwi 查询失败: {data.get('error', '未知错误')}")
    return data.get("itineraries", [])


def search_places(term: str) -> list:
    """机场/城市搜索，返回 Place 节点列表。"""
    variables = {"search": {"term": term}}
    result = _post(_PLACES_QUERY, variables, "PlacesQuery")
    places = result["data"]["places"]
    if places.get("__typename") != "PlaceConnection":
        return []
    return [e["node"] for e in places.get("edges", []) if e.get("node")]


# ── 机型查询（FlightRadar24，经 curl_cffi 过 Cloudflare） ──────────

# ICAO 机型代码（执行过的航班 FR24 渲染为 "A333 (B-303N)"）。
# 不匹配 "A330-300" 这类带连字符的变体名——只要干净的 ICAO 代码。
_ICAO_CLASS = (
    r"(?:A3(?:10|19|2[0-9]|3[0-3]|8[0-2])"
    r"|B7(?:2[0-9]|3[0-7]|4[0-8]|5[0-7]|6[0-7]|[78][0-9])"
    r"|A35[0-9]|A38[0-2]|E7[0-9]|E9\d|DH8\d?|AT7[25]?|CRJ\d?|SU9|AR8|SB[23])"
)
# "ICAO" 或 "ICAO (registration)" — 负向先行断言排除 A330-300 这类变体
_ICAO_PAIR_RE = re.compile(
    rf"\b({_ICAO_CLASS})(?!\d)(?!\-)"
    r"(?:\s*\(\s*([^)\s]+)\s*\))?"
)
# 兜底注册号匹配（中国 B- 前缀为主，含国际常见前缀）
_REG_RE = re.compile(
    r"\b(B-\d{3,4}[A-Z]{0,3}|B-[A-Z]{2}\d{2,3}|N\d{2,5}[A-Z]{0,2}"
    r"|A6-[A-Z]{3}|G-[A-Z0-9]{4,5}|9V-[A-Z]{2,3}|PH-[A-Z0-9]{3}|VH-[A-Z0-9]{3})\b"
)

# 机型缓存：(carrier_iata, flight_no) -> (icao, registration) 或 (None, None)
# 一次查询里同一航班号多次出现只请求一次；进程级缓存跨多次调用。
_aircraft_cache: dict = {}


def _fetch_aircraft(carrier_iata: str, flight_no: str):
    """查 FR24 航班页，返回 (icao_code, registration) 或 (None, None)。

    优先取最近一班已执行（Landed）记录 —— 有注册号、机型确定。
    全是 Scheduled（未来排班）时取首个 ICAO（无注册号）。
    FR24 无此航班 / 网络失败 / curl_cffi 未装 → (None, None)。
    """
    key = (carrier_iata.upper(), flight_no.upper())
    if key in _aircraft_cache:
        return _aircraft_cache[key]

    if not _CF_AVAILABLE:
        _aircraft_cache[key] = (None, None)
        return (None, None)

    slug = f"{carrier_iata.lower()}{flight_no.lower()}"
    url = f"https://www.flightradar24.com/data/flights/{slug}"
    try:
        r = _cf_requests.get(url, impersonate="chrome", timeout=20)
        if r.status_code != 200:
            _aircraft_cache[key] = (None, None)
            return (None, None)
        html = r.text
    except Exception:
        _aircraft_cache[key] = (None, None)
        return (None, None)

    # 去标签，压空白，便于在整行文本里搜 "ICAO (reg)" 对
    flat = re.sub(r"<[^>]+>", " ", html)
    flat = re.sub(r"\s+", " ", flat)

    icao = None
    reg = None
    # 优先：含 "Landed" 的片段里找 ICAO+reg 对
    for chunk in re.split(r"(?=Landed)", flat):
        if "Landed" not in chunk:
            continue
        m = _ICAO_PAIR_RE.search(chunk)
        if m:
            icao = m.group(1)
            reg = m.group(2)
            if not reg:
                rm = _REG_RE.search(chunk)
                if rm:
                    reg = rm.group(1)
            break
    # 回退：整页找任意 ICAO（未来排班只有 ICAO 无注册号）
    if not icao:
        m = _ICAO_PAIR_RE.search(flat)
        if m:
            icao = m.group(1)
            reg = m.group(2)

    _aircraft_cache[key] = (icao, reg)
    return (icao, reg)


# ── 输出命令 ──────────────────────────────────────────────────────

def _print_header(label: str, detail: str):
    print(f"\n{'='*70}")
    print(f"  {label}: {detail}")
    print(f"{'='*70}")


def _format_segment(seg: dict) -> str:
    """单段航班: 'CAN 11-20 03:20 → MEL 11-20 00:10  AK113 [A333 B-303N]  4h20m'"""
    src = seg["source"]
    dst = seg["destination"]
    src_code = src["station"]["code"]
    dst_code = dst["station"]["code"]
    dep = fmt_iso_datetime(src.get("localTime", ""))
    arr = fmt_iso_datetime(dst.get("localTime", ""))
    carrier = seg.get("carrier", {})
    carrier_code = carrier.get("code", "")
    carrier_name = get_airline_name(carrier_code) if carrier_code else ""
    flight_no = seg.get("code", "")
    airline_str = f"{carrier_code} ({carrier_name})" if carrier_name else carrier_code
    flight_str = f"{airline_str} {flight_no}".strip()

    # 机型（FR24 查询，可选）
    ac_icao, ac_reg = _fetch_aircraft(carrier_code, flight_no)
    if ac_icao:
        ac_str = f"[{ac_icao}"
        if ac_reg:
            ac_str += f" {ac_reg}"
        ac_str += "]"
    else:
        ac_str = "[机型N/A]"
    flight_str = f"{flight_str}  {ac_str}"

    dur = fmt_duration(seg.get("duration", 0))
    return f"{src_code} {dep} → {dst_code} {arr}  {dur:>7s}  {flight_str}"


def _format_sector(sector: dict, prefix: str = ""):
    """打印一个 sector 内所有航段 + 中转停留。"""
    segs = sector.get("sectorSegments", [])
    for i, ss in enumerate(segs):
        seg = ss.get("segment", {})
        line = _format_segment(seg)
        print(f"  {prefix}{line}")
        layover = ss.get("layover")
        if layover and layover.get("duration"):
            flags = []
            if layover.get("isStationChange"):
                flags.append("换站")
            if layover.get("isBaggageRecheck"):
                flags.append("重取行李")
            tag = f"  [{'+'.join(flags)}]" if flags else ""
            print(f"  {prefix}    中转停留 {fmt_duration(layover['duration'])}{tag}")


def cmd_search(from_code: str, to_code: str, date: str,
              seat: str = "economy", passengers: int = 1,
              stops: int = 2, sort: str = "QUALITY", currency: str = "cny"):
    """查询单程航班"""
    f = resolve_airport(from_code)
    t = resolve_airport(to_code)
    date_label = date or "任意时间"
    _print_header("航班查询", f"{from_code} → {to_code}  {date_label}  {seat}  ≤{stops}中转  {sort}  {currency}")

    try:
        results = search_oneway(f, t, date, seat, passengers, stops, sort, currency)
    except RuntimeError as e:
        print(f"查询失败: {e}")
        return

    if not results:
        print("  未找到航班")
        return

    sorted_results = sorted(results, key=lambda x: int(x["price"].get("amount", 0)))
    first_price = sorted_results[0]["price"].get("roundedFormattedValue", "")
    print(f"  共 {len(results)} 个航班，价格从 {first_price} 起\n")

    for i, itin in enumerate(sorted_results, 1):
        price = itin["price"].get("roundedFormattedValue", "")
        dur = fmt_duration(itin.get("duration", 0))
        print(f"  {i:2d}. 总价 {price:>10s}  总时长 {dur:>7s}")
        _format_sector(itin.get("sector", {}))
        print()


def cmd_roundtrip(from_code: str, to_code: str, depart_date: str,
                  return_date: str, seat: str = "economy", passengers: int = 1,
                  stops: int = 2, sort: str = "QUALITY", currency: str = "cny"):
    """查询往返航班"""
    f = resolve_airport(from_code)
    t = resolve_airport(to_code)
    _print_header("往返查询", f"{from_code} → {to_code}  {depart_date} → {return_date}  {seat}  ≤{stops}中转  {currency}")

    try:
        results = search_roundtrip(f, t, depart_date, return_date,
                                   seat, passengers, stops, sort, currency)
    except RuntimeError as e:
        print(f"查询失败: {e}")
        return

    if not results:
        print("  未找到航班")
        return

    sorted_results = sorted(results, key=lambda x: int(x["price"].get("amount", 0)))
    first_price = sorted_results[0]["price"].get("roundedFormattedValue", "")
    print(f"  共 {len(results)} 个往返方案，价格从 {first_price} 起\n")

    for i, itin in enumerate(sorted_results, 1):
        price = itin["price"].get("roundedFormattedValue", "")
        dur = fmt_duration(itin.get("duration", 0))
        print(f"  {i:2d}. 总价 {price:>10s}  总时长 {dur:>7s}")
        outbound = itin.get("outbound", {})
        inbound = itin.get("inbound", {})
        print(f"      去程:")
        _format_sector(outbound, prefix="    ")
        print(f"      返程:")
        _format_sector(inbound, prefix="    ")
        print()


def cmd_airport(keyword: str):
    """搜索机场/城市"""
    _print_header("机场/城市搜索", keyword)
    try:
        nodes = search_places(keyword)
    except RuntimeError as e:
        print(f"查询失败: {e}")
        return

    if not nodes:
        print("  未找到匹配地点")
        return

    # 优先显示 City，再显示 Station；同类型按 rank 降序
    cities = [n for n in nodes if n.get("__typename") == "City"]
    stations = [n for n in nodes if n.get("__typename") == "Station"]
    others = [n for n in nodes if n.get("__typename") not in ("City", "Station")]

    def sort_key(n):
        return -(n.get("rank") or 0)

    cities.sort(key=sort_key)
    stations.sort(key=sort_key)

    if cities:
        print(f"\n  城市 ({len(cities)}):")
        for n in cities:
            code = n.get("code", "")
            airports = n.get("airportsCount", "")
            country = n.get("country", {})
            country_name = country.get("name", "") if country else ""
            print(f"    {n['id']:40s}  {code:4s}  机场数:{airports}  {n['name']}  ({country_name})")

    if stations:
        print(f"\n  机场 ({len(stations)}):")
        for n in stations:
            code = n.get("code", "")
            city = n.get("city", {}) or {}
            city_name = city.get("name", "") if city else ""
            country = n.get("country", {})
            country_name = country.get("name", "") if country else ""
            print(f"    {n['id']:40s}  {code:4s}  {n['name']}  ({city_name}, {country_name})")

    if others:
        print(f"\n  其他 ({len(others)}):")
        for n in others:
            print(f"    {n.get('__typename'):12s}  {n.get('id','')}  {n.get('name','')}")


def cmd_airlines():
    """列出已知航空公司代码"""
    from .utils import AIRLINE_NAMES
    print(f"\n{'='*60}")
    print("  航空公司代码对照表")
    print(f"{'='*60}")
    for code in sorted(AIRLINE_NAMES.keys()):
        print(f"  {code:4s}  {AIRLINE_NAMES[code]}")
