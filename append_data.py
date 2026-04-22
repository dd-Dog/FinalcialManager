from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from financial_manager import analyze, load_input


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append new recommendation data into local caches."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input source file (txt/csv). Example: 张少辉.txt",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory for cache files.",
    )
    return parser.parse_args()


def count_missing_quote_rows(output_dir: Path) -> int:
    rec_path = output_dir / "recommendation_cache.csv"
    quote_path = output_dir / "quote_cache.csv"
    if not rec_path.exists():
        return 0

    rec_df = pd.read_csv(rec_path, dtype={"code": str})
    if quote_path.exists():
        quote_df = pd.read_csv(quote_path, dtype={"code": str})
    else:
        quote_df = pd.DataFrame(columns=["date", "code", "recommender"])

    for df in (rec_df, quote_df):
        if "recommender" not in df.columns:
            df["recommender"] = "未知推荐人"
        df["recommender"] = df["recommender"].fillna("").astype(str).str.strip()
        df.loc[df["recommender"] == "", "recommender"] = "未知推荐人"
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["code"] = df["code"].astype(str).str.zfill(6)

    rec_keys = set(zip(rec_df["date"], rec_df["code"]))
    quote_keys = set(zip(quote_df["date"], quote_df["code"]))
    return len(rec_keys - quote_keys)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)

    missing_before = count_missing_quote_rows(output_dir)

    # Sync mode: append current input first, then align all recommendation rows into quote cache.
    input_df = load_input(args.input, output_dir, load_all_cache=True)
    detail_df = analyze(input_df, output_dir / "quote_cache.csv")
    missing_after = count_missing_quote_rows(output_dir)

    success_count = int(detail_df["error"].isna().sum())
    fail_count = int(detail_df["error"].notna().sum())
    print(
        f"Incremental sync completed. total={len(detail_df)}, "
        f"success={success_count}, failed={fail_count}"
    )
    print(
        f"Quote cache alignment: missing_before={missing_before}, "
        f"missing_after={missing_after}"
    )
    print(f"Saved: {output_dir / 'recommendation_cache.csv'}")
    print(f"Saved: {output_dir / 'quote_cache.csv'}")


if __name__ == "__main__":
    main()
