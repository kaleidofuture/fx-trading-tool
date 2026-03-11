"""
シグナル通知モニター

4時間足の確定タイミングで Dual Momentum 戦略のシグナルをチェックし、
デスクトップ通知 + ログ出力する。

使い方:
    python signal_monitor.py              # 通常起動（4時間ごとにチェック）
    python signal_monitor.py --once       # 1回だけチェックして終了（テスト用）
    python signal_monitor.py --interval 60  # 60秒ごとにチェック（デバッグ用）
"""

import sys
import io
import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from time import sleep

import pandas as pd
import yfinance as yf

# Windows cp932 対策
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# パス解決
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE / "02_バックテスト基盤"))
sys.path.insert(0, str(BASE / "03_戦略実装"))

from backtest_engine import Side
from dual_momentum import DualMomentumStrategy

# ログ設定
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "signal_monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# シグナル履歴
HISTORY_FILE = Path(__file__).parent / "signal_history.json"

# 監視する通貨ペア（メジャー + 主要クロス円）
PAIRS = [
    # メジャーペア
    {"name": "USD/JPY", "ticker": "JPY=X", "pip_size": 0.01, "pip_value": 0.01, "spread": 0.3},
    {"name": "EUR/USD", "ticker": "EURUSD=X", "pip_size": 0.0001, "pip_value": 0.015, "spread": 0.2},
    {"name": "GBP/USD", "ticker": "GBPUSD=X", "pip_size": 0.0001, "pip_value": 0.015, "spread": 0.5},
    {"name": "AUD/USD", "ticker": "AUDUSD=X", "pip_size": 0.0001, "pip_value": 0.015, "spread": 0.4},
    {"name": "USD/CHF", "ticker": "CHF=X", "pip_size": 0.0001, "pip_value": 0.017, "spread": 0.5},
    # クロス円
    {"name": "EUR/JPY", "ticker": "EURJPY=X", "pip_size": 0.01, "pip_value": 0.01, "spread": 0.5},
    {"name": "GBP/JPY", "ticker": "GBPJPY=X", "pip_size": 0.01, "pip_value": 0.01, "spread": 1.0},
    {"name": "AUD/JPY", "ticker": "AUDJPY=X", "pip_size": 0.01, "pip_value": 0.01, "spread": 0.6},
]


def send_notification(title: str, message: str):
    """デスクトップ通知を送る"""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="FX Signal Monitor",
            timeout=30,
        )
        logger.info(f"Notification sent: {title}")
    except Exception as e:
        logger.warning(f"Notification failed: {e}")


def fetch_4h_data(ticker: str, pair_name: str) -> pd.DataFrame | None:
    """yfinance から直近の1時間足を取得し、4時間足にリサンプリング"""
    try:
        t = yf.Ticker(ticker)
        # 4H足のシグナル計算にEMA(200)が必要 → 200×4=800時間 ≈ 34日分は最低必要
        # 余裕を見て90日分取得
        df = t.history(period="90d", interval="1h")

        if df.empty:
            logger.warning(f"{pair_name}: No data returned")
            return None

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()

        # タイムゾーン除去
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # 4時間足にリサンプリング
        df_4h = df.resample("4h").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()

        logger.info(f"{pair_name}: {len(df_4h)} bars (4H), latest={df_4h.index[-1]}")
        return df_4h

    except Exception as e:
        logger.error(f"{pair_name}: Data fetch failed: {e}")
        return None


def get_open_position_count() -> int:
    """現在のオープンポジション数を取得（trade_log の trades.json から）"""
    trades_file = Path(__file__).parent.parent.parent / "03_運用" / "01_デモトレード記録" / "trades.json"
    if not trades_file.exists():
        return 0
    try:
        trades = json.loads(trades_file.read_text(encoding="utf-8"))
        return len([t for t in trades if t.get("status") == "OPEN"])
    except (json.JSONDecodeError, KeyError):
        return 0


MAX_POSITIONS = 3  # 同時最大ポジション数


