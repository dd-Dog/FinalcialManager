"""finance_webui 静态与导入回归：避免 on_dismiss 未定义、模块级 NameError 等重复问题。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "finance_webui.py"


def test_finance_webui_module_imports() -> None:
    """整页脚本必须能无 NameError 导入（含 @st.dialog 装饰器解析阶段）。"""
    import finance_webui  # noqa: F401


def test_dismiss_callbacks_and_consumers_exist() -> None:
    import finance_webui as m

    required = (
        "_dismiss_dialog_new_account",
        "_dismiss_dialog_account_pick",
        "_dismiss_dialog_delete_account",
        "_dismiss_dialog_edit_account",
        "_dismiss_dialog_new_asset",
        "_dismiss_dialog_asset_pick",
        "_dismiss_dialog_edit_asset",
        "_dismiss_dialog_delete_asset",
        "_dismiss_dialog_pos_opening",
        "_dismiss_dialog_pos_edit",
        "_dismiss_dialog_new_transaction",
        "_dismiss_dialog_transaction_detail",
        "_consume_accounts_grid_row_pick",
        "_consume_assets_grid_row_pick",
    )
    for name in required:
        assert hasattr(m, name), f"missing {name}"
        assert callable(getattr(m, name)), f"{name} is not callable"


def test_dialog_on_dismiss_handlers_defined_before_decorator_line() -> None:
    """装饰器在加载时解析 on_dismiss= 名称，对应 def 必须出现在同一文件更靠前的行。"""
    lines = WEBUI.read_text(encoding="utf-8").splitlines()
    pat = re.compile(r"on_dismiss=(_[\w]+)\b")
    for i, line in enumerate(lines):
        m = pat.search(line)
        if not m:
            continue
        fname = m.group(1)
        prior = "\n".join(lines[:i])
        assert re.search(rf"^def {re.escape(fname)}\s*\(", prior, re.MULTILINE), (
            f"{fname} 在第 {i + 1} 行用于 on_dismiss，但在该行之前未找到 def 定义"
        )


def test_session_dlg_keys_include_row_pick_and_delete() -> None:
    import finance_webui as m

    keys = set(m.SESSION_DLG_KEYS)
    assert "dlg_account_pick_id" in keys
    assert "dlg_account_delete_id" in keys
    assert "dlg_asset_pick_id" in keys
    assert "dlg_asset_delete_id" in keys
    assert "dlg_pos_open" in keys
    assert "dlg_pos_edit_open" in keys


def test_friendly_delete_error_returns_user_strings() -> None:
    import finance_webui as m

    a = m._friendly_delete_error("409: Cannot delete asset: related transactions exist", kind="asset")
    b = m._friendly_delete_error("409: Cannot delete account: related transactions exist", kind="account")
    assert isinstance(a, str) and len(a) > 5 and "409" not in a
    assert isinstance(b, str) and len(b) > 5 and "409" not in b


def test_column_label_single_language() -> None:
    import streamlit as st

    import finance_column_labels as cl

    st.session_state["ui_lang"] = "zh"
    zh = cl.column_label("balance")
    st.session_state["ui_lang"] = "en"
    en = cl.column_label("balance")
    assert zh == "余额" and en == "Balance"
    assert " / " not in zh and " / " not in en
    st.session_state["ui_lang"] = "zh"
    assert cl.column_label("cost_amount") == "成本金额"
    st.session_state["ui_lang"] = "en"
    assert cl.column_label("cost_amount") == "Cost amount"
    st.session_state["ui_lang"] = "zh"
    assert cl.column_label("floating_pnl") == "浮动盈亏"
    assert cl.column_label("yield_pct") == "收益率"
    assert cl.column_label("annualized_yield") == "年化"
    assert cl.column_label("last_price") == "参考市价"
    assert cl.column_label("ref_price_updated_at") == "参考价更新于"
    st.session_state["ui_lang"] = "en"
    assert cl.column_label("floating_pnl") == "Floating P&L"
    assert cl.column_label("yield_pct") == "Yield %"
    assert cl.column_label("annualized_yield") == "Annualized"
    assert cl.column_label("last_price") == "Last price (ref.)"
    assert cl.column_label("ref_price_updated_at") == "Ref. price updated at"
