from __future__ import annotations

import calendar
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from cn_security_lookup import LOOKUP_BAD_INPUT, LOOKUP_NETWORK, LOOKUP_NOT_FOUND, lookup_cn_security
from finance_column_labels import apply_table_column_labels
from finance_i18n import account_type_label, asset_type_label, t, tx_type_label


DEFAULT_API_BASE = "http://127.0.0.1:8000/api/v1"

# 表格/API 中可能为 ISO 的时间字段，展示为 YYYY/MM/DD HH:MM
TIME_COLUMN_KEYS = frozenset({"occurred_at", "start_date", "end_date", "created_at", "updated_at"})


def _user_tzinfo():
    z = datetime.now().astimezone().tzinfo
    return z if z is not None else timezone.utc


def format_ts_display(dt: datetime) -> str:
    """易读：YYYY/MM/DD HH:MM（按本机时区展示）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_user_tzinfo())
    return dt.astimezone().strftime("%Y/%m/%d %H:%M")


def parse_ts_input(s: str) -> datetime:
    """支持 YYYY/MM/DD HH:MM[:SS] 与 ISO-8601；无时区的按本机时区补全。"""
    raw = (s or "").strip()
    if not raw:
        raise ValueError("时间为空")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return datetime.fromisoformat(raw).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=_user_tzinfo())
    m = re.fullmatch(r"(\d{4})/(\d{2})/(\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", raw)
    if m:
        y, mo, d, h, mi, sec = m.groups()
        sec = sec or "0"
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec), tzinfo=_user_tzinfo())
    iso = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_user_tzinfo())
    return dt


def iso_ts_for_api(s: str) -> str:
    """提交给后端的时刻字符串（ISO，含秒）。"""
    return parse_ts_input(s).isoformat(timespec="seconds")


def _looks_like_datetime_string(s: str) -> bool:
    if len(s) < 10:
        return False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return True
    if s[4] == "/" and s[7] == "/" and len(s) >= 16 and s[10:11].isspace():
        return True
    if s[4] == "-" and s[7] == "-" and ("T" in s or len(s) == 10):
        return True
    return False


def format_ts_cell(v: object) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return format_ts_display(v)
    s = str(v).strip()
    if not _looks_like_datetime_string(s):
        return s
    try:
        return format_ts_display(parse_ts_input(s))
    except ValueError:
        return s


def _rows_asset_type_display(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    out: list[dict] = []
    for row in rows:
        d = dict(row)
        if "asset_type" in d and d["asset_type"] not in (None, ""):
            d["asset_type"] = asset_type_label(str(d["asset_type"]))
        out.append(d)
    return out


def rows_readable_times(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    out: list[dict] = []
    for row in rows:
        d = dict(row)
        for k in TIME_COLUMN_KEYS:
            if k in d and d[k] not in (None, ""):
                d[k] = format_ts_cell(d[k])
        if "month" in d and d["month"]:
            mv = str(d["month"]).strip()
            if len(mv) == 7 and mv[4] == "-":
                d["month"] = f"{mv[:4]}/{mv[5:7]}"
        out.append(d)
    return out


def prepare_grid_rows(
    rows: list[dict],
    *,
    drop_keys: frozenset[str] | None = None,
    preserve_column_keys: frozenset[str] | None = None,
) -> list[dict]:
    """时间列易读 + 表头随界面语言。``drop_keys`` 在转表头前剔除列；``preserve_column_keys`` 不改为显示列名。"""
    data = rows
    if drop_keys:
        data = [{k: v for k, v in r.items() if k not in drop_keys} for r in rows]
    return apply_table_column_labels(
        rows_readable_times(_rows_asset_type_display(data)),
        preserve_keys=preserve_column_keys or frozenset(),
    )


def pnl_default_range_readable() -> tuple[str, str]:
    """收支区间报表：本月首尾（易读字符串）。"""
    now = datetime.now().astimezone()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = calendar.monthrange(now.year, now.month)[1]
    end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)
    return format_ts_display(start), format_ts_display(end)


def normalize_api_base(raw: str) -> str:
    """FM_API_BASE 常写成 http://127.0.0.1:8000 未带 /api/v1，会导致 404。无路径时自动补上 /api/v1。"""
    u = (raw or "").strip().rstrip("/")
    if not u:
        return DEFAULT_API_BASE
    parsed = urlparse(u)
    path = parsed.path or ""
    if path in ("", "/") and not u.endswith("/api/v1"):
        return f"{parsed.scheme}://{parsed.netloc}/api/v1".rstrip("/")
    return u


try:
    from backend.core.cn_banks import CHINESE_BANK_CATALOG as BANK_CATALOG_BUILTIN
except ImportError:
    BANK_CATALOG_BUILTIN = ()


def load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass


def _fm_env_file() -> Path:
    return Path(__file__).resolve().parent / ".env"


def read_fm_api_base_raw() -> str:
    """优先读项目根 .env 文件中的 FM_API_BASE（每次脚本重跑都读盘），避免会话里长期卡住旧公网地址。"""
    env_path = _fm_env_file()
    raw = ""
    try:
        from dotenv import dotenv_values

        if env_path.is_file():
            vals = dotenv_values(env_path)
            raw = (vals.get("FM_API_BASE") or vals.get("API_BASE") or "").strip()
    except ImportError:
        pass
    if not raw:
        raw = (os.getenv("FM_API_BASE") or os.getenv("API_BASE") or "").strip()
    return raw


MENU_PAGES: list[tuple[str, str]] = [
    ("overview", "nav_overview"),
    ("accounts", "nav_accounts"),
    ("assets", "nav_assets"),
    ("transactions", "nav_transactions"),
    ("transfers", "nav_transfers"),
    ("positions", "nav_positions"),
    ("pnl", "nav_pnl"),
    ("reports", "nav_reports"),
]

SESSION_DLG_KEYS = (
    "dlg_account_open",
    "dlg_asset_open",
    "dlg_tx_open",
    "dlg_account_pick_id",
    "dlg_account_edit_id",
    "dlg_account_delete_id",
    "dlg_asset_pick_id",
    "dlg_asset_edit_id",
    "dlg_asset_delete_id",
)

_FM_ACCOUNTS_GRID_KEY = "fm_accounts_grid"
_FM_ASSETS_GRID_KEY = "fm_assets_grid"

SESSION_GRID_KEYS = (_FM_ACCOUNTS_GRID_KEY, _FM_ASSETS_GRID_KEY)

_PENDING_CLEAR_FM_ACCOUNTS_GRID = "_pending_clear_fm_accounts_grid"
_PENDING_CLEAR_FM_ASSETS_GRID = "_pending_clear_fm_assets_grid"

SESSION_PENDING_GRID_CLEAR_KEYS = (_PENDING_CLEAR_FM_ACCOUNTS_GRID, _PENDING_CLEAR_FM_ASSETS_GRID)


def _clear_fm_grid_selection(widget_key: str) -> None:
    st.session_state[widget_key] = {"selection": {"rows": [], "columns": [], "cells": []}}


def _request_clear_fm_accounts_grid() -> None:
    """从 ``@st.dialog`` 内调用：勿直接改 ``fm_accounts_grid`` 的 session_state（对话框片段重跑时主表 widget 已存在会报错）。"""
    st.session_state[_PENDING_CLEAR_FM_ACCOUNTS_GRID] = True


def _request_clear_fm_assets_grid() -> None:
    st.session_state[_PENDING_CLEAR_FM_ASSETS_GRID] = True


def _dismiss_dialog_new_account() -> None:
    st.session_state.pop("dlg_account_open", None)
    _request_clear_fm_accounts_grid()


def _dismiss_dialog_account_pick() -> None:
    st.session_state.pop("dlg_account_pick_id", None)
    _request_clear_fm_accounts_grid()


def _dismiss_dialog_delete_account() -> None:
    st.session_state.pop("dlg_account_delete_id", None)
    _request_clear_fm_accounts_grid()


def _dismiss_dialog_edit_account() -> None:
    st.session_state.pop("dlg_account_edit_id", None)
    _request_clear_fm_accounts_grid()


def _dismiss_dialog_new_asset() -> None:
    st.session_state.pop("dlg_asset_open", None)
    st.session_state.pop("_dlg_ast_post_lookup", None)
    for _k in ("dlg_ast_symbol", "dlg_ast_name", "dlg_ast_market"):
        st.session_state.pop(_k, None)
    _request_clear_fm_assets_grid()


def _dismiss_dialog_asset_pick() -> None:
    st.session_state.pop("dlg_asset_pick_id", None)
    _request_clear_fm_assets_grid()


def _dismiss_dialog_edit_asset() -> None:
    st.session_state.pop("dlg_asset_edit_id", None)
    _request_clear_fm_assets_grid()


def _dismiss_dialog_delete_asset() -> None:
    st.session_state.pop("dlg_asset_delete_id", None)
    _request_clear_fm_assets_grid()


SESSION_TX_DETAIL_KEYS = ("dlg_tx_detail_id",)


def _dismiss_dialog_new_transaction() -> None:
    st.session_state.pop("dlg_tx_open", None)


def _dismiss_dialog_transaction_detail() -> None:
    for k in SESSION_TX_DETAIL_KEYS:
        st.session_state.pop(k, None)
    _clear_fm_tx_list_df_selection()


TX_LIST_PAGE_SIZE = 10

# 登录态 Cookie：整页刷新会新建 Streamlit 会话，用主页面 Cookie + ``st.context.cookies`` 恢复 token。
# （extra_streamlit_components 写在 iframe 里的 cookie 往往不会出现在主文档请求里，故不用。）
_AUTH_COOKIE = "fm_auth"


def _persist_auth_cookie(token: str, username: str) -> None:
    """在主页面 ``document.cookie`` 写入，刷新后由浏览器随请求带给 ``st.context.cookies``。"""
    payload = json.dumps({"token": token, "username": username}, separators=(",", ":"))
    js_payload = json.dumps(payload)
    html = f"""
<div style="height:1px;width:1px"></div>
<script>
(function () {{
  const raw = {js_payload};
  const part = "{_AUTH_COOKIE}=" + encodeURIComponent(raw) + "; Path=/; Max-Age=1209600; SameSite=Lax";
  try {{
    var d = window.parent && window.parent !== window ? window.parent.document : document;
    d.cookie = part;
  }} catch (e) {{}}
}})();
</script>
"""
    components.html(html, height=1, width=1)


