#!/usr/bin/env python3
"""出行票务查询 CLI 入口 — 火车票 + 机票

用法:
  travel.py train query <from> <to> <date>              查询余票+票价
  travel.py train price <from> <to> <date>               查询票价
  travel.py train transfer <from> <to> <date> [--via X] 中转换乘
  travel.py train station <keyword>                      搜索车站
  travel.py train route <code> <from> <to> <date>        经停站

  travel.py flight search <from> <to> <date> [options]         单程航班
  travel.py flight roundtrip <from> <to> <depart> <return>     往返航班
  travel.py flight airlines                                     航空公司代码

快捷方式:
  travel.py query <from> <to> <date>   = train query
  travel.py search <from> <to> <date>  = flight search
  travel.py airlines                   = flight airlines
"""
import asyncio
import sys

from travel import train, flight
from travel.utils import resolve_airport


def print_usage():
    print(__doc__)


def parse_seat_passengers() -> tuple:
    """从 sys.argv 中解析 --seat 和 --passengers"""
    seat = "economy"
    passengers = 1
    if "--seat" in sys.argv:
        i = sys.argv.index("--seat")
        if i + 1 < len(sys.argv):
            seat = sys.argv[i + 1]
    if "--passengers" in sys.argv:
        i = sys.argv.index("--passengers")
        if i + 1 < len(sys.argv):
            try:
                passengers = int(sys.argv[i + 1])
            except ValueError:
                pass
    return seat, passengers


def parse_via() -> str:
    """从 sys.argv 中解析 --via"""
    via = ""
    if "--via" in sys.argv:
        i = sys.argv.index("--via")
        if i + 1 < len(sys.argv):
            via = sys.argv[i + 1]
    return via


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
            print("错误: 需要安装 fast-flights 库\n请运行: pip install fast-flights")
            return
        if len(sys.argv) < 5:
            print("用法: travel.py search <from> <to> <date> [--seat ...]")
            return
        seat, passengers = parse_seat_passengers()
        flight.cmd_search(sys.argv[2], sys.argv[3], sys.argv[4], seat, passengers)

    elif cmd in ("airlines", "a"):
        if not flight.AVAILABLE:
            print("错误: 需要安装 fast-flights 库")
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
            print("错误: 需要安装 fast-flights 库\n请运行: pip install fast-flights")
            return
        if len(sys.argv) < 3:
            print("用法: travel.py flight <search|roundtrip|airlines> ...")
            return
        sub = sys.argv[2]

        if sub in ("search", "s"):
            if len(sys.argv) < 6:
                print("用法: travel.py flight search <from> <to> <date> [--seat ...]")
                return
            seat, passengers = parse_seat_passengers()
            flight.cmd_search(sys.argv[3], sys.argv[4], sys.argv[5], seat, passengers)

        elif sub in ("roundtrip", "rt", "r"):
            if len(sys.argv) < 7:
                print("用法: travel.py flight roundtrip <from> <to> <depart> <return> [--seat ...]")
                return
            seat, _ = parse_seat_passengers()
            flight.cmd_roundtrip(sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], seat)

        elif sub in ("airlines", "a"):
            flight.cmd_airlines()

        else:
            print(f"未知 flight 子命令: {sub}")
            print("可用: search, roundtrip, airlines")

    else:
        print(f"未知命令: {cmd}")
        print_usage()


if __name__ == "__main__":
    asyncio.run(main())