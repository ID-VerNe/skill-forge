"""共享工具函数 — 格式化、机场/车站别名、币种映射"""

# ── 机场代码映射（中文名 → IATA / Kiwi 城市 id） ──────────────────
# value 为 (IATA, Kiwi_City_id) 元组；IATA 用于 fallback，City id 为首选。
AIRPORT_ALIASES = {
    # 深圳
    "深圳": ("SZX", "City:shenzhen_cn"), "sz": ("SZX", "City:shenzhen_cn"), "shenzhen": ("SZX", "City:shenzhen_cn"),
    # 上海
    "上海": ("SHA", "City:shanghai_cn"), "shanghai": ("SHA", "City:shanghai_cn"),
    "上海虹桥": ("SHA", "City:shanghai_cn"), "虹桥": ("SHA", "City:shanghai_cn"),
    "上海浦东": ("PVG", "City:shanghai_cn"), "浦东": ("PVG", "City:shanghai_cn"),
    "pudong": ("PVG", "City:shanghai_cn"), "pvg": ("PVG", "City:shanghai_cn"),
    # 北京
    "北京": ("PEK", "City:beijing_cn"), "北京首都": ("PEK", "City:beijing_cn"),
    "首都": ("PEK", "City:beijing_cn"), "beijing": ("PEK", "City:beijing_cn"),
    "北京大兴": ("PKX", "City:beijing_cn"), "大兴": ("PKX", "City:beijing_cn"), "daxing": ("PKX", "City:beijing_cn"),
    # 广州
    "广州": ("CAN", "City:guangzhou_cn"), "guangzhou": ("CAN", "City:guangzhou_cn"), "gz": ("CAN", "City:guangzhou_cn"),
    # 成都
    "成都": ("CTU", "City:chengdu_cn"), "成都双流": ("CTU", "City:chengdu_cn"),
    "成都天府": ("TFU", "City:chengdu_cn"), "天府": ("TFU", "City:chengdu_cn"), "chengdu": ("CTU", "City:chengdu_cn"),
    # 杭州
    "杭州": ("HGH", "City:hangzhou_cn"), "hangzhou": ("HGH", "City:hangzhou_cn"),
    # 武汉
    "武汉": ("WUH", "City:wuhan_cn"), "wuhan": ("WUH", "City:wuhan_cn"),
    # 重庆
    "重庆": ("CKG", "City:chongqing_cn"), "chongqing": ("CKG", "City:chongqing_cn"),
    # 南京
    "南京": ("NKG", "City:nanjing_cn"), "nanjing": ("NKG", "City:nanjing_cn"),
    # 厦门
    "厦门": ("XMN", "City:xiamen_cn"), "xiamen": ("XMN", "City:xiamen_cn"),
    # 三亚
    "三亚": ("SYX", "City:sanya_cn"), "sanya": ("SYX", "City:sanya_cn"),
    # 昆明
    "昆明": ("KMG", "City:kunming_cn"), "kunming": ("KMG", "City:kunming_cn"),
    # 西安
    "西安": ("XIY", "City:xian_cn"), "xian": ("XIY", "City:xian_cn"),
    # 香港
    "香港": ("HKG", "City:hong-kong_hk"), "hongkong": ("HKG", "City:hong-kong_hk"), "hong kong": ("HKG", "City:hong-kong_hk"),
    # 国际常用城市
    "墨尔本": ("MEL", "City:melbourne_vi_au"), "melbourne": ("MEL", "City:melbourne_vi_au"),
    "悉尼": ("SYD", "City:sydney_nsw_au"), "sydney": ("SYD", "City:sydney_nsw_au"),
    "东京": ("HND", "City:tokyo_jp"), "tokyo": ("HND", "City:tokyo_jp"),
    "新加坡": ("SIN", "City:singapore_sg"), "singapore": ("SIN", "City:singapore_sg"),
    "曼谷": ("BKK", "City:bangkok_th"), "bangkok": ("BKK", "City:bangkok_th"),
    "吉隆坡": ("KUL", "City:kuala-lumpur_my"), "kuala lumpur": ("KUL", "City:kuala-lumpur_my"), "kualalumpur": ("KUL", "City:kuala-lumpur_my"),
    "首尔": ("ICN", "City:seoul_kr"), "seoul": ("ICN", "City:seoul_kr"),
    "大阪": ("KIX", "City:osaka_jp"), "osaka": ("KIX", "City:osaka_jp"),
    "巴黎": ("CDG", "City:paris_fr"), "paris": ("CDG", "City:paris_fr"),
    "伦敦": ("LHR", "City:london_gb"), "london": ("LHR", "City:london_gb"),
    "纽约": ("JFK", "City:new-york-city_ny_us"), "new york": ("JFK", "City:new-york-city_ny_us"), "newyork": ("JFK", "City:new-york-city_ny_us"),
    "洛杉矶": ("LAX", "City:los-angeles_ca_us"), "los angeles": ("LAX", "City:los-angeles_ca_us"), "la": ("LAX", "City:los-angeles_ca_us"),
}