def _restore_auth_cookie_if_needed() -> None:
    if st.session_state.get("token"):
        return
    raw: str | None = None
    if hasattr(st, "context"):
        try:
            raw = st.context.cookies.get(_AUTH_COOKIE)
        except Exception:
            raw = None
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = json.loads(unquote(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            return
    except (TypeError, ValueError):
        return
    tok = data.get("token")
    if tok:
        st.session_state["token"] = str(tok)
        un = data.get("username")
        if un:
            st.session_state["username"] = str(un)
        st.session_state.setdefault("nav_page", "overview")


def _clear_auth_cookie() -> None:
    html = f"""
<div style="height:1px;width:1px"></div>
<script>
(function () {{
  try {{
    var d = window.parent && window.parent !== window ? window.parent.document : document;
    d.cookie = "{_AUTH_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax";
  }} catch (e) {{}}
}})();
</script>
"""
    components.html(html, height=1, width=1)


# 转账下拉占位：固定内部值，避免切换语言后选项字符串与逻辑不一致
TRANSFER_PLACEHOLDER = "__pick__"


def get_api_base() -> str:
    return st.session_state.get("api_base", DEFAULT_API_BASE).rstrip("/")


def get_auth_headers() -> dict[str, str]:
    token = st.session_state.get("token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def render_language_switcher() -> None:
    if "ui_lang" not in st.session_state:
        st.session_state["ui_lang"] = "zh"
    want_en = st.session_state["ui_lang"] == "en"
    _, lang_col = st.columns([0.78, 0.22])
    with lang_col:
        if hasattr(st, "toggle"):
            use_en = st.toggle(
                t("lang_toggle_switch_label"),
                value=want_en,
                key="_fm_ui_english_toggle",
                help=t("lang_toggle_help"),
            )
            if bool(use_en) != want_en:
                st.session_state["ui_lang"] = "en" if use_en else "zh"
                st.rerun()
        else:
            if st.button(
                t("lang_compact_toggle"),
                key="fm_lang_toggle_btn",
                use_container_width=True,
                help=t("lang_toggle_help"),
            ):
                st.session_state["ui_lang"] = "en" if st.session_state["ui_lang"] == "zh" else "zh"
                st.rerun()


def api_call(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    params: dict | None = None,
    require_auth: bool = True,
) -> tuple[bool, dict | str]:
    url = f"{get_api_base()}{path}"
    headers = {"Content-Type": "application/json"}
    if require_auth:
        auth_headers = get_auth_headers()
        if not auth_headers:
            return False, t("err_please_login")
        headers.update(auth_headers)

    try:
        response = requests.request(method, url, json=payload, params=params, headers=headers, timeout=15)
    except requests.RequestException as exc:
        return False, t("err_request", exc=str(exc))

    try:
        body = response.json()
    except ValueError:
        body = response.text

    if response.status_code >= 400:
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("message") or str(body)
        else:
            detail = str(body)
        return False, f"{response.status_code}: {detail}"
    return True, body


def _friendly_delete_error(result: object, *, kind: str) -> str:
    """DELETE 账户/标的失败时：不把原始 HTTP 堆栈甩给用户，只给可读说明。"""
    raw = (result if isinstance(result, str) else str(result) if result is not None else "").strip()
    if not raw:
        return t("err_delete_unknown")
    detail = raw.split(": ", 1)[-1].strip() if ": " in raw else raw
    dl = detail.lower()

    if kind == "account":
        if "non-zero balance" in dl:
            return t("err_delete_account_balance")
        if "related transactions" in dl:
            return t("err_delete_account_tx")
        if "related transfers" in dl:
            return t("err_delete_account_transfer")
        return t("err_delete_account_generic")

    if "non-zero position" in dl or ("holding" in dl and "position" in dl):
        return t("err_delete_asset_position")
    if "related transactions" in dl:
        return t("err_delete_asset_tx")
    return t("err_delete_asset_generic")


def _fetch_api_dict(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    params: dict | None = None,
) -> tuple[dict | None, str]:
    ok, result = api_call(method, path, payload=payload, params=params)
    if not ok:
        return None, str(result)
    if not isinstance(result, dict):
        return None, t("err_not_json")
    data = result.get("data")
    if not isinstance(data, dict):
        return None, t("err_bad_api_data", typ=type(data).__name__)
    return data, ""


def fetch_accounts() -> list[dict]:
    ok, result = api_call("GET", "/accounts")
    if ok and isinstance(result, dict):
        return result.get("data", {}).get("items", []) or []
    return []


def fetch_assets() -> list[dict]:
    ok, result = api_call("GET", "/assets")
    if ok and isinstance(result, dict):
        return result.get("data", {}).get("items", []) or []
    return []


def fetch_wealth_overview() -> tuple[dict | None, str]:
    return _fetch_api_dict("GET", "/reports/wealth-overview")


def _reports_year_bounds_iso(y: int) -> tuple[str, str]:
    z = _user_tzinfo()
    s = datetime(y, 1, 1, 0, 0, 0, tzinfo=z)
    e = datetime(y, 12, 31, 23, 59, 59, tzinfo=z)
    return s.isoformat(timespec="seconds"), e.isoformat(timespec="seconds")


def _reports_month_bounds_iso(y: int, m: int) -> tuple[str, str]:
    z = _user_tzinfo()
    last = calendar.monthrange(y, m)[1]
    s = datetime(y, m, 1, 0, 0, 0, tzinfo=z)
    e = datetime(y, m, last, 23, 59, 59, tzinfo=z)
    return s.isoformat(timespec="seconds"), e.isoformat(timespec="seconds")


def _reports_cashflow_metrics_row(data: dict) -> None:
    """收支报表一行：总收入（收入+股票+基金）、分项、实际支出、净额。"""

    def _cell(k: str) -> str:
        v = data.get(k)
        return str(v) if v is not None else "—"

    c0, c1, c2, c3, c4, c5 = st.columns(6, gap="small")
    with c0:
        st.metric(t("metric_reports_gross"), _cell("gross_income_total"))
    with c1:
        st.metric(t("metric_reports_income"), _cell("income_total"))
    with c2:
        st.metric(t("metric_reports_stock"), _cell("stock_gain_total"))
    with c3:
        st.metric(t("metric_reports_fund"), _cell("fund_gain_total"))
    with c4:
        st.metric(t("metric_actual_expense"), _cell("expense_total"))
    with c5:
        st.metric(t("metric_net"), _cell("net_total"))


def fetch_transactions_all_between(start_iso: str, end_iso: str) -> tuple[list[dict], str]:
    """分页拉取时间区间内的全部流水。"""
    out: list[dict] = []
    page = 1
    page_size = 100
    while True:
        ok, result = api_call(
            "GET",
            "/transactions",
            params={
                "page": page,
                "page_size": page_size,
                "start_date": start_iso,
                "end_date": end_iso,
            },
        )
        if not ok or not isinstance(result, dict):
            return [], str(result)
        data = result.get("data", {}) or {}
        chunk = list(data.get("items", []) or [])
        out.extend(chunk)
        total = int((data.get("pagination") or {}).get("total") or 0)
        if not chunk or len(out) >= total or len(chunk) < page_size:
            break
        page += 1
    return out, ""


def _reports_period_detail_rows(items: list[dict], assets: list[dict]) -> list[dict]:
    """收支明细：收入类、支出类、股票/基金卖出（收益行）。"""
    ast_by_id = {int(a["id"]): a for a in assets if a.get("id") is not None}
    out: list[dict] = []
    for row in items:
        ty = str(row.get("type") or "")
        if ty in ("income", "dividend", "transfer_in", "expense", "transfer_out"):
            out.append(row)
            continue
        if ty != "sell":
            continue
        aid = row.get("asset_id")
        if aid is None:
            continue
        try:
            ai = int(aid)
        except (TypeError, ValueError):
            continue
        a = ast_by_id.get(ai)
        if a and str(a.get("asset_type") or "") in ("stock", "fund"):
            out.append(row)

    def _occurred(r: dict) -> str:
        return str(r.get("occurred_at") or "")

    out.sort(key=_occurred, reverse=True)
    return out


def fetch_cashflow_summary_iso(start_iso: str, end_iso: str) -> tuple[dict | None, str]:
    """收支报表：收入 + 实际支出（不含证券 buy/sell）。"""
    ok, result = api_call(
        "GET",
        "/reports/cashflow-summary",
        params={"start_date": start_iso, "end_date": end_iso},
    )
    if not ok:
        return None, str(result)
    if not isinstance(result, dict):
        return None, t("err_not_json")
    data = result.get("data")
    if not isinstance(data, dict):
        return None, t("err_bad_api_data", typ=type(data).__name__)
    return data, ""


def fetch_pnl_overview() -> tuple[dict | None, str]:
    return _fetch_api_dict("GET", "/reports/pnl-overview")


def fetch_bank_catalog() -> list[dict]:
    ok, result = api_call("GET", "/accounts/bank-catalog")
    if not ok or not isinstance(result, dict):
        return []
    data = result.get("data")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [
                x
                for x in items
                if isinstance(x, dict) and (str(x.get("name") or "").strip())
            ]
    if isinstance(data, list):
        return [
            x
            for x in data
            if isinstance(x, dict) and (str(x.get("name") or "").strip())
        ]
    return []


def sync_bank_catalog_to_session() -> None:
    """写入 session：优先接口；若为空则用与后端一致的内置名录，避免首次拉取失败后一直为 []。"""
    remote = fetch_bank_catalog()
    if remote:
        st.session_state["bank_catalog"] = remote
        st.session_state.pop("bank_catalog_is_builtin", None)
        st.session_state.pop("_bank_catalog_load_attempted", None)
        return
    if BANK_CATALOG_BUILTIN:
        st.session_state["bank_catalog"] = [dict(x) for x in BANK_CATALOG_BUILTIN]
        st.session_state["bank_catalog_is_builtin"] = True
        st.session_state.pop("_bank_catalog_load_attempted", None)
        return
    st.session_state["bank_catalog"] = []
    st.session_state.pop("bank_catalog_is_builtin", None)
    st.session_state["_bank_catalog_load_attempted"] = True


def _account_pick_label(a: dict) -> str:
    owner = (a.get("owner_name") or "").strip()
    own = f" ·{owner}" if owner else ""
    return f"{a['id']} · {a['name']}{own} ({a['account_type']})"


def _account_transfer_label(a: dict) -> str:
    owner = (a.get("owner_name") or "").strip()
    own = f" ·{owner}" if owner else ""
    return f"{a['id']} · {a['name']}{own} ({a['balance']})"


def inject_login_page_css() -> None:
    st.markdown(
        """
        <style>
            /* 隐藏 Streamlit 默认顶栏（Deploy、⋮ 等） */
            header[data-testid="stHeader"] { display: none !important; }
            div[data-testid="stDecoration"] { display: none !important; }
            div[data-testid="stToolbar"],
            [data-testid="stAppToolbar"],
            [data-testid="stHeaderToolbar"] { display: none !important; }
            .stDeployButton,
            [data-testid="stToolbarActions"] { display: none !important; }
            [data-testid="stBottom"],
            footer,
            [data-testid="stStatusWidget"],
            div[data-testid="stThemeSwitcher"] { display: none !important; }

            [data-testid="stSidebar"] { display: none !important; }
            [data-testid="collapsedControl"] { display: none !important; }

            .stApp {
                background: linear-gradient(155deg, #050810 0%, #0c1526 38%, #0a1628 72%, #060d18 100%) !important;
            }
            .stApp::before {
                content: "";
                position: fixed;
                inset: 0;
                z-index: 0;
                pointer-events: none;
                background:
                    radial-gradient(ellipse 90% 55% at 50% -8%, rgba(56, 189, 248, 0.22), transparent 55%),
                    radial-gradient(ellipse 50% 45% at 100% 0%, rgba(99, 102, 241, 0.14), transparent 50%),
                    radial-gradient(ellipse 45% 40% at 0% 100%, rgba(34, 211, 238, 0.08), transparent 50%),
                    linear-gradient(rgba(148, 163, 184, 0.055) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(148, 163, 184, 0.055) 1px, transparent 1px);
                background-size: auto, auto, auto, 44px 44px, 44px 44px;
            }

            section[data-testid="stMain"] > div {
                position: relative;
                z-index: 1;
            }
            .block-container {
                max-width: 920px !important;
                padding-top: 4vh !important;
                padding-bottom: 3rem !important;
            }

            .login-brand h1 {
                color: #f8fafc;
                font-size: clamp(1.85rem, 4.2vw, 2.45rem);
                font-weight: 700;
                text-align: center;
                margin: 0 0 0.45rem 0;
                letter-spacing: 0.14em;
                text-shadow: 0 0 42px rgba(56, 189, 248, 0.35);
            }
            .login-brand .sub {
                color: #cbd5e1;
                text-align: center;
                font-size: 1.12rem;
                margin: 0 0 1.75rem 0;
                line-height: 1.55;
            }

            section[data-testid="stMain"] .stTextInput label p {
                text-align: center !important;
                font-size: 1.02rem !important;
                color: #cbd5e1 !important;
            }
            section[data-testid="stMain"] .stTextInput > div > div > input,
            section[data-testid="stMain"] .stTextInput input {
                font-size: 1.12rem !important;
                padding: 0.85rem 1.1rem !important;
                min-height: 52px !important;
                border-radius: 12px !important;
                text-align: center !important;
            }
            /* 登录页主区内独立按钮（若有） */
            section[data-testid="stMain"] .stButton > button {
                font-size: 1.1rem !important;
                font-weight: 600 !important;
                padding: 0.85rem 1.25rem !important;
                min-height: 52px !important;
                border-radius: 12px !important;
                width: 100% !important;
                background: linear-gradient(90deg, #0ea5e9, #6366f1) !important;
                color: #ffffff !important;
                border: none !important;
                box-shadow: 0 12px 28px rgba(14, 165, 233, 0.28);
            }
            section[data-testid="stMain"] .stButton > button:hover {
                box-shadow: 0 14px 36px rgba(99, 102, 241, 0.35);
            }
            section[data-testid="stMain"] .stButton > button p,
            section[data-testid="stMain"] .stButton > button span {
                color: #ffffff !important;
            }

            /* 表单内「进入系统」：部分主题会给深色字，这里强制高对比 */
            section[data-testid="stMain"] form .stButton > button,
            section[data-testid="stMain"] form button[type="submit"],
            section[data-testid="stMain"] form [data-baseweb="button"] {
                background: linear-gradient(92deg, #0284c7, #4f46e5) !important;
                -webkit-background-clip: border-box !important;
                background-clip: border-box !important;
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
                border: 1px solid rgba(125, 211, 252, 0.55) !important;
                font-size: 1.08rem !important;
                font-weight: 600 !important;
                min-height: 50px !important;
                border-radius: 12px !important;
                box-shadow: 0 10px 24px rgba(2, 132, 199, 0.35) !important;
            }
            section[data-testid="stMain"] form .stButton > button:hover,
            section[data-testid="stMain"] form button[type="submit"]:hover,
            section[data-testid="stMain"] form [data-baseweb="button"]:hover {
                background: linear-gradient(92deg, #0ea5e9, #6366f1) !important;
                -webkit-background-clip: border-box !important;
                background-clip: border-box !important;
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
                border-color: #e0f2fe !important;
                box-shadow: 0 12px 32px rgba(14, 165, 233, 0.42) !important;
                filter: none !important;
                opacity: 1 !important;
            }
            section[data-testid="stMain"] form .stButton > button:hover *,
            section[data-testid="stMain"] form button[type="submit"]:hover *,
            section[data-testid="stMain"] form [data-baseweb="button"]:hover * {
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
                opacity: 1 !important;
            }
            section[data-testid="stMain"] form .stButton > button:hover [data-baseweb="typography"],
            section[data-testid="stMain"] form button[type="submit"]:hover [data-baseweb="typography"],
            section[data-testid="stMain"] form [data-baseweb="button"]:hover [data-baseweb="typography"] {
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
            }
            section[data-testid="stMain"] form .stButton > button:focus-visible,
            section[data-testid="stMain"] form button[type="submit"]:focus-visible,
            section[data-testid="stMain"] form [data-baseweb="button"]:focus-visible {
                outline: 2px solid #7dd3fc !important;
                outline-offset: 2px !important;
            }
            section[data-testid="stMain"] form .stButton > button p,
            section[data-testid="stMain"] form .stButton > button span,
            section[data-testid="stMain"] form button[type="submit"] p,
            section[data-testid="stMain"] form button[type="submit"] span,
            section[data-testid="stMain"] form [data-baseweb="button"] p,
            section[data-testid="stMain"] form [data-baseweb="button"] span {
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
            }

            /* 登录页说明文字（st.caption） */
            section[data-testid="stMain"] .stCaption,
            section[data-testid="stMain"] [data-testid="stCaption"],
            section[data-testid="stMain"] [data-testid="stCaption"] p,
            section[data-testid="stMain"] div[data-testid="stCaption"] {
                color: #e2e8f0 !important;
                font-size: 0.98rem !important;
            }

            section[data-testid="stMain"] form {
                background: rgba(15, 23, 42, 0.78);
                border: 1px solid rgba(56, 189, 248, 0.28);
                border-radius: 18px;
                padding: 1.85rem 1.65rem 1.65rem;
                box-shadow: 0 28px 56px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.06);
                backdrop-filter: blur(14px);
                margin-top: 0.5rem;
            }
            /* st.subheader 在表单内多为 Markdown 的 h2/h3，单独拉高对比 */
            section[data-testid="stMain"] form h1,
            section[data-testid="stMain"] form h2,
            section[data-testid="stMain"] form h3,
            section[data-testid="stMain"] form .stMarkdown h1,
            section[data-testid="stMain"] form .stMarkdown h2,
            section[data-testid="stMain"] form .stMarkdown h3,
            section[data-testid="stMain"] form [data-testid="stMarkdownContainer"] h1,
            section[data-testid="stMain"] form [data-testid="stMarkdownContainer"] h2,
            section[data-testid="stMain"] form [data-testid="stMarkdownContainer"] h3 {
                color: #f8fafc !important;
                text-align: center !important;
                font-weight: 700 !important;
                font-size: 1.28rem !important;
                margin-bottom: 1rem !important;
                text-shadow: 0 1px 3px rgba(0, 0, 0, 0.55);
            }

            /* 展开条头部：浅字 + 略亮底 */
            section[data-testid="stMain"] .streamlit-expanderHeader {
                justify-content: center !important;
                font-size: 1.05rem !important;
                font-weight: 500 !important;
                color: #f1f5f9 !important;
                background: rgba(30, 41, 59, 0.75) !important;
                border-radius: 12px !important;
                padding: 0.65rem 0.75rem !important;
                border: 1px solid rgba(148, 163, 184, 0.35) !important;
            }
            section[data-testid="stMain"] .streamlit-expanderHeader p,
            section[data-testid="stMain"] .streamlit-expanderHeader span,
            section[data-testid="stMain"] [data-testid="stExpander"] summary,
            section[data-testid="stMain"] [data-testid="stExpander"] summary span {
                color: #f8fafc !important;
            }
            section[data-testid="stMain"] [data-testid="stExpander"] svg {
                fill: #e2e8f0 !important;
                color: #e2e8f0 !important;
            }
            section[data-testid="stMain"] [data-testid="stExpander"] {
                background: rgba(15, 23, 42, 0.55);
                border: 1px solid rgba(148, 163, 184, 0.28);
                border-radius: 14px;
                margin-top: 1.25rem;
            }
            section[data-testid="stMain"] [data-testid="stExpander"] details {
                border: none !important;
            }

            /* 登录页：新版 st.toggle 为 data-testid=stCheckbox + baseweb checkbox，非 baseweb switch */
            section[data-testid="stMain"] [data-testid="stCheckbox"] [data-testid="stWidgetLabel"],
            section[data-testid="stMain"] [data-testid="stCheckbox"] [data-testid="stWidgetLabel"] *,
            section[data-testid="stMain"] [data-testid="stCheckbox"] label,
            section[data-testid="stMain"] [data-testid="stCheckbox"] label *,
            section[data-testid="stMain"] [data-testid="stCheckbox"] p,
            section[data-testid="stMain"] [data-testid="stCheckbox"] span,
            section[data-testid="stMain"] [data-testid="stCheckbox"] [data-baseweb="typography"],
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stWidgetLabel"],
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stWidgetLabel"] * {
                color: #f8fafc !important;
                -webkit-text-fill-color: #f8fafc !important;
            }
            section[data-testid="stMain"] [data-testid="stCheckbox"] a,
            section[data-testid="stMain"] [data-testid="stCheckbox"] svg,
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] a,
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] svg {
                color: #e2e8f0 !important;
                fill: #e2e8f0 !important;
                stroke: #e2e8f0 !important;
            }
            section[data-testid="stMain"] [data-testid="stCheckbox"] [data-baseweb="checkbox"] {
                background-color: rgba(255, 255, 255, 0.38) !important;
            }
            /* 语言开关容器：圆角矩形 + 留白（登录页） */
            section[data-testid="stMain"] div[data-testid="element-container"][class*="st-key-_fm_ui_english_toggle"],
            section[data-testid="stMain"] div[data-testid="element-container"][class*="st-key-fm_lang_toggle_btn"] {
                background: rgba(15, 23, 42, 0.78) !important;
                border: 1px solid rgba(148, 163, 184, 0.45) !important;
                border-radius: 16px !important;
                padding: 0.6rem 1.25rem 0.6rem 1rem !important;
                margin: 0 0 0.55rem auto !important;
                box-shadow: 0 6px 22px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.07) !important;
                width: fit-content !important;
                max-width: 100% !important;
            }
            section[data-testid="stMain"] div[data-testid="element-container"][class*="st-key-_fm_ui_english_toggle"] [data-testid="stVerticalBlock"],
            section[data-testid="stMain"] div[data-testid="element-container"][class*="st-key-fm_lang_toggle_btn"] [data-testid="stVerticalBlock"] {
                gap: 0.35rem !important;
            }
            /* 登录失败等 st.error：深色背景下必须可见（否则像「点了没反应」） */
            section[data-testid="stMain"] [data-testid="stAlert"],
            section[data-testid="stMain"] div[data-testid="stAlert"] {
                margin-top: 1rem !important;
            }
            section[data-testid="stMain"] [data-testid="stAlert"] p,
            section[data-testid="stMain"] [data-testid="stAlert"] span,
            section[data-testid="stMain"] div[data-testid="stAlert"] p,
            section[data-testid="stMain"] div[data-testid="stAlert"] span {
                color: #fecaca !important;
                -webkit-text-fill-color: #fecaca !important;
            }
            /* 更旧 Streamlit 若仍用 baseweb switch */
            section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has([data-baseweb="switch"]) [data-testid="stWidgetLabel"],
            section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has([data-baseweb="switch"]) [data-testid="stWidgetLabel"] * {
                color: #f8fafc !important;
                -webkit-text-fill-color: #f8fafc !important;
            }
            /* 无 st.toggle 时：语言行在首行横向块最右列 */
            section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div:first-child [data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child .stButton > button {
                color: #f8fafc !important;
                border: 1px solid rgba(248, 250, 252, 0.65) !important;
                background: rgba(15, 23, 42, 0.55) !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_app_css() -> None:
    st.markdown(
        """
        <style>
            /* Streamlit 默认顶栏：Deploy、⋮ 等（本地自用无意义），去掉可消除一大块空白 */
            header[data-testid="stHeader"] {
                display: none !important;
            }
            div[data-testid="stDecoration"] {
                display: none !important;
            }
            /* 其余壳层：工具条、底栏、左下角状态、主题切换、开发时「文件已变/Rerun」条等 */
            div[data-testid="stToolbar"],
            [data-testid="stAppToolbar"],
            [data-testid="stHeaderToolbar"],
            [data-testid="stBottom"],
            footer,
            [data-testid="stStatusWidget"],
            div[data-testid="stThemeSwitcher"] {
                display: none !important;
            }
            .stDeployButton,
            [data-testid="stToolbarActions"] {
                display: none !important;
            }
            /* 主内容区顶距（原 2rem 易显「大白边」） */
            .block-container {
                padding-top: 0.6rem !important;
                padding-bottom: 1.25rem !important;
                padding-left: 1.5rem !important;
                padding-right: 1.5rem !important;
                max-width: 100% !important;
            }
            section[data-testid="stMain"] {
                overflow-x: hidden !important;
                overflow-y: auto !important;
            }
            section[data-testid="stMain"] > div {
                background-color: #f1f5f9;
            }

            /* 主界面：仅语言 toggle（widget key），避免误伤其它 checkbox */
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stWidgetLabel"],
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stWidgetLabel"] *,
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stCheckbox"] label,
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stCheckbox"] label *,
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stCheckbox"] p,
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stCheckbox"] span,
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stCheckbox"] [data-baseweb="typography"] {
                color: #0f172a !important;
                -webkit-text-fill-color: #0f172a !important;
            }
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] a,
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] svg {
                color: #475569 !important;
                fill: #475569 !important;
                stroke: #475569 !important;
            }
            section[data-testid="stMain"] [class*="st-key-_fm_ui_english_toggle"] [data-testid="stCheckbox"] [data-baseweb="checkbox"] {
                background-color: #cbd5e1 !important;
            }
            /* 语言开关容器：圆角矩形 + 留白（主界面浅底） */
            section[data-testid="stMain"] div[data-testid="element-container"][class*="st-key-_fm_ui_english_toggle"],
            section[data-testid="stMain"] div[data-testid="element-container"][class*="st-key-fm_lang_toggle_btn"] {
                background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%) !important;
                border: 1px solid #cbd5e1 !important;
                border-radius: 16px !important;
                padding: 0.6rem 1.2rem 0.6rem 0.95rem !important;
                margin: 0 0 0.5rem auto !important;
                box-shadow: 0 2px 10px rgba(15, 23, 42, 0.07), inset 0 1px 0 rgba(255, 255, 255, 0.95) !important;
                width: fit-content !important;
                max-width: 100% !important;
            }
            section[data-testid="stMain"] div[data-testid="element-container"][class*="st-key-_fm_ui_english_toggle"] [data-testid="stVerticalBlock"],
            section[data-testid="stMain"] div[data-testid="element-container"][class*="st-key-fm_lang_toggle_btn"] [data-testid="stVerticalBlock"] {
                gap: 0.35rem !important;
            }
            section[data-testid="stMain"] div[data-testid="stColumn"]:has([data-baseweb="switch"]) label,
            section[data-testid="stMain"] div[data-testid="stColumn"]:has([data-baseweb="switch"]) [data-testid="stWidgetLabel"],
            section[data-testid="stMain"] div[data-testid="stColumn"]:has([data-baseweb="switch"]) [data-testid="stWidgetLabel"] * {
                color: #0f172a !important;
            }
            section[data-testid="stMain"] div[data-testid="stColumn"]:has([data-baseweb="switch"]) [data-baseweb="switch"] {
                background-color: #cbd5e1 !important;
            }
            section[data-testid="stMain"] div[data-testid="stColumn"]:has([data-baseweb="switch"]) [data-baseweb="switch"] > div:last-child {
                background-color: #f8fafc !important;
                box-shadow: 0 1px 2px rgba(15, 23, 42, 0.18) !important;
            }
            section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div:first-child [data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child .stButton > button {
                color: #0f172a !important;
                border: 1px solid #94a3b8 !important;
                background: #e2e8f0 !important;
            }

            section[data-testid="stMain"] h1,
            section[data-testid="stMain"] h2,
            section[data-testid="stMain"] h3,
            section[data-testid="stMain"] [data-testid="stMarkdownContainer"] h1,
            section[data-testid="stMain"] [data-testid="stMarkdownContainer"] h2,
            section[data-testid="stMain"] [data-testid="stMarkdownContainer"] h3 {
                line-height: 1.45 !important;
                padding-top: 0.35rem !important;
                margin-top: 0.35rem !important;
                margin-bottom: 0.55rem !important;
                overflow: visible !important;
                letter-spacing: 0.02em;
            }
            section[data-testid="stMain"] [data-testid="stHeading"] {
                overflow: visible !important;
            }
            /* 顶栏标题：与右侧按钮同一行视觉对齐（Streamlit 多列默认顶对齐且 Markdown 外包层有留白） */
            section[data-testid="stMain"] .fm-toolbar-page-title {
                font-size: clamp(1.35rem, 2.2vw, 1.95rem) !important;
                font-weight: 700 !important;
                color: #0f172a !important;
                margin: 0 !important;
                line-height: 1.15 !important;
                padding: 0 !important;
                letter-spacing: 0.02em !important;
                display: inline-block !important;
                vertical-align: middle !important;
            }
            section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.fm-toolbar-page-title) {
                align-items: center !important;
            }
            /* 勿给 column 再套 flex，会与 Streamlit 自带纵向对齐冲突 */
            section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.fm-toolbar-page-title) [data-testid="stMarkdownContainer"] {
                margin-top: 0 !important;
                margin-bottom: 0 !important;
                padding-top: 0 !important;
                padding-bottom: 0 !important;
            }
            section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.fm-toolbar-page-title) [data-testid="stMarkdownContainer"] p {
                margin: 0 !important;
                padding: 0 !important;
                line-height: 1.25 !important;
            }
            section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.fm-toolbar-page-title) [data-testid="element-container"] {
                margin-top: 0 !important;
                margin-bottom: 0 !important;
            }
            /* 顶栏操作按钮：不要铺满整列（避免「新增标的」巨块） */
            section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.fm-toolbar-page-title) .stButton > button {
                width: auto !important;
                max-width: 100% !important;
            }
            section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div {
                overflow: visible !important;
            }
            section[data-testid="stMain"] .element-container {
                overflow: visible !important;
            }

            /* ---------- 左侧栏：高对比、与登录页一致的科技风 ---------- */
            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, #0b1220 0%, #111827 45%, #0f172a 100%) !important;
                border-right: 1px solid rgba(56, 189, 248, 0.22) !important;
                box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.04);
            }
            [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
                padding-top: 1rem;
            }
            /* 仅含按钮的区块留间距（含功能菜单与退出） */
            [data-testid="stSidebar"] [data-testid="element-container"]:has(.stButton) {
                margin-bottom: 0.35rem !important;
            }

            /* 侧栏内所有常见文字节点 */
            [data-testid="stSidebar"] h1,
            [data-testid="stSidebar"] h2,
            [data-testid="stSidebar"] h3,
            [data-testid="stSidebar"] p,
            [data-testid="stSidebar"] span,
            [data-testid="stSidebar"] li,
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span,
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
                color: #f1f5f9 !important;
            }

            [data-testid="stSidebar"] .stCaption,
            [data-testid="stSidebar"] [data-testid="stCaption"],
            [data-testid="stSidebar"] div[data-testid="stCaption"] {
                color: #cbd5e1 !important;
                font-size: 0.92rem !important;
            }

            [data-testid="stSidebar"] hr {
                margin: 1rem 0 !important;
                border: none !important;
                border-top: 1px solid rgba(148, 163, 184, 0.35) !important;
            }

            /* 功能菜单：整行按钮（替代 radio，整行可点） */
            [data-testid="stSidebar"] .stButton > button {
                width: 100% !important;
                min-height: 2.75rem !important;
                border-radius: 10px !important;
                font-size: 1rem !important;
                justify-content: center !important;
            }
            [data-testid="stSidebar"] .stButton > button[kind="secondary"],
            [data-testid="stSidebar"] button[data-testid="baseButton-secondary"] {
                background: rgba(30, 41, 59, 0.72) !important;
                color: #f8fafc !important;
                border: 1px solid rgba(148, 163, 184, 0.35) !important;
                font-weight: 500 !important;
            }
            [data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover,
            [data-testid="stSidebar"] button[data-testid="baseButton-secondary"]:hover {
                border-color: rgba(125, 211, 252, 0.65) !important;
                background: rgba(51, 65, 85, 0.85) !important;
                color: #ffffff !important;
            }
            [data-testid="stSidebar"] .stButton > button[kind="primary"],
            [data-testid="stSidebar"] button[data-testid="baseButton-primary"] {
                background: linear-gradient(92deg, #0369a1, #4f46e5) !important;
                color: #ffffff !important;
                border: 1px solid rgba(125, 211, 252, 0.55) !important;
                font-weight: 600 !important;
                box-shadow: 0 6px 18px rgba(2, 132, 199, 0.28) !important;
            }
            [data-testid="stSidebar"] .stButton > button:focus {
                box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.45) !important;
            }
            [data-testid="stSidebar"] .stButton > button p,
            [data-testid="stSidebar"] .stButton > button span {
                color: inherit !important;
            }

            /* 侧栏标题块（HTML 注入） */
            .fm-sidebar-nav-title {
                color: #f8fafc !important;
                font-size: 1.12rem !important;
                font-weight: 700 !important;
                letter-spacing: 0.12em !important;
                margin: 0 0 0.85rem 0 !important;
                padding-bottom: 0.5rem !important;
                border-bottom: 1px solid rgba(56, 189, 248, 0.35) !important;
                text-shadow: 0 0 20px rgba(56, 189, 248, 0.25);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_login_form_button_css_tail() -> None:
    """放在登录表单之后注入，覆盖 Streamlit 主题在悬停时写入的样式（含透明字/渐变裁切）。"""
    st.markdown(
        """
        <style>
            section[data-testid="stMain"] form button {
                -webkit-background-clip: border-box !important;
                background-clip: border-box !important;
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
            }
            section[data-testid="stMain"] form button:hover,
            section[data-testid="stMain"] form button:focus,
            section[data-testid="stMain"] form button:focus-visible {
                -webkit-background-clip: border-box !important;
                background-clip: border-box !important;
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
            }
            section[data-testid="stMain"] form button *,
            section[data-testid="stMain"] form button:hover *,
            section[data-testid="stMain"] form button:focus *,
            section[data-testid="stMain"] form button:focus-visible * {
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
                -webkit-background-clip: border-box !important;
                background-clip: border-box !important;
            }
            section[data-testid="stMain"] form [data-testid^="stBaseButton"],
            section[data-testid="stMain"] form [data-testid^="stBaseButton"]:hover,
            section[data-testid="stMain"] form [data-testid^="stBaseButton"]:hover * {
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
                -webkit-background-clip: border-box !important;
                background-clip: border-box !important;
            }
            section[data-testid="stMain"] form button[kind="formSubmit"],
            section[data-testid="stMain"] form button[kind="formSubmit"]:hover,
            section[data-testid="stMain"] form button[kind="formSubmit"]:hover * {
                color: #ffffff !important;
                -webkit-text-fill-color: #ffffff !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_login_screen() -> None:
    inject_login_page_css()
    render_language_switcher()
    left, center_col, right = st.columns([0.1, 0.8, 0.1])
    with center_col:
        st.markdown(
            f"""
            <div class="login-brand">
              <h1>{html.escape(t("login_title"))}</h1>
              <p class="sub">{html.escape(t("login_subtitle"))}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("login_form"):
            st.subheader(t("login_header"))
            username = st.text_input(t("username"), key="login_username")
            password = st.text_input(t("password"), type="password", key="login_password")
            submitted = st.form_submit_button(t("login_submit"), use_container_width=True)
            # 须在 form 内处理提交（官方示例）；放在外侧易导致提交后逻辑不执行或状态异常
            if submitted:
                ok, result = api_call(
                    "POST",
                    "/auth/login",
                    payload={"username": username, "password": password},
                    require_auth=False,
                )
                if ok and isinstance(result, dict):
                    data = result.get("data", {})
                    token = data.get("access_token")
                    if token:
                        st.session_state["token"] = token
                        st.session_state["username"] = username
                        st.session_state["nav_page"] = "overview"
                        st.session_state.pop("bank_catalog", None)
                        st.session_state.pop("_bank_catalog_load_attempted", None)
                        for _dk in (
                            *SESSION_DLG_KEYS,
                            *SESSION_TX_DETAIL_KEYS,
                            *SESSION_GRID_KEYS,
                            *SESSION_PENDING_GRID_CLEAR_KEYS,
                        ):
                            st.session_state.pop(_dk, None)
                        _persist_auth_cookie(str(token), str(username))
                        st.rerun()
                    else:
                        st.error(t("err_no_token"))
                else:
                    st.error(result)

        inject_login_form_button_css_tail()


def render_sidebar_nav() -> str:
    st.sidebar.markdown(
        '<p class="fm-sidebar-nav-title" style="color:#f8fafc;font-size:1.12rem;font-weight:700;'
        'letter-spacing:0.1em;margin:0 0 0.85rem 0;padding-bottom:0.45rem;'
        f'border-bottom:1px solid rgba(56,189,248,0.4);">{html.escape(t("nav_menu_title"))}</p>',
        unsafe_allow_html=True,
    )

    current = st.session_state.get("nav_page", "overview")
    for page_key, label_key in MENU_PAGES:
        label = t(label_key)
        is_active = current == page_key
        if st.sidebar.button(
            label,
            key=f"fm_nav_{page_key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            for _dk in (
                *SESSION_DLG_KEYS,
                *SESSION_TX_DETAIL_KEYS,
                *SESSION_GRID_KEYS,
                *SESSION_PENDING_GRID_CLEAR_KEYS,
            ):
                st.session_state.pop(_dk, None)
            st.session_state["nav_page"] = page_key
            st.rerun()

    st.sidebar.divider()
    st.sidebar.caption(t("user_label", name=st.session_state.get("username", "") or "—"))
    if st.sidebar.button(t("logout"), key="fm_logout", use_container_width=True, type="primary"):
        _clear_auth_cookie()
        for k in (
            "token",
            "username",
            "nav_page",
            "bank_catalog",
            "bank_catalog_is_builtin",
            "_bank_catalog_load_attempted",
            *SESSION_DLG_KEYS,
            *SESSION_TX_DETAIL_KEYS,
            *SESSION_GRID_KEYS,
            *SESSION_PENDING_GRID_CLEAR_KEYS,
        ):
            st.session_state.pop(k, None)
        st.rerun()

    return st.session_state.get("nav_page", "overview")


def _form_field_row(label: str):
    """两列表格：左列标签，右列放控件（右列用 with 包裹）。"""
    lc, rc = st.columns([0.28, 0.72], gap="small")
    with lc:
        st.markdown(
            f'<p style="margin:0;padding-top:0.55rem;font-weight:600;color:#0f172a;">{label}</p>',
            unsafe_allow_html=True,
        )
    return rc


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_new_account)
def _dialog_new_account() -> None:
    st.subheader(t("dlg_new_account"))
    if "bank_catalog" not in st.session_state:
        sync_bank_catalog_to_session()
    elif not st.session_state.get("bank_catalog") and not st.session_state.get(
        "_bank_catalog_load_attempted"
    ):
        sync_bank_catalog_to_session()

    b0, b1 = st.columns([0.35, 0.65])
    with b0:
        if st.button(t("dlg_close"), key="dlg_acc_close"):
            st.session_state.pop("dlg_account_open", None)
            st.rerun()
    with b1:
        if st.button(t("dlg_reload_catalog"), key="dlg_acc_reload"):
            st.session_state.pop("_bank_catalog_load_attempted", None)
            sync_bank_catalog_to_session()
            st.rerun()

    _acc_types = ["bank", "alipay", "wechat", "broker", "cash"]
    right = _form_field_row(t("dlg_acc_type"))
    with right:
        account_type = st.selectbox(
            "dlg_acc_t",
            _acc_types,
            format_func=account_type_label,
            label_visibility="collapsed",
            key="dlg_acc_type",
        )

    resolved_name = ""
    bank_code_val: str | None = None

    if account_type == "bank":
        catalog = [
            b
            for b in (st.session_state.get("bank_catalog") or [])
            if isinstance(b, dict) and (b.get("name") or "").strip()
        ]
        right = _form_field_row(t("dlg_bank_name"))
        with right:
            if not catalog:
                st.warning(t("dlg_catalog_empty"))
                resolved_name = st.text_input(
                    "dlg_acc_nm",
                    value=t("dlg_bank_manual_name_ph"),
                    label_visibility="collapsed",
                    key="dlg_acc_bank_manual_name",
                )
                bank_code_val = None
            else:
                bi = st.selectbox(
                    "dlg_acc_bi",
                    options=list(range(len(catalog))),
                    format_func=lambda i: str(catalog[i]["name"]),
                    label_visibility="collapsed",
                    key="dlg_acc_bank_pick",
                )
                b = catalog[int(bi)]
                bank_code_val = b["code"]
                base = str(b["name"])

        if catalog:
            right = _form_field_row(t("dlg_note"))
            with right:
                card_note = st.text_input(
                    "dlg_acc_cn",
                    value="",
                    label_visibility="collapsed",
                    key="dlg_acc_bank_note",
                )
            resolved_name = f"{base}·{card_note.strip()}" if card_note.strip() else base
    else:
        right = _form_field_row(t("dlg_acc_name"))
        with right:
            resolved_name = st.text_input(
                "dlg_acc_on",
                value=t("dlg_default_alipay"),
                label_visibility="collapsed",
                key=f"dlg_acc_other_name_{account_type}",
            )

    with st.form("dlg_create_account_form"):
        right = _form_field_row(t("dlg_owner"))
        with right:
            owner_name = st.text_input(
                "dlg_acc_ow",
                value="",
                label_visibility="collapsed",
                key="dlg_acc_owner",
            )
        right = _form_field_row(t("dlg_currency"))
        with right:
            currency = st.text_input(
                "dlg_acc_cur",
                value="CNY",
                label_visibility="collapsed",
                key="dlg_acc_currency",
            )
        right = _form_field_row(t("dlg_initial_balance"))
        with right:
            initial_balance = st.text_input(
                "dlg_acc_bal",
                value="0",
                label_visibility="collapsed",
                key="dlg_acc_balance",
            )
        submit = st.form_submit_button(t("dlg_save"))
    if submit:
        owner_payload = owner_name.strip() or None
        payload: dict[str, object] = {
            "name": resolved_name.strip(),
            "account_type": account_type,
            "currency": currency,
            "initial_balance": initial_balance,
            "owner_name": owner_payload,
        }
        if bank_code_val:
            payload["bank_code"] = bank_code_val
        ok, result = api_call("POST", "/accounts", payload=payload)
        st.success(str(result)) if ok else st.error(result)
        if ok:
            st.session_state.pop("dlg_account_open", None)
            st.rerun()


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_account_pick)
def _dialog_account_pick_actions() -> None:
    """列表行选后：修改 / 删除。"""
    raw_id = st.session_state.get("dlg_account_pick_id")
    if raw_id is None:
        return
    aid = int(raw_id)

    st.subheader(t("dlg_row_actions_title"))
    if st.button(t("dlg_close"), key=f"dlg_acc_pick_close_{aid}"):
        st.session_state.pop("dlg_account_pick_id", None)
        _request_clear_fm_accounts_grid()
        st.rerun()

    items = fetch_accounts()
    acc = next((a for a in items if int(a.get("id") or 0) == aid), None)
    if not acc:
        st.error(t("err_account_not_found"))
        if st.button(t("dlg_close"), key=f"dlg_acc_pick_nf_{aid}"):
            st.session_state.pop("dlg_account_pick_id", None)
            _request_clear_fm_accounts_grid()
            st.rerun()
        return

    st.markdown(html.escape(_account_pick_label(acc)))
    c0, c1 = st.columns(2)
    with c0:
        if st.button(t("btn_edit_account"), key=f"dlg_acc_pick_edit_{aid}", use_container_width=True):
            st.session_state.pop("dlg_account_pick_id", None)
            st.session_state["dlg_account_edit_id"] = aid
            _request_clear_fm_accounts_grid()
            st.rerun()
    with c1:
        if st.button(t("btn_delete_account"), key=f"dlg_acc_pick_del_{aid}", use_container_width=True):
            st.session_state.pop("dlg_account_pick_id", None)
            st.session_state["dlg_account_delete_id"] = aid
            _request_clear_fm_accounts_grid()
            st.rerun()


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_delete_account)
def _dialog_delete_account() -> None:
    raw_id = st.session_state.get("dlg_account_delete_id")
    if raw_id is None:
        return
    aid = int(raw_id)

    if st.button(t("dlg_close"), key=f"dlg_dacc_close_{aid}"):
        st.session_state.pop("dlg_account_delete_id", None)
        _request_clear_fm_accounts_grid()
        st.rerun()

    items = fetch_accounts()
    acc = next((a for a in items if int(a.get("id") or 0) == aid), None)
    if not acc:
        st.error(t("err_account_not_found"))
        return

    st.subheader(t("dlg_delete_account"))
    st.markdown(html.escape(_fmt_account_brief(acc)))

    confirm = st.checkbox(t("dlg_delete_account_confirm"), key=f"dlg_dacc_confirm_{aid}")
    if st.button(t("dlg_delete_account_submit"), key=f"dlg_dacc_go_{aid}", disabled=not confirm):
        ok, result = api_call("DELETE", f"/accounts/{aid}")
        if ok:
            st.success(t("msg_delete_ok"))
        else:
            st.error(_friendly_delete_error(result, kind="account"))
        if ok:
            st.session_state.pop("dlg_account_delete_id", None)
            _request_clear_fm_accounts_grid()
            st.rerun()


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_edit_account)
def _dialog_edit_account() -> None:
    raw_id = st.session_state.get("dlg_account_edit_id")
    if raw_id is None:
        return
    aid = int(raw_id)

    st.subheader(t("dlg_edit_account"))
    b0, b1 = st.columns([0.5, 0.5])
    with b0:
        if st.button(t("dlg_close"), key=f"dlg_eacc_close_{aid}"):
            st.session_state.pop("dlg_account_edit_id", None)
            _request_clear_fm_accounts_grid()
            st.rerun()
    with b1:
        if st.button(t("dlg_reload_catalog"), key=f"dlg_eacc_reload_{aid}"):
            st.session_state.pop("_bank_catalog_load_attempted", None)
            sync_bank_catalog_to_session()
            st.rerun()

    items = fetch_accounts()
    acc = next((a for a in items if int(a.get("id") or 0) == aid), None)
    if not acc:
        st.error(t("err_account_not_found"))
        if st.button(t("dlg_close"), key=f"dlg_eacc_nf_{aid}"):
            st.session_state.pop("dlg_account_edit_id", None)
            _request_clear_fm_accounts_grid()
            st.rerun()
        return

    if "bank_catalog" not in st.session_state:
        sync_bank_catalog_to_session()

    atype = str(acc.get("account_type") or "").strip()
    cur_bank = (acc.get("bank_code") or "").strip() or None

    with st.form(f"dlg_edit_account_form_{aid}"):
        right = _form_field_row(t("dlg_acc_name_edit"))
        with right:
            name_v = st.text_input(
                "dlg_eacc_nm",
                value=str(acc.get("name") or ""),
                label_visibility="collapsed",
                key=f"dlg_eacc_name_{aid}",
            )
        right = _form_field_row(t("dlg_owner"))
        with right:
            owner_v = st.text_input(
                "dlg_eacc_ow",
                value=str(acc.get("owner_name") or ""),
                label_visibility="collapsed",
                key=f"dlg_eacc_owner_{aid}",
            )
        right = _form_field_row(t("dlg_currency"))
        with right:
            cur_v = st.text_input(
                "dlg_eacc_cur",
                value=str(acc.get("currency") or "CNY"),
                label_visibility="collapsed",
                key=f"dlg_eacc_currency_{aid}",
            )
        right = _form_field_row(t("dlg_acc_active"))
        with right:
            active_v = st.checkbox(
                "dlg_eacc_act",
                value=bool(acc.get("is_active", True)),
                label_visibility="collapsed",
                key=f"dlg_eacc_active_{aid}",
            )

        bank_sel: str | None = None
        if atype == "bank":
            catalog = [
                b
                for b in (st.session_state.get("bank_catalog") or [])
                if isinstance(b, dict) and (b.get("name") or "").strip()
            ]
            right = _form_field_row(t("dlg_bank_name"))
            with right:
                if catalog:
                    codes = [str(b["code"]) for b in catalog]
                    try:
                        def_idx = codes.index(cur_bank) if cur_bank in codes else 0
                    except ValueError:
                        def_idx = 0
                    bi = st.selectbox(
                        "dlg_eacc_bank",
                        options=list(range(len(catalog))),
                        index=def_idx,
                        format_func=lambda i: str(catalog[int(i)]["name"]),
                        label_visibility="collapsed",
                        key=f"dlg_eacc_bank_{aid}",
                    )
                    bank_sel = str(catalog[int(bi)]["code"])
                else:
                    st.caption(t("dlg_catalog_empty"))
                    bank_sel = cur_bank

        submit = st.form_submit_button(t("dlg_save"))

    if submit:
        payload: dict[str, object] = {
            "name": name_v.strip(),
            "owner_name": owner_v.strip() or None,
            "currency": (cur_v or "CNY").strip().upper(),
            "is_active": bool(active_v),
        }
        if atype == "bank":
            payload["bank_code"] = bank_sel
        ok, result = api_call("PATCH", f"/accounts/{aid}", payload=payload)
        st.success(str(result)) if ok else st.error(result)
        if ok:
            st.session_state.pop("dlg_account_edit_id", None)
            _request_clear_fm_accounts_grid()
            st.rerun()


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_new_asset)
def _dialog_new_asset() -> None:
    st.subheader(t("dlg_new_asset"))
    if st.button(t("dlg_close"), key="dlg_ast_close"):
        st.session_state.pop("dlg_asset_open", None)
        st.rerun()

    # 查询结果必须在实例化带 key 的输入框之前写入对应 session_state（见 Streamlit 限制）。
    _pending = st.session_state.pop("_dlg_ast_post_lookup", None)
    if isinstance(_pending, dict):
        if _pending.get("name"):
            st.session_state["dlg_ast_name"] = str(_pending["name"])
        if _pending.get("market"):
            st.session_state["dlg_ast_market"] = str(_pending["market"])

    with st.form("dlg_create_asset_form"):
        right = _form_field_row(t("dlg_asset_type"))
        with right:
            st.selectbox(
                "dlg_ast_at",
                ["stock", "fund"],
                label_visibility="collapsed",
                key="dlg_ast_type",
            )
        right = _form_field_row(t("dlg_symbol"))
        with right:
            c_sym, c_qry = st.columns([4, 1], gap="small", vertical_alignment="center")
            with c_sym:
                st.text_input(
                    "dlg_ast_sym",
                    label_visibility="collapsed",
                    key="dlg_ast_symbol",
                    max_chars=16,
                )
            with c_qry:
                query_submit = st.form_submit_button(t("dlg_ast_query"), use_container_width=True)
        right = _form_field_row(t("dlg_name"))
        with right:
            st.text_input(
                "dlg_ast_nm",
                label_visibility="collapsed",
                key="dlg_ast_name",
            )
        right = _form_field_row(t("dlg_market"))
        with right:
            st.text_input(
                "dlg_ast_mkt",
                label_visibility="collapsed",
                key="dlg_ast_market",
            )
        save_submit = st.form_submit_button(t("dlg_save"))

    if query_submit:
        asset_type_q = str(st.session_state.get("dlg_ast_type") or "stock")
        sym_raw = st.session_state.get("dlg_ast_symbol", "")
        sym_digits = "".join(c for c in str(sym_raw) if c.isdigit())
        if len(sym_digits) != 6:
            st.warning(t("err_ast_code_six"))
        else:
            with st.spinner(t("dlg_ast_query_running")):
                name_g, mkt_g, errk = lookup_cn_security(asset_type_q, sym_digits)
            if errk == LOOKUP_BAD_INPUT:
                st.warning(t("err_ast_code_six"))
            elif errk == LOOKUP_NOT_FOUND:
                st.error(t("err_ast_lookup_not_found"))
            elif errk == LOOKUP_NETWORK:
                st.error(t("err_ast_lookup_network"))
            elif name_g:
                pl: dict[str, str] = {"name": name_g}
                if mkt_g:
                    pl["market"] = mkt_g
                st.session_state["_dlg_ast_post_lookup"] = pl
                st.rerun()
            else:
                st.error(t("err_ast_lookup_not_found"))

    if save_submit:
        asset_type = str(st.session_state.get("dlg_ast_type") or "stock")
        symbol = str(st.session_state.get("dlg_ast_symbol") or "").strip()
        name = str(st.session_state.get("dlg_ast_name") or "").strip()
        market = str(st.session_state.get("dlg_ast_market") or "").strip()
        if not symbol or not symbol.isdigit():
            st.error(t("err_ast_symbol_digits"))
            return
        ok, result = api_call(
            "POST",
            "/assets",
            payload={
                "asset_type": asset_type,
                "symbol": symbol,
                "name": name,
                "market": market or None,
            },
        )
        st.success(str(result)) if ok else st.error(result)
        if ok:
            st.session_state.pop("dlg_asset_open", None)
            st.session_state.pop("_dlg_ast_post_lookup", None)
            for _k in ("dlg_ast_symbol", "dlg_ast_name", "dlg_ast_market"):
                st.session_state.pop(_k, None)
            st.rerun()


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_asset_pick)
def _dialog_asset_pick_actions() -> None:
    """列表行选后：修改 / 删除。"""
    raw_id = st.session_state.get("dlg_asset_pick_id")
    if raw_id is None:
        return
    aid = int(raw_id)

    st.subheader(t("dlg_row_actions_title"))
    if st.button(t("dlg_close"), key=f"dlg_ast_pick_close_{aid}"):
        st.session_state.pop("dlg_asset_pick_id", None)
        _request_clear_fm_assets_grid()
        st.rerun()

    items = fetch_assets()
    ast = next((a for a in items if int(a["id"]) == aid), None)
    if ast is None:
        st.error(t("err_asset_not_found"))
        if st.button(t("dlg_close"), key=f"dlg_ast_pick_nf_{aid}"):
            st.session_state.pop("dlg_asset_pick_id", None)
            _request_clear_fm_assets_grid()
            st.rerun()
        return

    st.markdown(html.escape(_fmt_asset_brief(ast)))
    c0, c1 = st.columns(2)
    with c0:
        if st.button(t("btn_edit_asset"), key=f"dlg_ast_pick_edit_{aid}", use_container_width=True):
            st.session_state.pop("dlg_asset_pick_id", None)
            st.session_state["dlg_asset_edit_id"] = aid
            _request_clear_fm_assets_grid()
            st.rerun()
    with c1:
        if st.button(t("btn_delete_asset"), key=f"dlg_ast_pick_del_{aid}", use_container_width=True):
            st.session_state.pop("dlg_asset_pick_id", None)
            st.session_state["dlg_asset_delete_id"] = aid
            _request_clear_fm_assets_grid()
            st.rerun()


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_edit_asset)
def _dialog_edit_asset() -> None:
    aid = st.session_state.get("dlg_asset_edit_id")
    if aid is None:
        return
    aid = int(aid)

    if st.button(t("dlg_close"), key=f"dlg_east_close_{aid}"):
        st.session_state.pop("dlg_asset_edit_id", None)
        _request_clear_fm_assets_grid()
        st.rerun()

    items = fetch_assets()
    ast = next((a for a in items if int(a["id"]) == aid), None)
    if ast is None:
        st.error(t("err_asset_not_found"))
        if st.button(t("dlg_close"), key=f"dlg_east_nf_close_{aid}"):
            st.session_state.pop("dlg_asset_edit_id", None)
            _request_clear_fm_assets_grid()
            st.rerun()
        return

    if ast.get("has_open_position"):
        st.warning(t("cap_ast_has_position"))
        if st.button(t("dlg_close"), key=f"dlg_east_blk_close_{aid}"):
            st.session_state.pop("dlg_asset_edit_id", None)
            _request_clear_fm_assets_grid()
            st.rerun()
        return

    st.subheader(t("dlg_edit_asset"))
    cur_at = str(ast.get("asset_type") or "stock")
    if cur_at not in ("stock", "fund"):
        cur_at = "stock"
    cur_sym = str(ast.get("symbol") or "")
    cur_nm = str(ast.get("name") or "")
    cur_mkt = str(ast.get("market") or "")

    with st.form(f"dlg_edit_asset_form_{aid}"):
        right = _form_field_row(t("dlg_asset_type"))
        with right:
            at_i = ["stock", "fund"].index(cur_at) if cur_at in ("stock", "fund") else 0
            asset_type = st.selectbox(
                "dlg_east_at",
                ["stock", "fund"],
                index=at_i,
                label_visibility="collapsed",
                key=f"dlg_east_type_{aid}",
            )
        right = _form_field_row(t("dlg_symbol"))
        with right:
            symbol = st.text_input(
                "dlg_east_sym",
                value=cur_sym,
                label_visibility="collapsed",
                key=f"dlg_east_symbol_{aid}",
            )
        right = _form_field_row(t("dlg_name"))
        with right:
            name = st.text_input(
                "dlg_east_nm",
                value=cur_nm,
                label_visibility="collapsed",
                key=f"dlg_east_name_{aid}",
            )
        right = _form_field_row(t("dlg_market"))
        with right:
            market = st.text_input(
                "dlg_east_mkt",
                value=cur_mkt,
                label_visibility="collapsed",
                key=f"dlg_east_market_{aid}",
            )
        submit = st.form_submit_button(t("dlg_save"))

    if submit:
        ok, result = api_call(
            "PATCH",
            f"/assets/{aid}",
            payload={
                "asset_type": asset_type,
                "symbol": symbol.strip(),
                "name": name.strip(),
                "market": market.strip() or None,
            },
        )
        st.success(str(result)) if ok else st.error(result)
        if ok:
            st.session_state.pop("dlg_asset_edit_id", None)
            _request_clear_fm_assets_grid()
            st.rerun()


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_delete_asset)
def _dialog_delete_asset() -> None:
    aid = st.session_state.get("dlg_asset_delete_id")
    if aid is None:
        return
    aid = int(aid)

    if st.button(t("dlg_close"), key=f"dlg_dast_close_{aid}"):
        st.session_state.pop("dlg_asset_delete_id", None)
        _request_clear_fm_assets_grid()
        st.rerun()

    items = fetch_assets()
    ast = next((a for a in items if int(a["id"]) == aid), None)
    if ast is None:
        st.error(t("err_asset_not_found"))
        return

    st.subheader(t("dlg_delete_asset"))
    st.markdown(html.escape(_fmt_asset_brief(ast)))

    if ast.get("has_open_position"):
        st.warning(t("cap_ast_has_position"))
        return

    confirm = st.checkbox(t("dlg_delete_asset_confirm"), key=f"dlg_dast_confirm_{aid}")
    if st.button(t("dlg_delete_asset_submit"), key=f"dlg_dast_go_{aid}", disabled=not confirm):
        ok, result = api_call("DELETE", f"/assets/{aid}")
        if ok:
            st.success(t("msg_delete_ok"))
        else:
            st.error(_friendly_delete_error(result, kind="asset"))
        if ok:
            st.session_state.pop("dlg_asset_delete_id", None)
            _request_clear_fm_assets_grid()
            st.rerun()


