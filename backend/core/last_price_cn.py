"""境内股票/基金最新价（尽力而为，失败返回 None，不阻断主流程）。

东财 ``push2`` 对无完整浏览器头或短时多次请求可能断连，故使用 ``requests`` + 短暂重试；
部分标的 ``f43`` 为 ``"-"`` 时回退 ``f60``（昨收）等字段；``920`` 北交所等尝试多个 ``secid``。

基金：优先 ``fundgz.1234567.cn`` 估值/单位净值；失败或解析不到时用 ``fundf10.eastmoney.com``
历史净值接口最近一日单位净值（部分网络无法解析 ``1234567.cn`` 时仍可取到参考价）。
"""
from __future__ import annotations

import json
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

# 持仓列表会并行拉多条行情：单次不宜过长，避免 /positions 整体阻塞。
_RETRY_ATTEMPTS = 2
_RETRY_SLEEP_S = 0.4
_STOCK_TIMEOUT_S = 6.0
_FUND_TIMEOUT_S = 8.0


def _digits6(symbol: str) -> str | None:
    d = "".join(c for c in (symbol or "") if c.isdigit())
    return d if len(d) == 6 else None


def _parse_decimal(v: object) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s or s in ("-", "--", "—", "null", "None"):
            return None
    try:
        x = Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if x.is_nan() or x.is_infinite():
        return None
    return x


def _dedupe_preserve(xs: list[str]) -> list[str]:
    out: list[str] = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


def _eastmoney_secid_candidates(sym6: str) -> list[str]:
    """东财 ``secid`` 候选（按常见市场优先）。"""
    if len(sym6) != 6 or not sym6.isdigit():
        return []
    # 北交所新代码段 920xxx：不同环境可能落在 0./1./116. 下，依次尝试
    if sym6.startswith("920"):
        return _dedupe_preserve([f"0.{sym6}", f"1.{sym6}", f"116.{sym6}"])
    # 北交所 / 新三板常见 43、83 等：多为深证板块 0.
    if sym6[0] in ("4", "8"):
        return _dedupe_preserve([f"0.{sym6}", f"1.{sym6}"])
    # 沪主板、科创板、沪 B（900）等
    if sym6[0] in ("6", "9"):
        return _dedupe_preserve([f"1.{sym6}", f"0.{sym6}"])
    # 深主板、创业板等
    if sym6[0] in ("0", "1", "2", "3"):
        return _dedupe_preserve([f"0.{sym6}", f"1.{sym6}"])
    return _dedupe_preserve([f"0.{sym6}", f"1.{sym6}"])


def _retry_io(callable_, *, attempts: int = _RETRY_ATTEMPTS, sleep_s: float = _RETRY_SLEEP_S):
    last: BaseException | None = None
    for _ in range(attempts):
        try:
            return callable_()
        except BaseException as e:
            last = e
            time.sleep(sleep_s)
    if last is None:
        raise RuntimeError("retry: empty attempts")
    raise last


def _price_from_em_stock_block(blk: dict[str, Any]) -> Decimal | None:
    """从东财 ``data`` 块取可参考单价：现价优先，其次昨收等。"""
    for key in ("f43", "f60", "f46", "f301"):
        raw = blk.get(key)
        p = _parse_decimal(raw)
        if p is not None and p > 0:
            return p
    return None


def _stock_last_em(sym6: str) -> Decimal | None:
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    for secid in _eastmoney_secid_candidates(sym6):

        def _fetch_one() -> dict[str, Any] | None:
            r = requests.get(
                url,
                params={
                    "fltt": "2",
                    "invt": "2",
                    "fields": "f43,f44,f45,f46,f57,f58,f60,f170,f301",
                    "secid": secid,
                },
                headers=_EM_HEADERS,
                timeout=_STOCK_TIMEOUT_S,
            )
            r.raise_for_status()
            return r.json()

        try:
            j = _retry_io(_fetch_one)
        except BaseException:
            continue
        if j.get("rc") not in (0, None, "0"):
            continue
        blk = j.get("data")
        if not isinstance(blk, dict):
            continue
        price = _price_from_em_stock_block(blk)
        if price is not None:
            return price
    return None


def _fund_last_gz(code: str) -> Decimal | None:
    url = f"https://fundgz.1234567.cn/js/{code}.js"

    def _fetch() -> str:
        r = requests.get(url, headers=_EM_HEADERS, timeout=_FUND_TIMEOUT_S)
        r.raise_for_status()
        return r.text

    try:
        text = _retry_io(_fetch)
    except BaseException:
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


def _parse_f10_lsjz_unit_nav(api_text: str) -> Decimal | None:
    """解析 F10DataApi ``type=lsjz`` 返回的 JS 片段，取 tbody 首行单位净值（第二列）。"""
    # 当前接口多为 HTML 表格
    m = re.search(
        r"<tbody>\s*<tr>\s*<td>(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>([\d.]+)</td>\s*<td[^>]*>([\d.]+)</td>",
        api_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        p = _parse_decimal(m.group(2))
        if p is not None and p > 0:
            return p
    # 旧版：Markdown 风格竖线表
    for pat in (
        r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|",
        r"\|(\d{4}-\d{2}-\d{2})\|([\d.]+)\|([\d.]+)\|",
    ):
        m2 = re.search(pat, api_text)
        if not m2:
            continue
        p = _parse_decimal(m2.group(2))
        if p is not None and p > 0:
            return p
    return None


def _fund_last_f10_lsjz(sym6: str) -> Decimal | None:
    """东财 F10 历史净值（最近一日单位净值）；作 ``fundgz`` 的备用。"""
    url = "https://fundf10.eastmoney.com/F10DataApi.aspx"

    def _fetch() -> str:
        h = dict(_EM_HEADERS)
        h["Referer"] = "https://fundf10.eastmoney.com/"
        r = requests.get(
            url,
            params={"type": "lsjz", "code": sym6, "page": "1", "per": "1"},
            headers=h,
            timeout=_FUND_TIMEOUT_S,
        )
        r.raise_for_status()
        return r.text

    try:
        text = _retry_io(_fetch)
    except BaseException:
        return None
    return _parse_f10_lsjz_unit_nav(text)


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
            p = _fund_last_gz(sym6)
            if p is not None:
                return p
            return _fund_last_f10_lsjz(sym6)
    except Exception:
        return None
    return None
