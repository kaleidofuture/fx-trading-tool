"""
バックテスト実行スクリプト

USD/JPY と EUR/USD の 1時間足データで Dual Momentum 戦略を検証する。
4時間足は1時間足を4本ずつリサンプリングして生成する。
"""

import sys
import io
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Windows cp932 対策
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# パス解決
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE / "02_バックテスト基盤"))
sys.path.insert(0, str(BASE / "03_戦略実装"))

from backtest_engine import BacktestEngine
from dual_momentum import DualMomentumStrategy

DATA_DIR = BASE / "01_データ取得" / "data"


def load_and_resample_4h(csv_path: Path) -> pd.DataFrame:
    """1時間足CSVを読み込み、4時間足にリサンプリング"""
    df = pd.read_csv(csv_path, index_col="Datetime")
    df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)

    # 4時間足にリサンプリング
    df_4h = df.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()

    return df_4h


REPORT_DIR = BASE / "reports"
REPORT_DIR.mkdir(exist_ok=True)


def run_single(pair_name: str, csv_filename: str, pip_size: float, pip_value: float, spread: float):
    """1通貨ペアのバックテスト"""
    csv_path = DATA_DIR / csv_filename
    if not csv_path.exists():
        print(f"  [SKIP] {csv_path} not found")
        return None

    print(f"\n{'='*60}")
    print(f"  {pair_name} - Dual Momentum Trend Following (4H)")
    print(f"{'='*60}")

    # データ準備
    df = load_and_resample_4h(csv_path)
    print(f"  データ: {len(df)} bars ({df.index[0]} ~ {df.index[-1]})")

    # インサンプル / アウトオブサンプル 分割（70% / 30%）
    split_idx = int(len(df) * 0.7)
    df_in = df.iloc[:split_idx]
    df_out = df.iloc[split_idx:]

    results = {}
    for label, tag, data in [
        ("IN-SAMPLE (70%)", "in", df_in),
        ("OUT-OF-SAMPLE (30%)", "out", df_out),
    ]:
        print(f"\n--- {label}: {len(data)} bars ---")

        strategy = DualMomentumStrategy()
        engine = BacktestEngine(
            data=data,
            initial_balance=1_000_000,  # 100万円
            spread_pips=spread,
            pip_size=pip_size,
            pip_value_per_unit=pip_value,
        )
        result = engine.run(strategy)
        results[tag] = result
        print(result.summary())

        # トレード詳細（直近5件）
        if result.trades:
            print(f"\n  直近トレード（最大5件）:")
            for t in result.trades[-5:]:
                pips_fmt = f"{t.pnl_pips:+.1f}" if t.pnl_pips else "N/A"
                print(f"    {t.entry_time} {t.side.value:5s} "
                      f"entry={t.entry_price:.5f} exit={t.exit_price:.5f} "
                      f"pnl=¥{t.pnl:+,.0f} ({pips_fmt}pips) [{t.exit_reason}]")

    # グラフ生成
    pair_tag = pair_name.replace("/", "")
    generate_chart(pair_name, pair_tag, df, results, split_idx)

    return results


def generate_chart(pair_name: str, pair_tag: str, df: pd.DataFrame, results: dict, split_idx: int):
    """エクイティカーブと価格チャートを生成"""
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), gridspec_kw={"height_ratios": [2, 2, 1]})
    fig.suptitle(f"{pair_name} - Dual Momentum Trend Following (4H)", fontsize=14, fontweight="bold")

    # --- 1. 価格チャート + エントリー/イグジット ---
    ax1 = axes[0]
    ax1.plot(df.index, df["Close"], color="#555555", linewidth=0.8, label="Close")
    ax1.axvline(df.index[split_idx], color="orange", linestyle="--", alpha=0.7, label="In/Out split")

    for tag, color_win, color_loss in [("in", "#2196F3", "#FF5722"), ("out", "#4CAF50", "#E91E63")]:
        if tag not in results:
            continue
        for t in results[tag].trades:
            color = color_win if t.pnl and t.pnl > 0 else color_loss
            marker_entry = "^" if t.side.value == "LONG" else "v"
            ax1.scatter(t.entry_time, t.entry_price, marker=marker_entry, color=color, s=60, zorder=5)
            if t.exit_time and t.exit_price:
                ax1.scatter(t.exit_time, t.exit_price, marker="x", color=color, s=60, zorder=5)

    ax1.set_ylabel("Price")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.3)

    # --- 2. エクイティカーブ ---
    ax2 = axes[1]
    for tag, label, color in [("in", "In-Sample", "#2196F3"), ("out", "Out-of-Sample", "#4CAF50")]:
        if tag in results:
            eq = results[tag].equity_curve
            ax2.plot(eq.index, eq.values, color=color, linewidth=1.5, label=label)

    ax2.axhline(1_000_000, color="gray", linestyle="--", alpha=0.5, label="Initial")
    ax2.set_ylabel("Equity (JPY)")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, alpha=0.3)

    # --- 3. ドローダウン ---
    ax3 = axes[2]
    for tag, color in [("in", "#2196F3"), ("out", "#4CAF50")]:
        if tag in results:
            eq = results[tag].equity_curve
            peak = eq.expanding().max()
            dd_pct = (eq - peak) / peak * 100
            ax3.fill_between(dd_pct.index, dd_pct.values, 0, color=color, alpha=0.3)
            ax3.plot(dd_pct.index, dd_pct.values, color=color, linewidth=0.8)

    ax3.axhline(-20, color="red", linestyle="--", alpha=0.5, label="Stop limit (-20%)")
    ax3.set_ylabel("Drawdown (%)")
    ax3.legend(loc="lower left", fontsize=8)
    ax3.grid(True, alpha=0.3)

    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    plt.tight_layout()
    chart_path = REPORT_DIR / f"{pair_tag}_backtest.png"
    fig.savefig(chart_path, dpi=150)
    plt.close(fig)
    print(f"\n  Chart saved: {chart_path}")


def main():
    print("Dual Momentum Trend Following - Backtest")
    print("初期資金: ¥1,000,000")
    print("リスク: 1トレードあたり口座の1%")

    # USD/JPY: 1pip = 0.01円, 1通貨あたり1pipの価値 = 0.01円
    # 1万通貨なら 1pip = 100円
    run_single(
        pair_name="USD/JPY",
        csv_filename="USDJPY_1h.csv",
        pip_size=0.01,
        pip_value=0.01,   # 1通貨単位あたり1pipの円価値
        spread=0.3,
    )

    # EUR/USD: 1pip = 0.0001ドル
    # 1通貨（1ユーロ）× 1pip(0.0001ドル) = 0.0001ドル
    # 円換算: 0.0001 × 150 = 0.015円/通貨/pip
    # ただし取引単位は通貨数で、ポジションサイズ計算で調整される
    run_single(
        pair_name="EUR/USD",
        csv_filename="EURUSD_1h.csv",
        pip_size=0.0001,
        pip_value=0.015,  # 1通貨あたり1pipの円価値（USD/JPY≒150で概算）
        spread=0.2,
    )


if __name__ == "__main__":
    main()