def _tx_needs_asset(tx_type: str) -> bool:
    return tx_type in ("buy", "sell")


def _tx_needs_quantity_price(tx_type: str) -> bool:
    return tx_type in ("buy", "sell")


def _tx_shows_fee_field(tx_type: str) -> bool:
    """收入/分红等不走手续费输入，后端 fee 固定为 0；买入卖出支出可填。"""
    return tx_type in ("buy", "sell", "expense")


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_new_transaction)
def _dialog_new_transaction() -> None:
    st.subheader(t("dlg_new_tx"))
    accounts = fetch_accounts()
    assets = fetch_assets()
    account_options = {_account_pick_label(a): a["id"] for a in accounts}
    asset_options = {f"{a['id']} · {a['symbol']} {a['name']}": a["id"] for a in assets}

    if st.button(t("dlg_close"), key="dlg_tx_close"):
        st.session_state.pop("dlg_tx_open", None)
        st.rerun()

    _tx_types = ["income", "expense", "buy", "sell", "dividend"]
    right = _form_field_row(t("dlg_tx_type"))
    with right:
        tx_type = st.selectbox(
            "dlg_tx_t",
            _tx_types,
            format_func=tx_type_label,
            label_visibility="collapsed",
            key="dlg_tx_type",
        )

    qty_default = "" if not _tx_needs_quantity_price(tx_type) else "100"
    price_default = "" if not _tx_needs_quantity_price(tx_type) else "100.00"

    with st.form("dlg_create_tx_form"):
        right = _form_field_row(t("dlg_cash_account"))
        with right:
            if account_options:
                acc_label = st.selectbox(
                    "dlg_tx_acc",
                    list(account_options.keys()),
                    label_visibility="collapsed",
                    key="dlg_tx_account",
                )
                account_id = account_options[acc_label]
            else:
                st.warning(t("warn_create_account_first"))
                account_id = int(
                    st.number_input(
                        "dlg_tx_aid",
                        min_value=0,
                        step=1,
                        value=0,
                        label_visibility="collapsed",
                        key="dlg_tx_account_manual",
                    )
                )

        asset_id: int | None = None
        if _tx_needs_asset(tx_type):
            right = _form_field_row(t("dlg_asset_underlying"))
            with right:
                if asset_options:
                    ast_label = st.selectbox(
                        "dlg_tx_ast",
                        list(asset_options.keys()),
                        label_visibility="collapsed",
                        key="dlg_tx_asset",
                    )
                    asset_id = asset_options[ast_label]
                else:
                    st.warning(t("warn_create_asset_first"))
                    aid = st.number_input(
                        "dlg_tx_astid",
                        min_value=0,
                        step=1,
                        value=0,
                        label_visibility="collapsed",
                        key="dlg_tx_asset_manual",
                    )
                    asset_id = int(aid) if aid else None

        amount_input = ""
        if not _tx_needs_quantity_price(tx_type):
            right = _form_field_row(t("dlg_amount"))
            with right:
                amount_input = st.text_input(
                    "dlg_tx_amt",
                    value="1000.00",
                    label_visibility="collapsed",
                    key="dlg_tx_amount",
                )
        if _tx_needs_quantity_price(tx_type):
            right = _form_field_row(t("dlg_quantity"))
            with right:
                quantity_text = st.text_input(
                    "dlg_tx_qty",
                    value=qty_default,
                    label_visibility="collapsed",
                    key="dlg_tx_qty",
                )
            right = _form_field_row(t("dlg_price"))
            with right:
                price_text = st.text_input(
                    "dlg_tx_prc",
                    value=price_default,
                    label_visibility="collapsed",
                    key="dlg_tx_prc",
                )
        else:
            quantity_text = ""
            price_text = ""
        if _tx_shows_fee_field(tx_type):
            right = _form_field_row(t("dlg_fee"))
            with right:
                fee = st.text_input("dlg_tx_fee", value="0", label_visibility="collapsed", key="dlg_tx_fee")
        else:
            fee = "0"
        right = _form_field_row(t("dlg_note_short"))
        with right:
            note = st.text_input("dlg_tx_note", value="", label_visibility="collapsed", key="dlg_tx_note")
        right = _form_field_row(t("dlg_occurred_at"))
        with right:
            occurred_at = st.text_input(
                "dlg_tx_oc",
                value=format_ts_display(datetime.now().astimezone()),
                placeholder=t("ph_ts_example"),
                label_visibility="collapsed",
                key="dlg_tx_occurred",
            )
        submit = st.form_submit_button(t("dlg_submit"))
    if submit:
        if not accounts and account_id == 0:
            st.error(t("err_pick_account"))
        else:
            try:
                occurred_iso = iso_ts_for_api(occurred_at)
            except ValueError as exc:
                st.error(t("err_occurred_invalid", msg=str(exc)))
            else:
                from decimal import Decimal, InvalidOperation

                amount_for_api: str | None = None
                if _tx_needs_quantity_price(tx_type):
                    if not quantity_text.strip() or not price_text.strip():
                        st.error(t("err_trade_notional"))
                    else:
                        try:
                            q = Decimal(quantity_text.strip())
                            p = Decimal(price_text.strip())
                            if q <= 0 or p <= 0:
                                st.error(t("err_trade_notional"))
                            else:
                                amount_for_api = format((q * p).quantize(Decimal("0.01")), "f")
                        except (InvalidOperation, ValueError):
                            st.error(t("err_trade_notional"))
                else:
                    raw_amt = amount_input.strip()
                    if not raw_amt:
                        st.error(t("err_amount_required"))
                    else:
                        amount_for_api = raw_amt

                if amount_for_api:
                    payload: dict[str, object] = {
                        "type": tx_type,
                        "account_id": int(account_id) if account_id else None,
                        "amount": amount_for_api,
                        "fee": fee,
                        "note": note or None,
                        "occurred_at": occurred_iso,
                    }
                    if asset_id:
                        payload["asset_id"] = asset_id
                    if quantity_text.strip():
                        payload["quantity"] = quantity_text
                    if price_text.strip():
                        payload["price"] = price_text
                    ok, result = api_call("POST", "/transactions", payload=payload)
                    st.success(str(result)) if ok else st.error(result)
                    if ok:
                        st.session_state.pop("dlg_tx_open", None)
                        st.rerun()


