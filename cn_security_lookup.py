"""国内股票/基金代码 → 名称查询（东方财富等），供 WebUI 使用。

东财 ``push2.eastmoney.com`` 对无浏览器头的 ``requests`` 常会直接断连接（与 ping eastmoney.com 无关），
故股票简称走带 Referer/User-Agent 的直连 JSON，基金仍用 akshare 已带头部的列表接口。
"""
from __future__ import annotations

import functools
import time

import pandas as pd
import requests

LOOKUP_BAD_INPUT = "bad_input"
LOOKUP_NOT_FOUND = "not_found"
LOOKUP_NETWORK = "network"

_STOCK_TIMEOUT_S = 20.0
_RETRY_ATTEMPTS = 3
_RETRY_SLEEP_S = 0.65

# 与浏览器访问 quote 页一致；缺省时服务端常见 ``RemoteDisconnected``。
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _retry_io(callable_, *, attempts: int = _RETRY_ATTEMPTS, sleep_s: float = _RETRY_SLEEP_S):
    """短暂重试后再失败。"""
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return callable_()
        except Exception as e:
            last = e
            time.sleep(sleep_s)
    if last is None:
        raise RuntimeError("retry: empty attempts")
    raise last


def _stock_short_name_from_em(symbol_6: str, *, timeout: float) -> str | None:
    """东财 push2 接口取 ``f58`` 股票简称；成功无简称时返回 None。"""
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    market_code = 1 if symbol_6.startswith("6") else 0
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f57,f58",
        "secid": f"{market_code}.{symbol_6}",
    }
    r = requests.get(url, params=params, timeout=timeout, headers=_EM_HEADERS)
    r.raise_for_status()
    j = r.json()
    if j.get("rc") not in (0, None, "0"):
        return None
    blk = j.get("data")
    if not isinstance(blk, dict):
        return None
    nm = blk.get("f58")
    if nm is None:
        return None
    s = str(nm).strip()
    return s or None


@functools.lru_cache(maxsize=1)
def _fund_name_table() -> pd.DataFrame:
    import akshare as ak

    return _retry_io(ak.fund_name_em)


def infer_stock_board(symbol_6: str) -> str | None:
    """六位数字 A 股常见板块：SH / SZ / BJ。"""
    if len(symbol_6) != 6 or not symbol_6.isdigit():
        return None
    if symbol_6.startswith(("6", "9")):
        return "SH"
    if symbol_6.startswith(("0", "3")):
        return "SZ"
    if symbol_6.startswith(("4", "8")):
        return "BJ"
    return None


def lookup_cn_security(asset_type: str, symbol: str) -> tuple[str | None, str | None, str | None]:
    """
    按类型查询证券简称。

    :return: (name, market, err)；成功时 err 为 None；market 仅股票可能为 SH/SZ/BJ。
    """
    digits = "".join(c for c in (symbol or "") if c.isdigit())
    if len(digits) != 6:
        return None, None, LOOKUP_BAD_INPUT
    sym6 = digits
    at = (asset_type or "").strip().lower()
    try:
        if at == "fund":
            df = _fund_name_table()
            hit = df[df["基金代码"] == sym6]
            if hit.empty:
                return None, None, LOOKUP_NOT_FOUND
            nm = str(hit.iloc[0]["基金简称"]).strip()
            if not nm:
                return None, None, LOOKUP_NOT_FOUND
            return nm, None, None
        if at == "stock":
            try:
                nm = _retry_io(lambda: _stock_short_name_from_em(sym6, timeout=_STOCK_TIMEOUT_S))
            except Exception:
                return None, None, LOOKUP_NETWORK
            if not nm:
                return None, None, LOOKUP_NOT_FOUND
            return nm, infer_stock_board(sym6), None
    except Exception:
        return None, None, LOOKUP_NETWORK
    return None, None, LOOKUP_BAD_INPUT
