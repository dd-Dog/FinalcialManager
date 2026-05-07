import cn_security_lookup as m
from cn_security_lookup import infer_stock_board


def test_stock_short_name_parses_nested_data_f58(monkeypatch) -> None:
    class Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self):
            return {"rc": 0, "data": {"f57": "600519", "f58": "贵州茅台"}}

    def fake_get(url, **_kwargs):
        assert "push2.eastmoney.com" in url
        return Resp()

    monkeypatch.setattr(m.requests, "get", fake_get)
    assert m._stock_short_name_from_em("600519", timeout=1.0) == "贵州茅台"


def test_infer_stock_board() -> None:
    assert infer_stock_board("600519") == "SH"
    assert infer_stock_board("000001") == "SZ"
    assert infer_stock_board("300750") == "SZ"
    assert infer_stock_board("430047") == "BJ"
    assert infer_stock_board("12") is None