def _fmt_account_brief(acc: dict | None) -> str:
    if not acc:
        return "—"
    owner = (acc.get("owner_name") or "").strip()
    own = f" ·{owner}" if owner else ""
    return f"{acc['id']} · {acc['name']}{own} ({acc.get('account_type', '')})"


def _fmt_asset_brief(asset: dict | None) -> str:
    if not asset:
        return "—"
    at = str(asset.get("asset_type") or "").strip()
    at_disp = asset_type_label(at) if at else ""
    tail = f" ({at_disp})" if at_disp and at_disp != "—" else ""
    return f"{asset['id']} · {asset.get('symbol', '')} {asset.get('name', '')}{tail}"


def _tx_list_account_cell(account_id: object, acc_by_id: dict[int, dict]) -> str:
    if account_id is None:
        return "—"
    try:
        i = int(account_id)
    except (TypeError, ValueError):
        return str(account_id)
    a = acc_by_id.get(i)
    if not a:
        return f"#{i}"
    owner = (a.get("owner_name") or "").strip()
    own = f" · {owner}" if owner else ""
    at = str(a.get("account_type") or "").strip()
    tail = f" ({account_type_label(at)})" if at else ""
    return f"{a.get('name', '')}{own}{tail}"


def _tx_list_asset_cell(asset_id: object, ast_by_id: dict[int, dict]) -> str:
    if asset_id is None:
        return "—"
    try:
        i = int(asset_id)
    except (TypeError, ValueError):
        return str(asset_id)
    a = ast_by_id.get(i)
    if not a:
        return f"#{i}"
    sym = (a.get("symbol") or "").strip()
    name = (a.get("name") or "").strip()
    if sym and name:
        return f"{sym} · {name}"
    if sym or name:
        return sym or name
    return f"#{i}"