# ── 航空公司代码对照表 ────────────────────────────────────────────
AIRLINE_NAMES = {
    # 国内
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
    # 港澳台
    "CX": "国泰航空", "KA": "国泰港龙", "BR": "长荣航空",
    "CI": "中华航空", "MM": " Peach Aviation",
    # 东南亚 / 亚洲
    "AK": "亚洲航空", "D7": " AirAsia X", "FD": " 泰国亚航",
    "5J": "宿务太平洋", "PR": "菲律宾航空",
    "VJ": "越捷航空", "VN": "越南航空",
    "TR": "酷航", "3K": " 捷星亚洲",
    "JQ": "捷星航空", "VA": "维珍澳洲", "QF": "澳洲航空", "JST": " Jetstar",
    "SL": " 泰国狮航", "XW": " 泰国越捷", "PG": " 曼谷航空",
    # 东北亚
    "SQ": "新加坡航空", "NH": "全日空", "JL": "日本航空",
    "KE": "大韩航空", "OZ": "韩亚航空", "LJ": " Jin Air",
    "7C": " 真航空", "TW": " 德威航空", "ZE": " 易斯达航空",
    # 中东
    "EK": "阿联酋航空", "EY": "阿提哈德航空", "QR": "卡塔尔航空",
    "TK": "土耳其航空", "ET": "埃塞俄比亚航空", "SV": "沙特航空",
    # 欧洲
    "AF": "法国航空", "LH": "汉莎航空", "BA": "英国航空",
    "KL": "荷兰皇家航空", "IB": "西班牙航空", "AZ": "意大利航空",
    "LX": "瑞士国际航空", "SK": "北欧航空", "AY": "芬兰航空",
    # 美洲
    "AA": "美国航空", "DL": "达美航空", "UA": "美联航",
    "AC": "加拿大航空", "LA": " LATAM", "CM": " 巴拿马航空",
}


# ── 币种 → Kiwi locale/market 映射 ────────────────────────────────
# Kiwi options 需要 currency + locale + market + partnerMarket 四件套。
CURRENCY_MAP = {
    "cny": {"locale": "zh", "market": "cn", "partner_market": "cn"},
    "usd": {"locale": "en", "market": "us", "partner_market": "us"},
    "eur": {"locale": "en", "market": "eu", "partner_market": "eu"},
    "gbp": {"locale": "en", "market": "gb", "partner_market": "gb"},
    "aud": {"locale": "en", "market": "au", "partner_market": "au"},
    "jpy": {"locale": "ja", "market": "jp", "partner_market": "jp"},
    "hkd": {"locale": "zh", "market": "hk", "partner_market": "hk"},
    "sgd": {"locale": "en", "market": "sg", "partner_market": "sg"},
}


def resolve_airport(code_or_name: str) -> str:
    """将中文名或别名解析为 Kiwi id（City:xxx 或 Station:airport:XXX）。

    解析优先级：
    1. 别名表命中 → 返回表中的 City id（如 'City:guangzhou_cn'）。
    2. 三字 IATA → 用 'Station:airport:<IATA>'（如 'Station:airport:CAN'），
       Kiwi 同时也接受裸 IATA，但显式 Station id 更稳。
    3. 已是 Kiwi id 格式（含冒号）→ 原样返回。
    4. 其他 → 原样返回（交给 Kiwi 当 term/ids 处理）。
    """
    if ":" in code_or_name:
        return code_or_name  # 已是 City:xxx / Station:airport:XXX
    lower = code_or_name.lower()
    if lower in AIRPORT_ALIASES:
        return AIRPORT_ALIASES[lower][1]
    upper = code_or_name.upper()
    if len(upper) == 3 and upper.isalpha():
        return f"Station:airport:{upper}"
    return code_or_name


def fmt_time(t) -> str:
    """格式化时间: [7, 45] -> 07:45; 空值/异常结构 -> '--:--'"""
    if isinstance(t, (list, tuple)):
        if len(t) >= 2 and isinstance(t[0], int) and isinstance(t[1], int):
            return f"{t[0]:02d}:{t[1]:02d}"
        return "--:--"
    if t in (None, "", 0):
        return "--:--"
    return str(t)


def fmt_date(d) -> str:
    """格式化日期: [2026, 7, 28] -> 2026-07-28"""
    if isinstance(d, (list, tuple)):
        return f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}"
    return str(d)


def fmt_iso_datetime(iso: str) -> str:
    """格式化 Kiwi ISO 本地时间: '2026-11-20T03:20:00' -> '11-20 03:20'"""
    if not iso:
        return "--:--"
    try:
        date_part, time_part = iso.split("T", 1)
        return f"{date_part[5:]} {time_part[:5]}"
    except (ValueError, AttributeError):
        return str(iso)


def fmt_duration(seconds: int) -> str:
    """格式化时长: 155 (分钟) -> 2h35m；秒自动除 60。

    为兼容两种输入：>= 1000 视为秒（Kiwi），否则视为分钟（12306）。
    """
    if seconds is None:
        return "--"
    if seconds >= 1000:  # 秒（Kiwi 的航班时长至少几千秒）
        seconds = seconds // 60
    h = seconds // 60
    m = seconds % 60
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
