"""
FX過去データ取得スクリプト

Yahoo Finance から USD/JPY, EUR/USD の過去データを取得し、CSVに保存する。
yfinance では FX ペアは "USDJPY=X", "EURUSD=X" の形式で指定する。
"""

import sys
from pathlib import Path

import yfinance as yf
import pandas as pd

# 保存先
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# 取得する通貨ペア
PAIRS = {
    "USDJPY": "JPY=X",
    "EURUSD": "EURUSD=X",
}

# 期間設定（yfinance の 1h足は過去730日まで取得可能）
CONFIGS = [
    {"interval": "1d", "period": "10y", "suffix": "daily"},
    {"interval": "1h", "period": "730d", "suffix": "1h"},
]


def fetch_pair(pair_name: str, ticker: str, interval: str, period: str) -> pd.DataFrame:
    """1通貨ペア・1時間足の取得"""
    print(f"  {pair_name} ({ticker}) interval={interval} period={period} ...", end=" ")
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval)

    if df.empty:
        print("NO DATA")
        return df

    # 不要列の削除・整理
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index.name = "Datetime"
    df = df.round(5)

    print(f"{len(df)} rows")
    return df


def main():
    for cfg in CONFIGS:
        print(f"\n=== {cfg['suffix']} (interval={cfg['interval']}, period={cfg['period']}) ===")
        for pair_name, ticker in PAIRS.items():
            df = fetch_pair(pair_name, ticker, cfg["interval"], cfg["period"])
            if not df.empty:
                path = DATA_DIR / f"{pair_name}_{cfg['suffix']}.csv"
                df.to_csv(path)
                print(f"    -> saved: {path}")

    # サマリ表示
    print("\n=== Data Summary ===")
    for csv_file in sorted(DATA_DIR.glob("*.csv")):
        df = pd.read_csv(csv_file)
        print(f"  {csv_file.name}: {len(df)} rows, "
              f"{df.iloc[0, 0]} ~ {df.iloc[-1, 0]}")


if __name__ == "__main__":
    main()