def _tx_detail_occurred_readable(iso_val: str | None) -> str:
    if not iso_val:
        return "—"
    try:
        raw = str(iso_val).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        return format_ts_display(dt)
    except ValueError:
        return str(iso_val)


def _tx_detail_notional_label(qty: object, price: object) -> str:
    from decimal import Decimal, InvalidOperation

    if qty is None or price is None:
        return "—"
    try:
        n = Decimal(str(qty)) * Decimal(str(price))
        return format(n, ".2f")
    except (InvalidOperation, ValueError):
        return "—"


@st.dialog(" ", width="large", on_dismiss=_dismiss_dialog_transaction_detail)
def _dialog_transaction_detail() -> None:
    tid = st.session_state.get("dlg_tx_detail_id")
    if not tid:
        return
    st.subheader(t("tx_detail_title"))
    ok, body = api_call("GET", f"/transactions/{int(tid)}", require_auth=True)
    data: dict | None = None
    if not ok or not isinstance(body, dict):
        st.error(str(body) if not ok else t("tx_detail_err"))
    else:
        raw = body.get("data")
        data = raw if isinstance(raw, dict) else None
        if data is None:
            st.error(t("tx_detail_err"))

    if data:
        tx_ty = str(data.get("type", ""))
        st.markdown(
            f"- **{t('tx_detail_id')}**：`{int(data['id'])}`\n"
            f"- **{t('tx_detail_type')}**：{tx_type_label(tx_ty)}\n"
            f"- **{t('dlg_occurred_at')}**：{_tx_detail_occurred_readable(str(data.get('occurred_at')) if data.get('occurred_at') is not None else None)}"
        )
        tr = data.get("transfer")
        if isinstance(tr, dict) and (tr.get("from_account") or tr.get("to_account")):
            st.markdown(f"### {t('tx_detail_transfer_section')}")
            fa = tr.get("from_account") if isinstance(tr.get("from_account"), dict) else None
            ta = tr.get("to_account") if isinstance(tr.get("to_account"), dict) else None
            st.markdown(
                f"- **{t('tx_detail_from')}**：{html.escape(_fmt_account_brief(fa))}\n"
                f"- **{t('tx_detail_to')}**：{html.escape(_fmt_account_brief(ta))}\n"
                f"- **{t('tx_detail_transfer_amount')}**：{html.escape(str(tr.get('amount', data.get('amount'))))}"
            )
        elif tx_ty in ("buy", "sell"):
            acct = data.get("account") if isinstance(data.get("account"), dict) else None
            st.markdown(f"- **{t('tx_detail_account')}**：{html.escape(_fmt_account_brief(acct))}")
            ast = data.get("asset") if isinstance(data.get("asset"), dict) else None
            st.markdown(f"- **{t('tx_detail_asset')}**：{html.escape(_fmt_asset_brief(ast))}")
            st.markdown(
                f"- **{t('dlg_amount')}**：{html.escape(str(data.get('amount')))}\n"
                f"- **{t('dlg_quantity')}**：{html.escape(str(data.get('quantity')) if data.get('quantity') is not None else '—')}\n"
                f"- **{t('dlg_price')}**：{html.escape(str(data.get('price')) if data.get('price') is not None else '—')}\n"
                f"- **{t('tx_detail_notional')}**：{html.escape(_tx_detail_notional_label(data.get('quantity'), data.get('price')))}\n"
                f"- **{t('dlg_fee')}**：{html.escape(str(data.get('fee')))}"
            )
            if tx_ty == "sell" and data.get("realized_pnl") is not None:
                st.markdown(f"- **{t('tx_detail_realized_pnl')}**：{html.escape(str(data.get('realized_pnl')))}")
        else:
            acct = data.get("account") if isinstance(data.get("account"), dict) else None
            st.markdown(f"- **{t('tx_detail_account')}**：{html.escape(_fmt_account_brief(acct))}")
            st.markdown(
                f"- **{t('dlg_amount')}**：{html.escape(str(data.get('amount')))}\n"
                f"- **{t('dlg_fee')}**：{html.escape(str(data.get('fee')))}"
            )

        note = data.get("note")
        if note:
            st.markdown(f"- **{t('dlg_note_short')}**：{html.escape(str(note))}")
        cat = data.get("category")
        if cat:
            st.markdown(f"- **{t('tx_detail_category')}**：{html.escape(str(cat))}")

    if st.button(t("tx_detail_close"), key="dlg_tx_detail_close"):
        for k in SESSION_TX_DETAIL_KEYS:
            st.session_state.pop(k, None)
        _clear_fm_tx_list_df_selection()
        st.rerun()


