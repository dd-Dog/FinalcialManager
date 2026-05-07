"""境内股票/基金最新价（尽力而为，失败返回 None，不阻断主流程）。"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _digits6(symbol: str) -> str | None:
    d = "".join(c for c in (symbol or "") if c.isdigit())
    return d if len(d) == 6 else None


def _parse_decimal(v: object) -> Decimal | None:
    if v is None:
        return None
    try:
        x = Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if x.is_nan() or x.is_infinite():
        return None
    return x


def _stock_last_em(sym6: str) -> Decimal | None:
    market_code = 1 if sym6.startswith("6") else 0
    q = urlencode(
        {"fltt": "2", "invt": "2", "fields": "f43,f57,f58", "secid": f"{market_code}.{sym6}"}
    )
    url = f"https://push2.eastmoney.com/api/qt/stock/get?{q}"
    req = Request(url, headers=_EM_HEADERS, method="GET")
    try:
        with urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError, TimeoutError):
        return None
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return None
    blk = j.get("data")
    if not isinstance(blk, dict):
        return None
    return _parse_decimal(blk.get("f43"))


def _fund_last_gz(code: str) -> Decimal | None:
    url = f"https://fundgz.1234567.cn/js/{code}.js"
    req = Request(url, headers=_EM_HEADERS, method="GET")
    try:
        with urlopen(req, timeout=12) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError, TimeoutError):
        return None
    m = re.search(r"jsonpgzf\s*\(\s*(\{.*?\})\s*\)\s*;", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        j = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(j, dict):
        return None
    for key in ("gsz", "dwjz"):
        p = _parse_decimal(j.get(key))
        if p is not None and p > 0:
            return p
    return None


def fetch_last_price_cn(asset_type: str, symbol: str) -> Decimal | None:
    """返回最近可参考单价（元/份）；网络或解析失败时返回 None。"""
    sym6 = _digits6(symbol)
    if sym6 is None:
        return None
    at = (asset_type or "").strip().lower()
    try:
        if at == "stock":
            return _stock_last_em(sym6)
        if at == "fund":
            return _fund_last_gz(sym6)
    except Exception:
        return None
    return None
