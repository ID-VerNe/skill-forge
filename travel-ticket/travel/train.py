"""火车票查询模块 — 基于 mcp-server-12306 库直连 12306 官方 API"""

import asyncio
import json
import sys

# ── 依赖检查 ──────────────────────────────────────────────────────
try:
    from mcp_12306.services.ticket_service import (
        query_tickets_validated,
        query_ticket_price_validated,
        query_transfer_validated,
        search_stations_validated,
        station_service,
        get_train_route_stations_validated,
    )
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from .utils import fmt_seats_compact, fmt_prices_compact


async def init():
    """初始化车站数据"""
    if AVAILABLE:
        await station_service.load_stations()


async def fetch_price_map(from_station: str, to_station: str, train_date: str) -> dict:
    """获取某线路的票价映射: {(train_code, from_station, to_station) -> {seat_type: price}}"""
    try:
        result = await query_ticket_price_validated({
            "from_station": from_station, "to_station": to_station,
            "train_date": train_date, "purpose_codes": "ADULT",
        })
        data = json.loads(result[0]["text"])
        if not data.get("success"):
            return {}
        pm = {}
        for t in data.get("data", []):
            pm[(t["train_code"], t["from_station"], t["to_station"])] = t.get("prices", {})
        return pm
    except Exception:
        return {}


async def cmd_query(from_station: str, to_station: str, train_date: str):
    """查询余票 + 票价"""
    ticket_result, price_result = await asyncio.gather(
        query_tickets_validated({
            "from_station": from_station, "to_station": to_station, "train_date": train_date,
        }),
        query_ticket_price_validated({
            "from_station": from_station, "to_station": to_station,
            "train_date": train_date, "purpose_codes": "ADULT",
        }),
    )

    data = json.loads(ticket_result[0]["text"])
    price_data = json.loads(price_result[0]["text"])

    if not data.get("success"):
        print(f"查询失败: {data.get('error', '未知错误')}")
        if data.get("suggestions"):
            for s in data["suggestions"]:
                for m in s.get("matches", []):
                    print(f"  建议: {m['name']} ({m['code']})")
        return

    price_map = {}
    if price_data.get("success"):
        for t in price_data.get("data", []):
            price_map[t["train_code"]] = t.get("prices", {})

    print(f"\n{'='*70}")
    print(f"  🚄 火车票: {from_station} → {to_station}  {train_date}")
    print(f"  共 {data.get('count', 0)} 个车次")
    print(f"{'='*70}")

    for t in data.get("trains", []):
        code = t["train_no"]
        seats_str = fmt_seats_compact(t.get("seats", {}))
        prices_str = fmt_prices_compact(price_map.get(code, {}))
        parts = [
            f"  {code:8s}  {t['from_station']:6s} {t['start_time']} → "
            f"{t['to_station']:8s} {t['arrive_time']}  {t['duration']}"
        ]
        if seats_str:
            parts.append(f"  余票: {seats_str}")
        if prices_str:
            parts.append(f"  票价: {prices_str}")
        print(" | ".join(parts))


async def cmd_price(from_station: str, to_station: str, train_date: str):
    """查询票价"""
    result = await query_ticket_price_validated({
        "from_station": from_station, "to_station": to_station,
        "train_date": train_date, "purpose_codes": "ADULT",
    })
    data = json.loads(result[0]["text"])
    if not data.get("success"):
        print(f"查询失败: {data.get('error', '未知错误')}")
        return

    print(f"\n{'='*60}")
    print(f"  票价查询: {from_station} → {to_station}  {train_date}")
    print(f"  共 {data.get('count', 0)} 个车次")
    print(f"{'='*60}")

    for t in data.get("data", []):
        prices = fmt_prices_compact(t.get("prices", {}))
        print(f"  {t['train_code']:8s}  {t['from_station']:6s} {t['start_time']} → "
              f"{t['to_station']:8s} {t['arrive_time']}  {t['duration']}  {prices}")


