#!/usr/bin/env python3
"""出行票务查询 CLI 入口 — 火车票 + 机票

用法:
  travel.py train query <from> <to> <date>              查询余票+票价
  travel.py train price <from> <to> <date>               查询票价
  travel.py train transfer <from> <to> <date> [--via X] 中转换乘
  travel.py train station <keyword>                      搜索车站
  travel.py train route <code> <from> <to> <date>        经停站

  travel.py flight search <from> <to> [date] [options]         单程航班
  travel.py flight roundtrip <from> <to> <depart> <return>     往返航班
  travel.py flight airport <keyword>                           机场/城市搜索
  travel.py flight airlines                                     航空公司代码

快捷方式:
  travel.py query <from> <to> <date>   = train query
  travel.py search <from> <to> [date]  = flight search
  travel.py airlines                   = flight airlines
"""
import asyncio
import sys

from travel import train, flight
from travel.utils import resolve_airport


def print_usage():
    print(__doc__)


def parse_flight_options() -> dict:
    """从 sys.argv 解析机票选项: --seat / --passengers / --stops / --sort / --currency"""
    opts = {
        "seat": "economy",
        "passengers": 1,
        "stops": 2,
        "sort": "QUALITY",
        "currency": "cny",
    }
    i = 0
    args = sys.argv
    while i < len(args):
        a = args[i]
        if a == "--seat" and i + 1 < len(args):
            opts["seat"] = args[i + 1]; i += 2; continue
        if a == "--passengers" and i + 1 < len(args):
            try:
                opts["passengers"] = int(args[i + 1])
            except ValueError:
                pass
            i += 2; continue
        if a == "--stops" and i + 1 < len(args):
            try:
                opts["stops"] = int(args[i + 1])
            except ValueError:
                pass
            i += 2; continue
        if a == "--sort" and i + 1 < len(args):
            opts["sort"] = args[i + 1]; i += 2; continue
        if a == "--currency" and i + 1 < len(args):
            opts["currency"] = args[i + 1]; i += 2; continue
        i += 1
    return opts


def parse_via() -> str:
    """从 sys.argv 中解析 --via"""
    via = ""
    if "--via" in sys.argv:
        i = sys.argv.index("--via")
        if i + 1 < len(sys.argv):
            via = sys.argv[i + 1]
    return via


def _flight_search(argv_offset: int):
    """flight search 子命令。argv_offset 是 <from> 在 sys.argv 中的位置。"""
    args = sys.argv[argv_offset:]
    # args: [<from>, <to>, <date>?, ...options]
    if len(args) < 2:
        print("用法: travel.py flight search <from> <to> [date] [--seat ...] [--stops n] [--sort ...] [--currency ...]")
        print("  date 可省略或写 anytime，查未来最便宜航班")
        return
    from_code = args[0]
    to_code = args[1]
    # date：第 3 个非选项位置参数
    date = ""
    for tok in args[2:]:
        if tok.startswith("--"):
            break
        date = tok
        break
    opts = parse_flight_options()
    flight.cmd_search(from_code, to_code, date,
                      opts["seat"], opts["passengers"],
                      opts["stops"], opts["sort"], opts["currency"])


def _flight_roundtrip(argv_offset: int):
    args = sys.argv[argv_offset:]
    if len(args) < 4:
        print("用法: travel.py flight roundtrip <from> <to> <depart> <return> [--seat ...] [--currency ...]")
        return
    from_code = args[0]
    to_code = args[1]
    depart = args[2]
    return_ = args[3]
    opts = parse_flight_options()
    flight.cmd_roundtrip(from_code, to_code, depart, return_,
                         opts["seat"], opts["passengers"],
                         opts["stops"], opts["sort"], opts["currency"])


async def main():
    if len(sys.argv) < 2:
        print_usage()
        return

    cmd = sys.argv[1]

    # ── 快捷命令 ──
    if cmd in ("query", "q"):
        if not train.AVAILABLE:
            print("错误: 需要安装 mcp-server-12306 库\n请运行: pip install mcp-server-12306")
            return
        if len(sys.argv) < 5:
            print("用法: travel.py query <from> <to> <date>")
            return
        await train.init()
        await train.cmd_query(sys.argv[2], sys.argv[3], sys.argv[4])

    elif cmd in ("search", "s"):
        if not flight.AVAILABLE:
            print("错误: 机票模块不可用")
            return
        _flight_search(2)

    elif cmd in ("airlines", "a"):
        if not flight.AVAILABLE:
            print("错误: 机票模块不可用")
            return
        flight.cmd_airlines()

    # ── train 子命令 ──
    elif cmd == "train":
        if not train.AVAILABLE:
            print("错误: 需要安装 mcp-server-12306 库\n请运行: pip install mcp-server-12306")
            return
        if len(sys.argv) < 3:
            print("用法: travel.py train <query|price|transfer|station|route> ...")
            return
        await train.init()
        sub = sys.argv[2]

        if sub in ("query", "q"):
            if len(sys.argv) < 6:
                print("用法: travel.py train query <from> <to> <date>")
                return
            await train.cmd_query(sys.argv[3], sys.argv[4], sys.argv[5])

        elif sub in ("price", "p"):
            if len(sys.argv) < 6:
                print("用法: travel.py train price <from> <to> <date>")
                return
            await train.cmd_price(sys.argv[3], sys.argv[4], sys.argv[5])

        elif sub in ("transfer", "t"):
            if len(sys.argv) < 6:
                print("用法: travel.py train transfer <from> <to> <date> [--via <station>]")
                return
            via = parse_via()
            await train.cmd_transfer(sys.argv[3], sys.argv[4], sys.argv[5], via)

        elif sub in ("station", "st"):
            if len(sys.argv) < 4:
                print("用法: travel.py train station <keyword>")
                return
            await train.cmd_station(sys.argv[3])

        elif sub in ("route", "r"):
            if len(sys.argv) < 7:
                print("用法: travel.py train route <code> <from> <to> <date>")
                return
            await train.cmd_route(sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])

        else:
            print(f"未知 train 子命令: {sub}")
            print("可用: query, price, transfer, station, route")

    # ── flight 子命令 ──
    elif cmd == "flight":
        if not flight.AVAILABLE:
            print("错误: 机票模块不可用")
            return
        if len(sys.argv) < 3:
            print("用法: travel.py flight <search|roundtrip|airport|airlines> ...")
            return
        sub = sys.argv[2]

        if sub in ("search", "s"):
            _flight_search(3)

        elif sub in ("roundtrip", "rt", "r"):
            _flight_roundtrip(3)

        elif sub in ("airport", "ap"):
            if len(sys.argv) < 4:
                print("用法: travel.py flight airport <keyword>")
                return
            flight.cmd_airport(sys.argv[3])

        elif sub in ("airlines", "a"):
            flight.cmd_airlines()

        else:
            print(f"未知 flight 子命令: {sub}")
            print("可用: search, roundtrip, airport, airlines")

    else:
        print(f"未知命令: {cmd}")
        print_usage()


if __name__ == "__main__":
    asyncio.run(main())