def render_overview_panel() -> None:
    _tcol, _sp = st.columns([0.72, 0.28], gap="small", vertical_alignment="center")
    with _tcol:
        st.markdown(
            f'<p style="margin:0;padding:0"><span class="fm-toolbar-page-title">{html.escape(t("overview_title"))}</span></p>',
            unsafe_allow_html=True,
        )
    with _sp:
        st.empty()

    data, fetch_err = fetch_wealth_overview()
    if fetch_err or data is None:
        st.error(f"{t('overview_err')}{fetch_err}" if fetch_err else t("overview_err"))
        st.caption(t("overview_err_hint"))
        return
    if data.get("note"):
        st.caption(str(data["note"]))
    m1, m2, m3 = st.columns(3)
    m1.metric(t("metric_cash_total"), data.get("cash_total", "-"))
    m2.metric(t("metric_position_cost"), data.get("position_book_value_total", "-"))
    m3.metric(t("metric_grand_book"), data.get("grand_book_total", "-"))

    st.subheader(t("sub_accounts"))
    acc = data.get("accounts") or []
    if acc:
        st.dataframe(prepare_grid_rows(acc), use_container_width=True, hide_index=True)
    else:
        st.info(t("info_no_accounts"))

    st.subheader(t("sub_positions"))
    pos = data.get("positions") or []
    if pos:
        st.dataframe(prepare_grid_rows(pos), use_container_width=True, hide_index=True)
    else:
        st.info(t("info_no_positions"))

    st.caption(t("cap_overview_hint"))


