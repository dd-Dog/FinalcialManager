from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import akshare as ak
import matplotlib.pyplot as plt
import pandas as pd


LOTS_PER_STOCK = 100
PROXY_ENV_KEYS = [
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "all_proxy",
]


@dataclass
class QuoteResult:
    code: str
    date: str
    open_price: Optional[float]
    close_price: Optional[float]
    stock_name: Optional[str]
    error: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze short-term stock picks based on daily open/close prices."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input CSV path. Required columns: date, code",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to save analysis files.",
    )
    return parser.parse_args()


def normalize_code(code: str) -> str:
    cleaned = str(code).strip().lower().replace("sh", "").replace("sz", "")
    return cleaned.zfill(6)


def infer_recommender(input_path: Path) -> str:
    name = input_path.stem.strip()
    return name or "未知推荐人"


def _to_tx_symbol(code: str) -> str:
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def _call_without_proxy(func, *args, **kwargs):
    backup = {k: os.environ.get(k) for k in PROXY_ENV_KEYS}
    try:
        for key in PROXY_ENV_KEYS:
            if key in os.environ:
                del os.environ[key]
        return func(*args, **kwargs)
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def fetch_daily_quote(code: str, date: str) -> QuoteResult:
    try:
        dt = pd.to_datetime(date)
    except ValueError:
        return QuoteResult(
            code=code,
            date=date,
            open_price=None,
            close_price=None,
            stock_name=None,
            error="invalid date format",
        )

    query_date = dt.strftime("%Y%m%d")
    normalized_date = dt.strftime("%Y-%m-%d")

    df = pd.DataFrame()
    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=query_date,
            end_date=query_date,
            adjust="",
        )
    except Exception as exc:  # pragma: no cover - network data source
        # Common local issue: bad proxy variables break requests in data vendors.
        try:
            df = _call_without_proxy(
                ak.stock_zh_a_hist,
                symbol=code,
                period="daily",
                start_date=query_date,
                end_date=query_date,
                adjust="",
            )
        except Exception as retry_exc:
            last_error = str(retry_exc)
        else:
            last_error = None
    else:
        last_error = None

    if not df.empty:
        row = df.iloc[0]
        return QuoteResult(
            code=code,
            date=normalized_date,
            open_price=float(row["开盘"]),
            close_price=float(row["收盘"]),
            stock_name=str(row.get("股票名称", "")) or None,
            error=None,
        )

    # Fallback to Tencent data source when Eastmoney is unavailable.
    try:
        tx_df = ak.stock_zh_a_hist_tx(
            symbol=_to_tx_symbol(code),
            start_date=query_date,
            end_date=query_date,
            adjust="",
        )
        if not tx_df.empty:
            tx_row = tx_df.iloc[0]
            return QuoteResult(
                code=code,
                date=normalized_date,
                open_price=float(tx_row["open"]),
                close_price=float(tx_row["close"]),
                stock_name=None,
                error=None,
            )
    except Exception as tx_exc:  # pragma: no cover - network data source
        if last_error:
            last_error = f"{last_error}; fallback tx failed: {tx_exc}"
        else:
            last_error = f"fallback tx failed: {tx_exc}"

    if last_error:
        msg = f"quote fetch failed: {last_error}"
    else:
        msg = "no trading data on this date (market may not be closed or it is a non-trading day)"

    return QuoteResult(
        code=code,
        date=normalized_date,
        open_price=None,
        close_price=None,
        stock_name=None,
        error=msg,
    )


