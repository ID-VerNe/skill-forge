"""共享工具函数 — 格式化、机场/车站别名"""

# ── 机场代码映射（中文名 → IATA） ────────────────────────────────
AIRPORT_ALIASES = {
    # 深圳
    "深圳": "SZX", "sz": "SZX", "shenzhen": "SZX",
    # 上海
    "上海": "SHA", "上海虹桥": "SHA", "虹桥": "SHA", "shanghai": "SHA",
    "shanghai hongqiao": "SHA",
    "上海浦东": "PVG", "浦东": "PVG", "pudong": "PVG", "pvg": "PVG",
    # 北京
    "北京": "PEK", "北京首都": "PEK", "首都": "PEK", "beijing": "PEK",
    "北京大兴": "PKX", "大兴": "PKX", "daxing": "PKX",
    # 广州
    "广州": "CAN", "guangzhou": "CAN", "gz": "CAN",
    # 成都
    "成都": "CTU", "成都双流": "CTU", "成都天府": "TFU", "天府": "TFU",
    "chengdu": "CTU",
    # 杭州
    "杭州": "HGH", "hangzhou": "HGH",
    # 武汉
    "武汉": "WUH", "wuhan": "WUH",
    # 重庆
    "重庆": "CKG", "chongqing": "CKG",
    # 南京
    "南京": "NKG", "nanjing": "NKG",
    # 厦门
    "厦门": "XMN", "xiamen": "XMN",
    # 三亚
    "三亚": "SYX", "sanya": "SYX",
    # 昆明
    "昆明": "KMG", "kunming": "KMG",
    # 西安
    "西安": "XIY", "xian": "XIY",
    # 香港
    "香港": "HKG", "hongkong": "HKG", "hong kong": "HKG",
}

# ── 航空公司代码对照表 ────────────────────────────────────────────
AIRLINE_NAMES = {
    "ZH": "深圳航空", "CA": "中国国航", "MU": "东方航空",
    "CZ": "南方航空", "HU": "海南航空", "3U": "四川航空",
    "MF": "厦门航空", "SC": "山东航空", "FM": "上海航空",
    "GS": "天津航空", "8L": "祥鹏航空", "KY": "昆明航空",
    "JD": "首都航空", "GJ": "长龙航空", "BK": "奥凯航空",
    "EU": "成都航空", "NS": "河北航空", "QW": "青岛航空",
    "9C": "春秋航空", "AQ": "九元航空", "DZ": "东海航空",
    "JR": "幸福航空", "Y8": "金鹏航空", "GT": "桂林航空",
    "HO": "吉祥航空", "TV": "西藏航空", "UQ": "乌鲁木齐航空",
    "PN": "西部航空", "LT": "龙江航空",
    # 国际
    "CX": "国泰航空", "KA": "国泰港龙", "SQ": "新加坡航空",
    "NH": "全日空", "JL": "日本航空", "KE": "大韩航空",
    "OZ": "韩亚航空", "EK": "阿联酋航空", "EY": "阿提哈德航空",
    "QR": "卡塔尔航空", "TK": "土耳其航空", "AF": "法国航空",
    "LH": "汉莎航空", "BA": "英国航空", "AA": "美国航空",
    "DL": "达美航空", "UA": "美联航", "AC": "加拿大航空",
    "QF": "澳洲航空",
}


def resolve_airport(code_or_name: str) -> str:
    """将中文名或别名解析为 IATA 三字码"""
    upper = code_or_name.upper()
    if len(upper) == 3 and upper.isalpha():
        return upper
    return AIRPORT_ALIASES.get(code_or_name.lower(), code_or_name.upper())


def fmt_time(t) -> str:
    """格式化时间: [7, 45] -> 07:45"""
    if isinstance(t, (list, tuple)):
        return f"{t[0]:02d}:{t[1]:02d}"
    return str(t)


def fmt_date(d) -> str:
    """格式化日期: [2026, 7, 28] -> 2026-07-28"""
    if isinstance(d, (list, tuple)):
        return f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}"
    return str(d)


def fmt_duration(minutes: int) -> str:
    """格式化时长: 155 -> 2h35m"""
    h = minutes // 60
    m = minutes % 60
    if h == 0:
        return f"{m}m"
    return f"{h}h{m:02d}m"


def fmt_price(price) -> str:
    """格式化价格"""
    try:
        return f"¥{int(price)}"
    except (ValueError, TypeError):
        return f"¥{price}"


def fmt_train_price(price_val: str) -> str:
    """格式化火车票价格"""
    try:
        v = float(price_val)
        return f"¥{v:.1f}"
    except ValueError:
        return price_val


def get_airline_name(code: str) -> str:
    """获取航空公司中文名"""
    return AIRLINE_NAMES.get(code, code)


def fmt_seats_compact(seats: dict) -> str:
    """紧凑格式余票，只显示有票的席别"""
    parts = []
    label_map = {
        "business": "商务", "first_class": "一等", "second_class": "二等",
        "advanced_soft_sleeper": "高软", "soft_sleeper": "软卧",
        "dongwo": "动卧", "hard_sleeper": "硬卧",
        "soft_seat": "软座", "hard_seat": "硬座", "no_seat": "无座",
    }
    for k, v in seats.items():
        if v in ("无", "0", 0, "") or v is None:
            continue
        parts.append(f"{label_map.get(k, k)}{v}")
    return "  ".join(parts)


def fmt_prices_compact(prices: dict) -> str:
    """紧凑格式票价"""
    parts = []
    label_map = {
        "business": "商务", "first_class": "一等", "second_class": "二等",
        "advanced_soft_sleeper": "高软", "soft_sleeper": "软卧",
        "dongwo": "动卧", "hard_sleeper": "硬卧",
        "soft_seat": "软座", "hard_seat": "硬座",
    }
    for k, v in prices.items():
        try:
            parts.append(f"{label_map.get(k, k)}¥{float(v):.1f}")
        except (ValueError, TypeError):
            parts.append(f"{label_map.get(k, k)}{v}")
    return "  ".join(parts)