def _render_pnl_overview_body(data: dict) -> None:
    """收益总览核心内容：累计已实现盈亏、按标的持仓、卖出流水表。"""
    st.metric(t("metric_realized_total"), data.get("position_realized_pnl_total", "-"))

    st.subheader(t("sub_by_symbol"))
    positions = data.get("positions") or []
    if positions:
        st.dataframe(prepare_grid_rows(positions), use_container_width=True, hide_index=True)
    else:
        st.info(t("info_no_pos_data"))

    st.subheader(t("sub_sell_ledger"))
    sells = data.get("sell_ledger") or []
    if sells:
        st.dataframe(prepare_grid_rows(sells), use_container_width=True, hide_index=True)
    else:
        st.info(t("info_no_sells"))

    st.caption(t("cap_pnl_hint"))


def render_pnl_overview_panel() -> None:
    _tcol, _sp = st.columns([0.72, 0.28], gap="small", vertical_alignment="center")
    with _tcol:
        st.markdown(
            f'<p style="margin:0;padding:0"><span class="fm-toolbar-page-title">{html.escape(t("pnl_title"))}</span></p>',
            unsafe_allow_html=True,
        )
    with _sp:
        st.empty()

    data, fetch_err = fetch_pnl_overview()
    if fetch_err or data is None:
        st.error(f"{t('pnl_err')}{fetch_err}" if fetch_err else t("pnl_err"))
        return

    _render_pnl_overview_body(data)


def render_accounts_panel() -> None:
    if st.session_state.pop(_PENDING_CLEAR_FM_ACCOUNTS_GRID, False):
        _clear_fm_grid_selection(_FM_ACCOUNTS_GRID_KEY)
    if "bank_catalog" not in st.session_state:
        sync_bank_catalog_to_session()
    elif not st.session_state.get("bank_catalog") and not st.session_state.get(
        "_bank_catalog_load_attempted"
    ):
        sync_bank_catalog_to_session()

    # 单行三列，避免「标题一列 + 右侧再嵌套列」导致整行高度被撑高、标题与按钮上下错位
    _tcol, _bcol, _pcol = st.columns([0.38, 0.24, 0.38], gap="small", vertical_alignment="center")
    with _tcol:
        st.markdown(
            f'<p style="margin:0;padding:0"><span class="fm-toolbar-page-title">{html.escape(t("accounts_title"))}</span></p>',
            unsafe_allow_html=True,
        )
    with _bcol:
        if st.button(t("btn_new_account"), key="fm_btn_open_account"):
            for _k in ("dlg_account_pick_id", "dlg_account_edit_id", "dlg_account_delete_id"):
                st.session_state.pop(_k, None)
            st.session_state["dlg_account_open"] = True
            _request_clear_fm_accounts_grid()
    with _pcol:
        if hasattr(st, "popover"):
            with st.popover(t("popover_book_help")):
                st.markdown(t("help_markdown"))
        else:
            with st.expander(t("expander_book_help"), expanded=False):
                st.markdown(t("help_markdown"))

    if st.session_state.get("dlg_account_delete_id") is not None:
        _dialog_delete_account()
    elif st.session_state.get("dlg_account_edit_id") is not None:
        _dialog_edit_account()
    elif st.session_state.get("dlg_account_pick_id") is not None:
        _dialog_account_pick_actions()
    elif st.session_state.get("dlg_account_open"):
        _dialog_new_account()

    ok, result = api_call("GET", "/accounts")
    if ok and isinstance(result, dict):
        items = result.get("data", {}).get("items", [])
        st.subheader(t("sub_account_list"))
        if items:
            _consume_accounts_grid_row_pick(items)
            acc_df = pd.DataFrame(prepare_grid_rows(items))
            st.dataframe(
                acc_df,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=_FM_ACCOUNTS_GRID_KEY,
            )
        else:
            st.info(t("info_no_accounts_list"))
    else:
        st.error(result)


def render_assets_panel() -> None:
    if st.session_state.pop(_PENDING_CLEAR_FM_ASSETS_GRID, False):
        _clear_fm_grid_selection(_FM_ASSETS_GRID_KEY)
    _title_col, _btn_col = st.columns([0.68, 0.32], gap="small", vertical_alignment="center")
    with _title_col:
        st.markdown(
            f'<p style="margin:0;padding:0"><span class="fm-toolbar-page-title">{html.escape(t("assets_title"))}</span></p>',
            unsafe_allow_html=True,
        )
    with _btn_col:
        if st.button(t("btn_new_asset"), key="fm_btn_open_asset"):
            for _k in ("dlg_asset_pick_id", "dlg_asset_edit_id", "dlg_asset_delete_id"):
                st.session_state.pop(_k, None)
            st.session_state.pop("_dlg_ast_post_lookup", None)
            for _k in ("dlg_ast_symbol", "dlg_ast_name", "dlg_ast_market"):
                st.session_state.pop(_k, None)
            st.session_state["dlg_asset_open"] = True
            _request_clear_fm_assets_grid()

    if st.session_state.get("dlg_asset_delete_id") is not None:
        _dialog_delete_asset()
    elif st.session_state.get("dlg_asset_edit_id") is not None:
        _dialog_edit_asset()
    elif st.session_state.get("dlg_asset_pick_id") is not None:
        _dialog_asset_pick_actions()
    elif st.session_state.get("dlg_asset_open"):
        _dialog_new_asset()

    ok, result = api_call("GET", "/assets")
    if ok and isinstance(result, dict):
        items = result.get("data", {}).get("items", [])
        st.subheader(t("sub_asset_list"))
        if items:
            _consume_assets_grid_row_pick(items)
            ast_df = pd.DataFrame(
                prepare_grid_rows(items, drop_keys=frozenset({"has_open_position"})),
            )
            st.dataframe(
                ast_df,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=_FM_ASSETS_GRID_KEY,
            )
        else:
            st.info(t("info_no_assets"))
    else:
        st.error(result)


def _transactions_rows_for_display(
    items: list[dict],
    page: int,
    page_size: int,
    *,
    accounts: list[dict],
    assets: list[dict],
) -> list[dict]:
    """列表展示：不展示流水数据库 id；首列 seq；账户/标的显示名称而非 ID。"""
    acc_by_id = {int(a["id"]): a for a in accounts if a.get("id") is not None}
    ast_by_id = {int(a["id"]): a for a in assets if a.get("id") is not None}
    base = (page - 1) * page_size
    out: list[dict] = []
    for i, row in enumerate(items):
        d: dict[str, object] = {
            "seq": base + i + 1,
            "account": _tx_list_account_cell(row.get("account_id"), acc_by_id),
            "asset": _tx_list_asset_cell(row.get("asset_id"), ast_by_id),
        }
        for k, v in row.items():
            if k == "id" or k in ("account_id", "asset_id"):
                continue
            if k == "type" and v is not None:
                d[k] = tx_type_label(str(v))
            else:
                d[k] = v
        out.append(d)
    return out