def check_signal(pair: dict) -> dict | None:
    """1通貨ペアのシグナルをチェック（品質フィルター付き）"""
    df = fetch_4h_data(pair["ticker"], pair["name"])
    if df is None or len(df) < 201:
        return None

    strategy = DualMomentumStrategy()
    strategy.prepare(df)
    data = strategy.data

    # 最新バーでフィルター付きシグナル確認
    idx = len(data) - 1
    signal, skip_reasons = strategy.filtered_signal(idx)

    if skip_reasons:
        logger.info(f"{pair['name']}: Signal detected but FILTERED OUT ({', '.join(skip_reasons)})")
        # フィルターで除外されたシグナルも履歴に残す（分析用）
        row = data.iloc[idx]
        save_signal({
            "pair": pair["name"],
            "time": str(data.index[idx]),
            "signal": strategy.signal(idx).value,
            "price": round(float(row["Close"]), 5),
            "filtered": True,
            "filter_reasons": skip_reasons,
        })
        return None

    if signal is None:
        return None

    row = data.iloc[idx]
    atr = strategy.get_atr(idx)

    if signal == Side.LONG:
        sl = row["Close"] - atr * 2.0
        tp = row["Close"] + atr * 3.0
    else:
        sl = row["Close"] + atr * 2.0
        tp = row["Close"] - atr * 3.0

    return {
        "pair": pair["name"],
        "time": str(data.index[idx]),
        "signal": signal.value,
        "price": round(float(row["Close"]), 5),
        "atr": round(float(atr), 5),
        "stop_loss": round(float(sl), 5),
        "take_profit": round(float(tp), 5),
        "rsi": round(float(row["RSI"]), 1),
        "ema_short": round(float(row["EMA_short"]), 5),
        "ema_mid": round(float(row["EMA_mid"]), 5),
        "ema_long": round(float(row["EMA_long"]), 5),
        "filtered": False,
        "filter_reasons": [],
    }


def save_signal(signal_data: dict):
    """シグナル履歴を保存"""
    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    signal_data["detected_at"] = datetime.now(timezone.utc).isoformat()
    history.append(signal_data)

    # 直近100件のみ保持
    history = history[-100:]
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def format_signal_message(sig: dict) -> str:
    """通知メッセージを整形"""
    direction = "BUY (LONG)" if sig["signal"] == "LONG" else "SELL (SHORT)"
    arrow = "^" if sig["signal"] == "LONG" else "v"

    lines = [
        f"{arrow} {sig['pair']} {direction}",
        f"Price: {sig['price']}",
        f"SL: {sig['stop_loss']}  TP: {sig['take_profit']}",
        f"ATR: {sig['atr']}  RSI: {sig['rsi']}",
    ]
    return "\n".join(lines)


def run_check():
    """全通貨ペアのシグナルチェック"""
    now = datetime.now(timezone.utc)
    logger.info(f"=== Signal Check @ {now.strftime('%Y-%m-%d %H:%M UTC')} ===")

    # ポジション上限チェック
    open_count = get_open_position_count()
    logger.info(f"Open positions: {open_count}/{MAX_POSITIONS}")

    signals_found = []

    for pair in PAIRS:
        # 同時ポジション上限チェック
        if open_count + len(signals_found) >= MAX_POSITIONS:
            logger.info(f"{pair['name']}: Skipped (position limit {MAX_POSITIONS} reached)")
            continue

        sig = check_signal(pair)
        if sig:
            signals_found.append(sig)
            msg = format_signal_message(sig)
            logger.info(f"SIGNAL DETECTED!\n{msg}")
            send_notification(
                title=f"FX Signal: {sig['pair']} {sig['signal']}",
                message=msg,
            )
            save_signal(sig)
        else:
            logger.info(f"{pair['name']}: No signal")

    if not signals_found:
        logger.info("No signals detected.")

    return signals_found


def next_4h_boundary() -> int:
    """次の4時間境界までの秒数を計算"""
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    # 4時間境界: 0, 4, 8, 12, 16, 20
    next_boundary_hour = ((current_hour // 4) + 1) * 4
    if next_boundary_hour >= 24:
        next_boundary_hour = 0

    next_time = now.replace(
        hour=next_boundary_hour % 24,
        minute=5,  # 5分の余裕（ローソク足確定待ち）
        second=0,
        microsecond=0,
    )
    if next_time <= now:
        # 翌日の同時刻
        next_time = next_time + pd.Timedelta(days=1)

    wait_seconds = (next_time - now).total_seconds()
    logger.info(f"Next check at {next_time.strftime('%H:%M UTC')} (in {wait_seconds/60:.0f} min)")
    return int(wait_seconds)


def main():
    parser = argparse.ArgumentParser(description="FX Signal Monitor")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=0,
                        help="Check interval in seconds (0=auto 4H boundary)")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("FX Signal Monitor - Dual Momentum Trend Following")
    logger.info("Pairs: " + ", ".join(p["name"] for p in PAIRS))
    logger.info("Timeframe: 4H")
    logger.info("=" * 50)

    if args.once:
        signals = run_check()
        if signals:
            for s in signals:
                print(f"\n{format_signal_message(s)}")
        else:
            print("\nNo signals at this time.")
        return

    # 継続監視モード
    send_notification(
        title="FX Signal Monitor Started",
        message=f"Monitoring {', '.join(p['name'] for p in PAIRS)} on 4H timeframe",
    )

    while True:
        try:
            run_check()

            if args.interval > 0:
                wait = args.interval
                logger.info(f"Waiting {wait} seconds...")
            else:
                wait = next_4h_boundary()

            sleep(wait)

        except KeyboardInterrupt:
            logger.info("Monitor stopped by user.")
            break
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            logger.info("Retrying in 60 seconds...")
            sleep(60)


if __name__ == "__main__":
    main()