def load_input(path: str, output_dir: Path, load_all_cache: bool = True) -> pd.DataFrame:
    input_path = Path(path)
    recommender = infer_recommender(input_path)
    if input_path.suffix.lower() == ".csv":
        input_df = pd.read_csv(path, dtype={"code": str})
        required_columns = {"date", "code"}
        missing = required_columns - set(input_df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")
        if "company_name" not in input_df.columns:
            input_df["company_name"] = None
        if "theme" not in input_df.columns:
            input_df["theme"] = None
        if "recommender" not in input_df.columns:
            input_df["recommender"] = recommender
    else:
        parsed_df = parse_recommendation_text(path)
        parsed_df["recommender"] = recommender
        append_recommendation_cache(parsed_df, output_dir)
        if load_all_cache:
            input_df = load_recommendation_cache(output_dir / "recommendation_cache.csv")
        else:
            input_df = parsed_df.copy()

    input_df["code"] = input_df["code"].map(normalize_code)
    input_df["date"] = pd.to_datetime(input_df["date"]).dt.strftime("%Y-%m-%d")
    if "recommender" not in input_df.columns:
        input_df["recommender"] = recommender
    return input_df


def parse_recommendation_text(path: str) -> pd.DataFrame:
    text = Path(path).read_text(encoding="utf-8")
    date_pattern = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
    month_day_pattern = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日(?!\d)")
    recommendation_pattern = re.compile(
        r"【\s*(?P<company>.*?)\s+(?P<code>\d{6})\s*】"
    )
    code_pattern = re.compile(r"(?<!\d)(\d{6})(?!\d)")
    theme_pattern = re.compile(r"题材[：:]\s*(?P<theme>.+)$")

    rows = []
    current_date: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        date_match = date_pattern.search(line)
        if date_match:
            year, month, day = date_match.groups()
            current_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        else:
            md_match = month_day_pattern.search(line)
            if md_match:
                month, day = md_match.groups()
                year = datetime.now().year
                current_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        matched_any = False
        for match in recommendation_pattern.finditer(line):
            if current_date is None:
                continue
            company_name = re.sub(r"\s+", "", match.group("company"))
            theme_match = theme_pattern.search(line)
            theme = theme_match.group("theme").strip() if theme_match else None
            rows.append(
                {
                    "date": current_date,
                    "code": match.group("code"),
                    "company_name": company_name or None,
                    "theme": theme,
                }
            )
            matched_any = True

        # Fallback: if line has plain code but no bracket structure.
        if not matched_any:
            for code in code_pattern.findall(line):
                if current_date is None:
                    continue
                theme_match = theme_pattern.search(line)
                theme = theme_match.group("theme").strip() if theme_match else None
                rows.append(
                    {
                        "date": current_date,
                        "code": code,
                        "company_name": None,
                        "theme": theme,
                    }
                )

    if not rows:
        raise ValueError(
            "No recommendation rows parsed from text source. "
            "Expected a date line and stock lines containing 6-digit codes."
        )

    return pd.DataFrame(rows)


def append_recommendation_cache(input_df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "recommendation_cache.csv"

    new_df = input_df.copy()
    new_df["code"] = new_df["code"].map(normalize_code)
    new_df["date"] = pd.to_datetime(new_df["date"]).dt.strftime("%Y-%m-%d")
    if "recommender" not in new_df.columns:
        new_df["recommender"] = "未知推荐人"
    new_df["recommender"] = new_df["recommender"].fillna("").astype(str).str.strip()
    new_df.loc[new_df["recommender"] == "", "recommender"] = "未知推荐人"

    if cache_path.exists():
        cached_df = pd.read_csv(cache_path, dtype={"code": str})
    else:
        cached_df = pd.DataFrame(
            columns=["date", "code", "company_name", "theme", "recommender"]
        )
    if "recommender" not in cached_df.columns:
        cached_df["recommender"] = "未知推荐人"
    cached_df["recommender"] = cached_df["recommender"].fillna("").astype(str).str.strip()
    cached_df.loc[cached_df["recommender"] == "", "recommender"] = "未知推荐人"

    merged = pd.concat([cached_df, new_df], ignore_index=True)
    # Canonical recommendation key: one stock code per day.
    merged = merged.drop_duplicates(subset=["date", "code"], keep="last")
    merged = merged.sort_values(["date", "code"])
    merged.to_csv(cache_path, index=False, encoding="utf-8-sig")
    print(f"Saved: {cache_path}")


def load_recommendation_cache(cache_path: Path) -> pd.DataFrame:
    if not cache_path.exists():
        return pd.DataFrame(
            columns=["date", "code", "company_name", "theme", "recommender"]
        )

    rec_df = pd.read_csv(cache_path, dtype={"code": str})
    for col in ["date", "code", "company_name", "theme", "recommender"]:
        if col not in rec_df.columns:
            rec_df[col] = "未知推荐人" if col == "recommender" else None
    rec_df["recommender"] = rec_df["recommender"].fillna("").astype(str).str.strip()
    rec_df.loc[rec_df["recommender"] == "", "recommender"] = "未知推荐人"
    rec_df["code"] = rec_df["code"].map(normalize_code)
    rec_df["date"] = pd.to_datetime(rec_df["date"]).dt.strftime("%Y-%m-%d")
    return rec_df[["date", "code", "company_name", "theme", "recommender"]]


def load_quote_cache(cache_path: Path) -> pd.DataFrame:
    if not cache_path.exists():
        return pd.DataFrame(
            columns=[
                "date",
                "code",
                "recommender",
                "stock_name",
                "company_name",
                "theme",
                "open_price",
                "close_price",
                "error",
                "return_rate",
                "position_cost",
                "position_profit",
                "updated_at",
            ]
        )

    quote_cache = pd.read_csv(cache_path, dtype={"code": str})
    expected_cols = [
        "date",
        "code",
        "recommender",
        "stock_name",
        "company_name",
        "theme",
        "open_price",
        "close_price",
        "error",
        "return_rate",
        "position_cost",
        "position_profit",
        "updated_at",
    ]
    for col in expected_cols:
        if col not in quote_cache.columns:
            quote_cache[col] = None
    quote_cache["recommender"] = quote_cache["recommender"].fillna("").astype(str).str.strip()
    quote_cache.loc[quote_cache["recommender"] == "", "recommender"] = "未知推荐人"
    return quote_cache[expected_cols]


def save_quote_cache(cache_df: pd.DataFrame, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    for col in ["date", "code", "recommender"]:
        if col not in cache_df.columns:
            cache_df[col] = None
    cache_df["recommender"] = cache_df["recommender"].fillna("").astype(str).str.strip()
    cache_df.loc[cache_df["recommender"] == "", "recommender"] = "未知推荐人"
    # Quote cache follows recommendation canonical key: date + code.
    dedup_df = cache_df.drop_duplicates(
        subset=["date", "code"], keep="last"
    ).sort_values(["date", "code"])
    dedup_df.to_csv(cache_path, index=False, encoding="utf-8-sig")
    print(f"Saved: {cache_path}")


def analyze(input_df: pd.DataFrame, quote_cache_path: Path) -> pd.DataFrame:
    rows = []
    quote_cache_df = load_quote_cache(quote_cache_path)
    recommendation_cache_df = load_recommendation_cache(
        quote_cache_path.parent / "recommendation_cache.csv"
    )
    if not recommendation_cache_df.empty and not quote_cache_df.empty:
        quote_cache_df = quote_cache_df.merge(
            recommendation_cache_df,
            on=["date", "code"],
            how="left",
            suffixes=("", "_rec"),
        )
        quote_cache_df["recommender"] = quote_cache_df["recommender"].where(
            quote_cache_df["recommender"].notna(), quote_cache_df["recommender_rec"]
        )
        quote_cache_df["company_name"] = quote_cache_df["company_name"].where(
            quote_cache_df["company_name"].notna(), quote_cache_df["company_name_rec"]
        )
        quote_cache_df["theme"] = quote_cache_df["theme"].where(
            quote_cache_df["theme"].notna(), quote_cache_df["theme_rec"]
        )
        quote_cache_df = quote_cache_df.drop(
            columns=["recommender_rec", "company_name_rec", "theme_rec"]
        )

    cache_lookup: Dict[tuple[str, str], Dict[str, object]] = {}
    for item in quote_cache_df.to_dict(orient="records"):
        cache_lookup[
            (
                str(item["date"]),
                normalize_code(str(item["code"])),
            )
        ] = item

    for rec in input_df.itertuples(index=False):
        recommender = getattr(rec, "recommender", "未知推荐人") or "未知推荐人"
        cache_key = (rec.date, rec.code)
        cached_quote = cache_lookup.get(cache_key)
        input_stock_name = getattr(rec, "company_name", None)
        input_theme = getattr(rec, "theme", None)
        normalized_theme = (
            input_theme
            if pd.notna(input_theme) and input_theme
            else (
                str(cached_quote["theme"])
                if cached_quote and pd.notna(cached_quote.get("theme"))
                else "未知题材"
            )
        )
        normalized_company_name = (
            input_stock_name
            if pd.notna(input_stock_name) and input_stock_name
            else (
                str(cached_quote["company_name"])
                if cached_quote and pd.notna(cached_quote.get("company_name"))
                else None
            )
        )

        if cached_quote:
            quote = QuoteResult(
                code=rec.code,
                date=rec.date,
                open_price=(
                    float(cached_quote["open_price"])
                    if pd.notna(cached_quote["open_price"])
                    else None
                ),
                close_price=(
                    float(cached_quote["close_price"])
                    if pd.notna(cached_quote["close_price"])
                    else None
                ),
                stock_name=(
                    str(cached_quote["stock_name"])
                    if pd.notna(cached_quote["stock_name"])
                    else None
                ),
                error=str(cached_quote["error"]) if pd.notna(cached_quote["error"]) else None,
            )
        else:
            quote = fetch_daily_quote(code=rec.code, date=rec.date)

        row = {
            "date": quote.date,
            "code": quote.code,
            "recommender": recommender,
            "stock_name": quote.stock_name or input_stock_name or (
                str(cached_quote["stock_name"]) if cached_quote and pd.notna(cached_quote["stock_name"]) else None
            ),
            "company_name": normalized_company_name,
            "theme": normalized_theme,
            "open_price": quote.open_price,
            "close_price": quote.close_price,
            "error": quote.error,
        }

        if quote.error is None and quote.open_price and quote.close_price:
            row["return_rate"] = (quote.close_price - quote.open_price) / quote.open_price
            row["position_cost"] = quote.open_price * LOTS_PER_STOCK
            row["position_profit"] = (quote.close_price - quote.open_price) * LOTS_PER_STOCK
        else:
            row["return_rate"] = None
            row["position_cost"] = None
            row["position_profit"] = None

        rows.append(row)
        cache_lookup[cache_key] = {
            "date": row["date"],
            "code": row["code"],
            "stock_name": row["stock_name"],
            "company_name": row["company_name"],
            "theme": row["theme"],
            "open_price": row["open_price"],
            "close_price": row["close_price"],
            "error": row["error"],
            "return_rate": row["return_rate"],
            "position_cost": row["position_cost"],
            "position_profit": row["position_profit"],
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    rows_df = pd.DataFrame(rows)
    merged_cache_df = pd.concat([quote_cache_df, rows_df], ignore_index=True)
    save_quote_cache(merged_cache_df, quote_cache_path)
    return rows_df


def build_daily_summary(detail_df: pd.DataFrame) -> pd.DataFrame:
    valid_df = detail_df[detail_df["error"].isna()].copy()
    if valid_df.empty:
        return pd.DataFrame(
            columns=["date", "stock_count", "avg_return_rate", "avg_position_profit"]
        )

    summary = (
        valid_df.groupby("date", as_index=False)
        .agg(
            stock_count=("code", "count"),
            avg_return_rate=("return_rate", "mean"),
            avg_position_profit=("position_profit", "mean"),
        )
        .sort_values("date")
    )
    return summary


def build_theme_summary(detail_df: pd.DataFrame) -> pd.DataFrame:
    valid_df = detail_df[detail_df["error"].isna()].copy()
    if valid_df.empty:
        return pd.DataFrame(
            columns=[
                "theme",
                "stock_count",
                "avg_return_rate",
                "total_position_profit",
            ]
        )

    summary = (
        valid_df.groupby("theme", as_index=False)
        .agg(
            stock_count=("code", "count"),
            avg_return_rate=("return_rate", "mean"),
            total_position_profit=("position_profit", "sum"),
        )
        .sort_values("avg_return_rate", ascending=False)
    )
    return summary


def build_stock_summary(detail_df: pd.DataFrame) -> pd.DataFrame:
    valid_df = detail_df[detail_df["error"].isna()].copy()
    if valid_df.empty:
        return pd.DataFrame(
            columns=[
                "code",
                "stock_name",
                "theme",
                "pick_count",
                "avg_return_rate",
                "total_position_profit",
            ]
        )

    summary = (
        valid_df.groupby(["code", "stock_name", "theme"], as_index=False)
        .agg(
            pick_count=("date", "count"),
            avg_return_rate=("return_rate", "mean"),
            total_position_profit=("position_profit", "sum"),
        )
        .sort_values("avg_return_rate", ascending=False)
    )
    return summary


def _format_percent_axis(ax: plt.Axes) -> None:
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.1%}")


def _configure_chinese_font() -> None:
    # Try common Windows/macOS/Linux Chinese fonts to reduce garbled labels.
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def generate_charts(
    output_dir: Path,
    daily_summary_df: pd.DataFrame,
    theme_summary_df: pd.DataFrame,
    stock_summary_df: pd.DataFrame,
) -> None:
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    _configure_chinese_font()

    if not daily_summary_df.empty:
        plot_df = daily_summary_df.copy()
        plot_df["date"] = pd.to_datetime(plot_df["date"])
        plot_df = plot_df.sort_values("date")

        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.plot(
            plot_df["date"],
            plot_df["avg_return_rate"],
            marker="o",
            linewidth=1.8,
            color="#1f77b4",
        )
        _format_percent_axis(ax)
        ax.set_title("每日平均收益率趋势")
        ax.set_xlabel("日期")
        ax.set_ylabel("平均收益率")
        ax.grid(True, linestyle="--", alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        daily_chart_path = charts_dir / "daily_avg_return_trend.png"
        fig.savefig(daily_chart_path, dpi=160)
        plt.close(fig)
        print(f"Saved: {daily_chart_path}")

    if not theme_summary_df.empty:
        plot_df = theme_summary_df.head(10).copy()
        fig, ax = plt.subplots(figsize=(10, 5.2))
        bars = ax.barh(plot_df["theme"], plot_df["avg_return_rate"], color="#2ca02c")
        _format_percent_axis(ax)
        ax.invert_yaxis()
        ax.set_title("题材平均收益率 Top10")
        ax.set_xlabel("平均收益率")
        ax.set_ylabel("题材")
        ax.grid(True, axis="x", linestyle="--", alpha=0.3)
        for bar in bars:
            width = bar.get_width()
            ax.text(width, bar.get_y() + bar.get_height() / 2, f" {width:.2%}", va="center")
        fig.tight_layout()
        theme_chart_path = charts_dir / "theme_avg_return_top10.png"
        fig.savefig(theme_chart_path, dpi=160)
        plt.close(fig)
        print(f"Saved: {theme_chart_path}")

    if not stock_summary_df.empty:
        top_n = min(5, len(stock_summary_df))
        top_df = stock_summary_df.head(top_n).copy()
        bottom_df = stock_summary_df.tail(top_n).iloc[::-1].copy()
        plot_df = pd.concat([top_df, bottom_df], ignore_index=True)
        plot_df["label"] = plot_df["code"] + " " + plot_df["stock_name"].fillna("")
        plot_df["color"] = plot_df["avg_return_rate"].apply(
            lambda x: "#d62728" if x < 0 else "#1f77b4"
        )

        fig, ax = plt.subplots(figsize=(11, 5.4))
        bars = ax.barh(plot_df["label"], plot_df["avg_return_rate"], color=plot_df["color"])
        _format_percent_axis(ax)
        ax.set_title("个股平均收益率 Top/Bottom")
        ax.set_xlabel("平均收益率")
        ax.set_ylabel("股票")
        ax.grid(True, axis="x", linestyle="--", alpha=0.3)
        for bar in bars:
            width = bar.get_width()
            text_x = width + 0.001 if width >= 0 else width - 0.001
            align = "left" if width >= 0 else "right"
            ax.text(text_x, bar.get_y() + bar.get_height() / 2, f"{width:.2%}", va="center", ha=align)
        fig.tight_layout()
        stock_chart_path = charts_dir / "stock_avg_return_top_bottom.png"
        fig.savefig(stock_chart_path, dpi=160)
        plt.close(fig)
        print(f"Saved: {stock_chart_path}")


def cleanup_deprecated_outputs(output_dir: Path) -> None:
    deprecated_files = [
        output_dir / "theme_summary.csv",
        output_dir / "stock_summary.csv",
        output_dir / "detail_analysis.csv",
        output_dir / "daily_summary.csv",
        output_dir / "recommendation_extracted.csv",
    ]
    for file_path in deprecated_files:
        if file_path.exists():
            file_path.unlink()
            print(f"Deleted: {file_path}")


def print_quick_report(daily_summary_df: pd.DataFrame, theme_summary_df: pd.DataFrame) -> None:
    if daily_summary_df.empty:
        print("No valid trading rows were found. Check input codes and dates.")
    else:
        overall_avg = daily_summary_df["avg_return_rate"].mean()
        print(f"Overall average return rate: {overall_avg:.4%}")
        print("Top 3 dates by average return:")
        print(daily_summary_df.sort_values("avg_return_rate", ascending=False).head(3).to_string(index=False))

    if not theme_summary_df.empty:
        print("Top 5 themes by average return:")
        print(theme_summary_df.head(5).to_string(index=False))


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    input_df = load_input(args.input, output_dir)

    quote_cache_path = output_dir / "quote_cache.csv"
    detail_df = analyze(input_df, quote_cache_path)
    daily_summary_df = build_daily_summary(detail_df)
    theme_summary_df = build_theme_summary(detail_df)
    stock_summary_df = build_stock_summary(detail_df)

    cleanup_deprecated_outputs(output_dir)
    generate_charts(output_dir, daily_summary_df, theme_summary_df, stock_summary_df)
    print_quick_report(daily_summary_df, theme_summary_df)


if __name__ == "__main__":
    main()
