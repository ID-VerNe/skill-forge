"""机票查询模块 — 基于 fast-flights 库，直连 Google Flights 获取实时航班数据"""

import sys

# ── 依赖检查 ──────────────────────────────────────────────────────
try:
    from fast_flights import FlightQuery, Passengers, create_query
    from fast_flights import parser as fast_flights_parser
    from fast_flights.parser import (
        Flights, ResultList, SingleFlight, Airport,
        JsMetadata, Alliance, Airline, CarbonEmission, SimpleDatetime,
    )
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from .utils import (
    resolve_airport, fmt_time, fmt_date, fmt_duration, fmt_price, get_airline_name,
)

# ── fast-flights v3.0.2 解析器补丁 ────────────────────────────────
# 某些航班条目（无价格数据）的 k[1][0] 是空列表，导致 IndexError
# 跳过这些条目，保留有价格的航班


def _install_patch():
    """安装解析器补丁，处理空价格数组条目"""
    if not AVAILABLE:
        return

    def _patched_parse_js(js: str):
        import json as _json
        data = js.split("data:", 1)[1].rsplit(",", 1)[0]
        if data.endswith("errorHasStatus: true"):
            from fast_flights.exceptions import FlightsNotFound
            raise FlightsNotFound("no flights found; received error")

        payload = _json.loads(data)
        alliances = []
        airlines = []
        if payload[7][1][0]:
            for code, name in payload[7][1][0]:
                alliances.append(Alliance(code=code, name=name))
        if payload[7][1][1]:
            for code, name in payload[7][1][1]:
                airlines.append(Airline(code=code, name=name))
        meta = JsMetadata(alliances=alliances, airlines=airlines)

        flights = ResultList()
        if payload[3][0] is None:
            return flights

        for k in payload[3][0]:
            try:
                flight = k[0]
                if not k[1] or not k[1][0] or len(k[1][0]) < 2:
                    continue
                price = k[1][0][1]
                typ = flight[0]
                airline_names = flight[1]
                sg_flights = []
                for single_flight in flight[2]:
                    sg_flights.append(SingleFlight(
                        from_airport=Airport(code=single_flight[3], name=single_flight[4]),
                        to_airport=Airport(code=single_flight[6], name=single_flight[5]),
                        departure=SimpleDatetime(date=single_flight[20], time=single_flight[8]),
                        arrival=SimpleDatetime(date=single_flight[21], time=single_flight[10]),
                        duration=single_flight[11], plane_type=single_flight[17],
                    ))
                extras = flight[22]
                flights.append(Flights(
                    type=typ, price=price, airlines=airline_names, flights=sg_flights,
                    carbon=CarbonEmission(typical_on_route=extras[8], emission=extras[7]),
                ))
            except (IndexError, TypeError, KeyError):
                continue
        flights.metadata = meta
        return flights

    fast_flights_parser.parse_js = _patched_parse_js


_install_patch()


# ── 查询函数 ──────────────────────────────────────────────────────

def search_flights(
    from_airport: str,
    to_airport: str,
    date: str,
    return_date: str = "",
    seat: str = "economy",
    adults: int = 1,
    currency: str = "CNY",
):
    """查询航班，返回 ResultList"""
    from fast_flights import get_flights as _get_flights

    flights_list = [FlightQuery(from_airport=from_airport, to_airport=to_airport, date=date)]
    trip = "one-way"
    if return_date:
        flights_list.append(
            FlightQuery(from_airport=to_airport, to_airport=from_airport, date=return_date),
        )
        trip = "round-trip"

    query = create_query(
        flights=flights_list, seat=seat, trip=trip,
        passengers=Passengers(adults=adults), currency=currency,
    )
    return _get_flights(query)


# ── 输出命令 ──────────────────────────────────────────────────────

def _print_header(label: str, detail: str):
    print(f"\n{'='*70}")
    print(f"  ✈️ {label}: {detail}")
    print(f"{'='*70}")