def _consume_tx_detail_query_param() -> bool:
    """从 URL 读取 ?tx_detail= 并写入 dlg_tx_detail_id，然后去掉 query，避免重复弹窗。成功解析并写入时返回 True。"""
    raw = st.query_params.get("tx_detail")
    if raw is None:
        return False
    applied = False
    try:
        tok = raw[0] if isinstance(raw, list) else raw
        st.session_state["dlg_tx_detail_id"] = int(str(tok))
        applied = True
    except (ValueError, TypeError, IndexError):
        pass
    if "tx_detail" in st.query_params:
        try:
            del st.query_params["tx_detail"]
        except Exception:
            pass
    return applied


def _fm_tx_list_df_state_key() -> str:
    pg = max(1, int(st.session_state.get("tx_list_page", 1) or 1))
    return f"fm_tx_list_df_p{pg}"


def _clear_fm_tx_list_df_selection() -> None:
    st.session_state[_fm_tx_list_df_state_key()] = {
        "selection": {"rows": [], "columns": [], "cells": []},
    }


def _consume_accounts_grid_row_pick(items: list[dict]) -> None:
    """在 ``st.dataframe`` 之前消费行选：打开操作弹窗并清空表格 widget 状态（创建 widget 后不能再写同一 key）。"""
    if (
        st.session_state.get("dlg_account_pick_id") is not None
        or st.session_state.get("dlg_account_edit_id") is not None
        or st.session_state.get("dlg_account_delete_id") is not None
    ):
        return
    raw = st.session_state.get(_FM_ACCOUNTS_GRID_KEY)
    if not raw:
        return
    try:
        rows = raw["selection"]["rows"]
    except (KeyError, TypeError, AttributeError):
        return
    if not rows:
        return
    ri = int(rows[0])
    if ri < 0 or ri >= len(items):
        return
    st.session_state.pop("dlg_account_open", None)
    st.session_state["dlg_account_pick_id"] = int(items[ri]["id"])
    _clear_fm_grid_selection(_FM_ACCOUNTS_GRID_KEY)
    st.rerun()


def _consume_assets_grid_row_pick(items: list[dict]) -> None:
    """在 ``st.dataframe`` 之前消费行选：打开操作弹窗并清空表格 widget 状态。"""
    if (
        st.session_state.get("dlg_asset_pick_id") is not None
        or st.session_state.get("dlg_asset_edit_id") is not None
        or st.session_state.get("dlg_asset_delete_id") is not None
    ):
        return
    raw = st.session_state.get(_FM_ASSETS_GRID_KEY)
    if not raw:
        return
    try:
        rows = raw["selection"]["rows"]
    except (KeyError, TypeError, AttributeError):
        return
    if not rows:
        return
    ri = int(rows[0])
    if ri < 0 or ri >= len(items):
        return
    st.session_state.pop("dlg_asset_open", None)
    st.session_state["dlg_asset_pick_id"] = int(items[ri]["id"])
    _clear_fm_grid_selection(_FM_ASSETS_GRID_KEY)
    st.rerun()


def _apply_tx_list_row_selection_to_detail(items: list[dict], *, skip_if_query_opened: bool) -> None:
    """将 ``st.dataframe`` 的单行选择映射为流水详情弹窗 id（不经过浏览器跳转）。"""
    if skip_if_query_opened:
        return
    key = _fm_tx_list_df_state_key()
    raw = st.session_state.get(key)
    if not raw:
        return
    try:
        rows = raw["selection"]["rows"]
    except (KeyError, TypeError, AttributeError):
        return
    if not rows:
        return
    ri = int(rows[0])
    if ri < 0 or ri >= len(items):
        return
    tid = int(items[ri]["id"])
    if st.session_state.get("dlg_tx_detail_id") == tid:
        return
    st.session_state["dlg_tx_detail_id"] = tid


def render_transactions_panel() -> None:
    _title_col, _btn_col = st.columns([0.68, 0.32], gap="small", vertical_alignment="center")
    with _title_col:
        st.markdown(
            f'<p style="margin:0;padding:0"><span class="fm-toolbar-page-title">{html.escape(t("tx_title"))}</span></p>',
            unsafe_allow_html=True,
        )
    with _btn_col:
        if st.button(t("btn_new_tx"), key="fm_btn_open_tx"):
            st.session_state["dlg_tx_open"] = True

    if st.session_state.get("dlg_tx_open"):
        _dialog_new_transaction()

    page_size = TX_LIST_PAGE_SIZE
    page_req = max(1, int(st.session_state.get("tx_list_page", 1) or 1))
    ok, result = api_call("GET", "/transactions", params={"page": page_req, "page_size": page_size})
    if ok and isinstance(result, dict):
        data = result.get("data", {}) or {}
        items = data.get("items", []) or []
        pagination = data.get("pagination") or {}
        total = int(pagination.get("total") or 0)
        total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
        if page_req > total_pages:
            st.session_state["tx_list_page"] = total_pages
            st.rerun()
        page = page_req
        st.subheader(t("sub_recent_tx"))
        if total == 0:
            st.info(t("info_no_recent_tx"))
        else:
            opened_from_url = _consume_tx_detail_query_param()
            p1, p2, p3 = st.columns([1, 2, 1])
            with p1:
                if st.button(t("tx_page_prev"), disabled=page <= 1, key="tx_list_prev"):
                    st.session_state["tx_list_page"] = page - 1
                    st.rerun()
            with p2:
                st.caption(t("tx_page_status", page=page, total_pages=total_pages, total=total))
            with p3:
                if st.button(t("tx_page_next"), disabled=page >= total_pages, key="tx_list_next"):
                    st.session_state["tx_list_page"] = page + 1
                    st.rerun()

            accounts = fetch_accounts()
            assets = fetch_assets()
            display_rows = _transactions_rows_for_display(
                items, page, page_size, accounts=accounts, assets=assets
            )
            df = pd.DataFrame(
                prepare_grid_rows(
                    display_rows,
                    drop_keys=frozenset({"category"}),
                )
            )
            st.caption(t("tx_row_select_detail_hint"))
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=_fm_tx_list_df_state_key(),
            )
            _apply_tx_list_row_selection_to_detail(
                items, skip_if_query_opened=opened_from_url
            )
            if st.session_state.get("dlg_tx_detail_id"):
                _dialog_transaction_detail()
    else:
        st.error(result)


def render_transfers_panel() -> None:
    st.header(t("transfer_title"))
    st.markdown(t("transfer_desc"))

    accounts = fetch_accounts()
    account_options = {_account_transfer_label(a): a["id"] for a in accounts}

    with st.form("transfer_form"):
        if len(account_options) >= 2:
            from_choices = [TRANSFER_PLACEHOLDER] + list(account_options.keys())
            from_label = st.selectbox(
                t("tf_from"),
                from_choices,
                index=0,
                format_func=lambda x: t("tf_pick_from") if x == TRANSFER_PLACEHOLDER else x,
                key="tf_from",
            )
            from_id = 0 if from_label == TRANSFER_PLACEHOLDER else int(account_options[from_label])

            if from_id:
                to_choices = [TRANSFER_PLACEHOLDER] + [k for k in account_options if account_options[k] != from_id]
            else:
                to_choices = [TRANSFER_PLACEHOLDER] + list(account_options.keys())
            to_label = st.selectbox(
                t("tf_to"),
                to_choices,
                index=0,
                format_func=lambda x: t("tf_pick_to") if x == TRANSFER_PLACEHOLDER else x,
                key="tf_to",
            )
            to_id = (
                0
                if to_label == TRANSFER_PLACEHOLDER or to_label not in account_options
                else int(account_options[to_label])
            )
        elif account_options:
            st.warning(t("warn_two_accounts"))
            from_id = to_id = 0
        else:
            st.warning(t("warn_two_accounts_create"))
            from_id = st.number_input(t("tf_from_id"), min_value=0, step=1)
            to_id = st.number_input(t("tf_to_id"), min_value=0, step=1)

        amount = st.text_input(t("tf_amount"), value="", placeholder=t("ph_amount_example"))
        note = st.text_input(t("tf_note"), value="")
        occurred_at = st.text_input(
            t("tf_time"),
            value=format_ts_display(datetime.now().astimezone()),
            placeholder=t("ph_ts_example"),
        )
        submit = st.form_submit_button(t("tf_submit"))
    if submit:
        if from_id and to_id and from_id == to_id:
            st.error(t("err_same_account"))
        elif not from_id or not to_id:
            st.error(t("err_pick_both"))
        elif not str(amount).strip():
            st.error(t("err_amount_required"))
        else:
            try:
                occurred_iso = iso_ts_for_api(occurred_at)
            except ValueError as exc:
                st.error(t("err_transfer_time", msg=str(exc)))
            else:
                ok, result = api_call(
                    "POST",
                    "/transfers",
                    payload={
                        "from_account_id": int(from_id),
                        "to_account_id": int(to_id),
                        "amount": amount.strip(),
                        "note": note or None,
                        "occurred_at": occurred_iso,
                    },
                )
                st.success(str(result)) if ok else st.error(result)
                if ok:
                    st.rerun()


def render_positions_panel() -> None:
    st.header(t("positions_title"))
    ok, result = api_call("GET", "/positions")
    if ok and isinstance(result, dict):
        items = result.get("data", {}).get("items", [])
        if items:
            st.dataframe(prepare_grid_rows(items), use_container_width=True, hide_index=True)
        else:
            st.info(t("info_no_positions_simple"))
    else:
        st.error(result)


def render_reports_panel() -> None:
    now = datetime.now().astimezone()
    cy, cm = now.year, now.month

    _title_col, c_y, c_m = st.columns([2.6, 1, 1], gap="small", vertical_alignment="center")
    with _title_col:
        st.markdown(
            f'<p style="margin:0;padding:0"><span class="fm-toolbar-page-title">{html.escape(t("reports_title"))}</span></p>',
            unsafe_allow_html=True,
        )
    with c_y:
        year = int(
            st.number_input(
                t("reports_year"),
                min_value=2000,
                max_value=2100,
                value=cy,
                step=1,
                key="reports_filter_year",
            )
        )
    with c_m:
        months = list(range(1, 13))

        def _month_label(mv: int) -> str:
            if st.session_state.get("ui_lang", "zh") == "en":
                return calendar.month_name[mv]
            return f"{mv}月"

        month = int(
            st.selectbox(
                t("reports_month"),
                months,
                index=cm - 1,
                format_func=_month_label,
                key="reports_filter_month",
            )
        )

    y_start, y_end = _reports_year_bounds_iso(year)
    ann, ann_err = fetch_cashflow_summary_iso(y_start, y_end)
    st.subheader(t("reports_annual_sub", year=year))
    if ann_err:
        st.error(ann_err)
    elif ann:
        _reports_cashflow_metrics_row(ann)

    st.divider()

    m_start, m_end = _reports_month_bounds_iso(year, month)
    m02 = f"{month:02d}"
    mont, mont_err = fetch_cashflow_summary_iso(m_start, m_end)
    st.subheader(t("reports_month_tx_sub", year=year, month=month, m02=m02))
    if mont_err:
        st.error(mont_err)
    elif mont:
        _reports_cashflow_metrics_row(mont)

    accounts = fetch_accounts()
    assets = fetch_assets()
    mon_tx, mon_tx_err = fetch_transactions_all_between(m_start, m_end)
    if mon_tx_err:
        st.error(mon_tx_err)
    elif not mon_tx:
        st.info(t("info_no_reports_detail"))
    else:
        det_m = _reports_period_detail_rows(mon_tx, assets)
        if not det_m:
            st.info(t("info_no_reports_detail"))
        else:
            dr_m = _transactions_rows_for_display(
                det_m,
                1,
                max(1, len(det_m)),
                accounts=accounts,
                assets=assets,
            )
            st.dataframe(
                pd.DataFrame(prepare_grid_rows(dr_m, drop_keys=frozenset({"category"}))),
                use_container_width=True,
                hide_index=True,
            )


def render_main_workspace(page: str) -> None:
    inject_app_css()
    render_language_switcher()
    if page == "overview":
        render_overview_panel()
    elif page == "accounts":
        render_accounts_panel()
    elif page == "assets":
        render_assets_panel()
    elif page == "transactions":
        render_transactions_panel()
    elif page == "transfers":
        render_transfers_panel()
    elif page == "positions":
        render_positions_panel()
    elif page == "pnl":
        render_pnl_overview_panel()
    elif page == "reports":
        render_reports_panel()


def main() -> None:
    st.set_page_config(
        page_title="理财管理 · Financial Manager",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "Get Help": None,
            "Report a bug": None,
            "About": None,
        },
    )
    if "ui_lang" not in st.session_state:
        st.session_state["ui_lang"] = "zh"
    load_dotenv_if_present()
    st.session_state["api_base"] = normalize_api_base(read_fm_api_base_raw())

    _restore_auth_cookie_if_needed()

    if not st.session_state.get("token"):
        render_login_screen()
        return

    st.session_state.setdefault("nav_page", "overview")

    page = render_sidebar_nav()
    render_main_workspace(page)


if __name__ == "__main__":
    main()
