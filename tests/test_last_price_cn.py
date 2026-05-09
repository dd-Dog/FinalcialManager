"""``backend.core.last_price_cn``：东财/天天基金解析与回退逻辑（网络请求 mock）。"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.core import last_price_cn as m


def test_parse_decimal_dash() -> None:
    assert m._parse_decimal("-") is None
    assert m._parse_decimal("  --  ") is None


def test_eastmoney_secid_candidates() -> None:
    assert m._eastmoney_secid_candidates("600519")[0] == "1.600519"
    assert "0.000001" in m._eastmoney_secid_candidates("000001")
    assert m._eastmoney_secid_candidates("920971")[:2] == ["0.920971", "1.920971"]
    assert m._eastmoney_secid_candidates("430047")[0] == "0.430047"


def test_price_from_block_f43_then_f60() -> None:
    assert m._price_from_em_stock_block({"f43": "-", "f60": "12.34"}) == Decimal("12.34")
    assert m._price_from_em_stock_block({"f43": "10.5"}) == Decimal("10.5")
    assert m._price_from_em_stock_block({"f43": "-", "f60": "-"}) is None


@patch.object(m.requests, "get")
def test_stock_tries_second_secid_when_rc_bad(mock_get: MagicMock) -> None:
    bad = MagicMock()
    bad.raise_for_status = MagicMock()
    bad.json.return_value = {"rc": 100, "data": None}
    good = MagicMock()
    good.raise_for_status = MagicMock()
    good.json.return_value = {
        "rc": 0,
        "data": {"f43": "9.99", "f60": "9.00"},
    }
    mock_get.side_effect = [bad, good]
    out = m._stock_last_em("000001")
    assert out == Decimal("9.99")
    assert mock_get.call_count == 2


@patch.object(m.requests, "get")
def test_fund_uses_gsz(mock_get: MagicMock) -> None:
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.text = 'jsonpgzf({"gsz":"1.2345"});'
    assert m._fund_last_gz("000001") == Decimal("1.2345")


def test_parse_f10_lsjz_spacing_and_compact() -> None:
    spaced = 'var apidata={ content:"| 2026-05-08 | 1.5710 | 3.3780 | -0.82% |"'
    assert m._parse_f10_lsjz_unit_nav(spaced) == Decimal("1.5710")
    compact = 'content:"|2026-05-08|1.1310|1.1310|-0.82%|开放申购|"'
    assert m._parse_f10_lsjz_unit_nav(compact) == Decimal("1.1310")


def test_parse_f10_lsjz_html_table() -> None:
    html = (
        "var apidata={ content:\"<table><tbody><tr>"
        "<td>2026-05-08</td><td class='tor bold'>1.5710</td><td class='tor bold'>3.3780</td>"
        "<td>-0.82%</td></tr></tbody></table>\""
    )
    assert m._parse_f10_lsjz_unit_nav(html) == Decimal("1.5710")


@patch.object(m, "_fund_last_f10_lsjz", return_value=Decimal("2.5"))
@patch.object(m, "_fund_last_gz", return_value=None)
def test_fund_fetch_falls_back_to_f10(_mock_gz: MagicMock, _mock_f10: MagicMock) -> None:
    assert m.fetch_last_price_cn("fund", "260108") == Decimal("2.5")