def _print_flight_list(results, show_price=True):
    """打印航班列表（通用）"""
    if not results:
        print("  未找到航班")
        return

    sorted_results = sorted(results, key=lambda x: x.price)
    print(f"  共 {len(results)} 个航班，价格从 {fmt_price(sorted_results[0].price)} 起\n")

    for i, flight in enumerate(sorted_results, 1):
        airline_code = flight.type
        known_name = get_airline_name(airline_code)
        if known_name:
            airline_str = f"{airline_code} ({known_name})"
        else:
            airline_str = f"{airline_code} ({flight.airlines[0] if flight.airlines else ''})"

        for j, sg in enumerate(flight.flights):
            dep_time = fmt_time(sg.departure.time)
            arr_time = fmt_time(sg.arrival.time)
            duration = fmt_duration(sg.duration)
            plane = sg.plane_type or ""

            if show_price:
                print(f"  {i:2d}. {airline_str:24s}  {sg.from_airport.code} {dep_time} → "
                      f"{sg.to_airport.code} {arr_time}  {duration:>6s}  "
                      f"{fmt_price(flight.price):>8s}  {plane}")
            else:
                print(f"  {i:2d}. {airline_str:24s}  {sg.from_airport.code} {dep_time} → "
                      f"{sg.to_airport.code} {arr_time}  {duration:>6s}  {plane}")

        if hasattr(flight, 'carbon') and flight.carbon.emission:
            print(f"     碳排放: {flight.carbon.emission/1000:.0f}kg CO₂ "
                  f"(航线平均 {flight.carbon.typical_on_route/1000:.0f}kg)")
        print()


def cmd_search(from_code: str, to_code: str, date: str,
               seat: str = "economy", passengers: int = 1):
    """查询单程航班"""
    f = resolve_airport(from_code)
    t = resolve_airport(to_code)
    _print_header("航班查询", f"{f} → {t}  {date}  {seat}")

    try:
        results = search_flights(f, t, date, seat=seat, adults=passengers)
    except Exception as e:
        print(f"查询失败: {e}")
        return

    _print_flight_list(results)


def cmd_roundtrip(from_code: str, to_code: str, depart_date: str,
                  return_date: str, seat: str = "economy"):
    """查询往返航班"""
    f = resolve_airport(from_code)
    t = resolve_airport(to_code)
    _print_header("往返查询", f"{f} → {t}  {depart_date} → {return_date}  {seat}")

    try:
        results = search_flights(f, t, depart_date, return_date=return_date, seat=seat)
    except Exception as e:
        print(f"查询失败: {e}")
        return

    if not results:
        print("  未找到航班")
        return

    sorted_results = sorted(results, key=lambda x: x.price)
    print(f"  共 {len(results)} 个往返方案，价格从 {fmt_price(sorted_results[0].price)} 起\n")

    for i, flight in enumerate(sorted_results, 1):
        airline_code = flight.type
        known_name = get_airline_name(airline_code)
        airline_str = f"{airline_code} ({known_name})" if known_name else airline_code
        print(f"  {i:2d}. {airline_str:24s}  总价: {fmt_price(flight.price):>8s}")

        for j, sg in enumerate(flight.flights):
            flag = "去程" if j == 0 else "返程"
            dep_time = fmt_time(sg.departure.time)
            arr_time = fmt_time(sg.arrival.time)
            dep_date = fmt_date(sg.departure.date) if sg.departure.date else ""
            duration = fmt_duration(sg.duration)
            plane = sg.plane_type or ""
            print(f"     {flag}: {sg.from_airport.code} {dep_date} {dep_time} → "
                  f"{sg.to_airport.code} {arr_time}  {duration:>6s}  {plane}")
        print()


def cmd_airlines():
    """列出已知航空公司代码"""
    from .utils import AIRLINE_NAMES
    print(f"\n{'='*60}")
    print("  航空公司代码对照表")
    print(f"{'='*60}")
    for code in sorted(AIRLINE_NAMES.keys()):
        print(f"  {code:4s}  {AIRLINE_NAMES[code]}")