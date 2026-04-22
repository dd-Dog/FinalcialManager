from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st


QUOTE_CACHE_PATH = Path("output/quote_cache.csv")


def configure_matplotlib_for_chinese() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def load_quote_cache() -> pd.DataFrame:
    if not QUOTE_CACHE_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(QUOTE_CACHE_PATH, dtype={"code": str})
    if "date" not in df.columns or "return_rate" not in df.columns:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["return_rate"] = pd.to_numeric(df["return_rate"], errors="coerce")
    df = df.dropna(subset=["date", "return_rate"])
    if "stock_name" not in df.columns:
        df["stock_name"] = None
    if "recommender" not in df.columns:
        df["recommender"] = "未知推荐人"
    return df


def plot_daily_bar(daily_df: pd.DataFrame, selected_date: pd.Timestamp) -> None:
    if daily_df.empty:
        st.info("该日期没有可用的涨跌幅数据。")
        return

    daily_df = daily_df.sort_values("return_rate", ascending=False).copy()
    daily_df["label"] = daily_df["code"] + " " + daily_df["stock_name"].fillna("")
    # A-share convention: up=red, down=green
    colors = ["#d62728" if x >= 0 else "#2ca02c" for x in daily_df["return_rate"]]

    fig, ax = plt.subplots(figsize=(10, 4.8))
    bars = ax.bar(daily_df["label"], daily_df["return_rate"], color=colors)
    ax.set_title(f"{selected_date.strftime('%Y-%m-%d')} 推荐股票涨跌幅")
    ax.set_ylabel("涨跌幅")
    ax.set_xlabel("股票")
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.1%}")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.tick_params(axis="x", rotation=30)
    y_min = float(daily_df["return_rate"].min())
    y_max = float(daily_df["return_rate"].max())
    y_span = max(y_max - y_min, 0.01)
    y_pad = max(y_span * 0.18, 0.006)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    for bar, value in zip(bars, daily_df["return_rate"]):
        va = "bottom" if value >= 0 else "top"
        offset = y_pad * 0.22 if value >= 0 else -y_pad * 0.22
        ax.text(bar.get_x() + bar.get_width() / 2, value + offset, f"{value:.2%}", ha="center", va=va)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    st.pyplot(fig)


def show_period_summary(filtered_df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp) -> None:
    if filtered_df.empty:
        st.info("该区间没有可用的涨跌幅数据。")
        return

    daily_avg_df = (
        filtered_df.groupby("date", as_index=False)
        .agg(avg_return_rate=("return_rate", "mean"), stock_count=("code", "count"))
        .sort_values("date")
    )

    overall_avg = filtered_df["return_rate"].mean()
    st.metric("区间平均涨跌幅", f"{overall_avg:.2%}")
    st.caption(
        f"统计区间：{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}，"
        f"共 {len(daily_avg_df)} 个交易日，{len(filtered_df)} 条推荐记录。"
    )

    fig, ax = plt.subplots(figsize=(10, 4.8))
    bar_colors = ["#d62728" if x >= 0 else "#2ca02c" for x in daily_avg_df["avg_return_rate"]]
    bars = ax.bar(daily_avg_df["date"].dt.strftime("%Y-%m-%d"), daily_avg_df["avg_return_rate"], color=bar_colors)
    ax.set_title("区间内每日平均涨跌幅")
    ax.set_xlabel("日期")
    ax.set_ylabel("平均涨跌幅")
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.1%}")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.tick_params(axis="x", rotation=30)
    y_min = float(daily_avg_df["avg_return_rate"].min())
    y_max = float(daily_avg_df["avg_return_rate"].max())
    y_span = max(y_max - y_min, 0.01)
    y_pad = max(y_span * 0.18, 0.006)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)
    for bar, value in zip(bars, daily_avg_df["avg_return_rate"]):
        va = "bottom" if value >= 0 else "top"
        offset = y_pad * 0.22 if value >= 0 else -y_pad * 0.22
        ax.text(bar.get_x() + bar.get_width() / 2, value + offset, f"{value:.2%}", ha="center", va=va)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    st.pyplot(fig)

    show_df = daily_avg_df.copy()
    show_df["date"] = show_df["date"].dt.strftime("%Y-%m-%d")
    show_df["avg_return_rate"] = show_df["avg_return_rate"].map(lambda x: f"{x:.2%}")
    with st.expander("查看区间明细表", expanded=False):
        st.dataframe(show_df, use_container_width=True, height=220)


def main() -> None:
    st.set_page_config(page_title="FinancialManager 看板", layout="wide")
    configure_matplotlib_for_chinese()
    st.markdown(
        """
        <style>
            .block-container {padding-top: 1rem; padding-bottom: 1rem;}
            h1, h2, h3 {margin-top: 0.2rem; margin-bottom: 0.4rem;}
            div[data-testid="stHorizontalBlock"] {gap: 0.8rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("FinancialManager 数据看板")
    st.caption("数据来源：output/quote_cache.csv")

    df = load_quote_cache()
    if df.empty:
        st.warning("未找到可用数据。请先运行 financial_manager.py 生成 output/quote_cache.csv。")
        return

    recommenders = sorted(df["recommender"].fillna("未知推荐人").unique().tolist())

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1.2, 1.2, 1.2])
    with ctrl_col1:
        selected_recommender = st.selectbox("推荐人", options=recommenders, index=0)
    view_df = df[df["recommender"].fillna("未知推荐人") == selected_recommender].copy()

    available_dates = sorted(view_df["date"].dropna().unique())
    if not available_dates:
        st.warning("当前推荐人没有可用日期数据。")
        return

    with ctrl_col2:
        selected_date = st.selectbox(
            "查看日期",
            options=available_dates,
            index=len(available_dates) - 1,
            format_func=lambda d: pd.Timestamp(d).strftime("%Y-%m-%d"),
        )
    selected_date = pd.Timestamp(selected_date)

    with ctrl_col3:
        period_mode = st.selectbox("统计区间", options=["最近7天", "最近30天", "自定义"])
    max_date = pd.Timestamp(max(available_dates))

    if period_mode == "最近7天":
        start_date = max_date - pd.Timedelta(days=6)
        end_date = max_date
    elif period_mode == "最近30天":
        start_date = max_date - pd.Timedelta(days=29)
        end_date = max_date
    else:
        default_start = max_date - pd.Timedelta(days=6)
        start_date, end_date = st.date_input(
            "自定义日期范围",
            value=(default_start.date(), max_date.date()),
            min_value=min(available_dates).date(),
            max_value=max_date.date(),
        )
        start_date = pd.Timestamp(start_date)
        end_date = pd.Timestamp(end_date)

    left_col, right_col = st.columns(2)

    with left_col:
        st.subheader("1) 每日推荐股票涨跌幅")
        daily_df = view_df[view_df["date"] == selected_date].copy()
        plot_daily_bar(daily_df, selected_date)

    period_df = view_df[(view_df["date"] >= start_date) & (view_df["date"] <= end_date)].copy()
    with right_col:
        st.subheader("2) 一段时间内平均涨跌幅")
        show_period_summary(period_df, start_date, end_date)


if __name__ == "__main__":
    main()