async def cmd_transfer(from_station: str, to_station: str, train_date: str, via: str = ""):
    """查询中转换乘（含余票 + 票价）"""
    args = {
        "from_station": from_station, "to_station": to_station,
        "train_date": train_date, "purpose_codes": "00",
    }
    if via:
        args["middle_station"] = via

    result = await query_transfer_validated(args)
    data = json.loads(result[0]["text"])
    if not data.get("success"):
        print(f"查询失败: {data.get('error', '未知错误')}")
        return

    transfers = data.get("transfers", [])[:10]
    route_pairs = set()
    for t in transfers:
        for seg in t.get("segments", []):
            route_pairs.add((seg["from_station"], seg["to_station"]))

    price_map_by_route = {}

    async def _fetch(f, t):
        m = await fetch_price_map(f, t, train_date)
        if m:
            price_map_by_route[(f, t)] = m

    if route_pairs:
        await asyncio.gather(*[_fetch(f, t) for f, t in route_pairs])

    print(f"\n{'='*70}")
    title = f"  🚄 中转换乘: {from_station} → {to_station}  {train_date}"
    if via:
        title += f"  via {via}"
    print(title)
    print(f"  共 {data.get('count', 0)} 个方案（显示前10个）")
    print(f"{'='*70}")

    for i, t in enumerate(transfers, 1):
        print(f"\n  ── 方案{i}: 中转 {t.get('middle_station')}  等候 "
              f"{t.get('wait_time')}  总耗时 {t.get('total_duration')} ──")
        for seg in t.get("segments", []):
            code = seg["train_code"]
            seats_str = fmt_seats_compact(seg.get("seats", {}))
            route_key = (seg["from_station"], seg["to_station"])
            prices = price_map_by_route.get(route_key, {}).get(
                (code, seg["from_station"], seg["to_station"]), {})
            prices_str = fmt_prices_compact(prices)

            parts = [f"    {code:8s}  {seg['from_station']:6s} {seg['start_time']} → "
                     f"{seg['to_station']:8s} {seg['arrive_time']}  {seg['duration']}"]
            if seats_str:
                parts.append(f"  余票: {seats_str}")
            if prices_str:
                parts.append(f"  票价: {prices_str}")
            print(" | ".join(parts))


async def cmd_station(keyword: str):
    """搜索车站"""
    result = await search_stations_validated({"query": keyword, "limit": 15})
    data = json.loads(result[0]["text"])
    if not data.get("success"):
        print(f"未找到匹配: {keyword}")
        return

    print(f"\n{'='*60}")
    print(f"  车站搜索: {keyword}")
    print(f"  共 {data.get('count', 0)} 个结果")
    print(f"{'='*60}")

    for s in data.get("stations", []):
        city = f" [{s.get('city', '')}]" if s.get('city') else ""
        print(f"  {s['name']:8s}  {s['code']}  {s['pinyin']} ({s['py_short']}){city}")


async def cmd_route(train_code: str, from_station: str, to_station: str, train_date: str):
    """查询列车经停站"""
    try:
        from mcp_12306.services.ticket_service import get_train_route_stations_validated
    except ImportError:
        return
    result = await get_train_route_stations_validated({
        "train_no": train_code, "from_station": from_station,
        "to_station": to_station, "train_date": train_date,
    })
    data = json.loads(result[0]["text"])
    if not data.get("success"):
        print(f"查询失败: {data.get('error', '未知错误')}")
        return

    print(f"\n{'='*60}")
    print(f"  {train_code} 经停站  {train_date}")
    print(f"{'='*60}")

    for s in data.get("stations", []):
        arrive = s.get("arrive_time", "----")
        depart = s.get("start_time", "----")
        stay = s.get("stopover_time", "")
        stay_str = f" 停{stay}" if stay else ""
        print(f"  {s['station_no']:3s}  {s['station_name']:8s}  {arrive} → {depart}{stay_str}")