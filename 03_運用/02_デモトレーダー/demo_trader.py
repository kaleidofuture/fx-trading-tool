"""
デモトレーダー

シグナル検出 → 自動ポジション建て → SL/TP/トレーリングストップ監視 → 自動決済
全てローカル完結。実際の発注は行わない。

使い方:
    python demo_trader.py                # 通常起動（4Hシグナル + 5分ごと価格監視）
    python demo_trader.py --once         # 1回だけ実行して終了
    python demo_trader.py --status       # 現在の状態表示
    python demo_trader.py --reset        # 全データリセット（確認あり）
"""

import sys
import io
import json
import argparse
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
BASE = Path(__file__).parent.parent.parent / "02_開発"
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
        logging.FileHandler(LOG_DIR / "demo_trader.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# === 設定 ===
INITIAL_BALANCE = 100_000  # 10万円
RISK_PER_TRADE = 0.01      # 1トレードあたり口座の1%
MAX_POSITIONS = 3           # 同時最大ポジション数
PRICE_CHECK_INTERVAL = 300  # 価格チェック間隔（秒）= 5分

# データファイル
DATA_DIR = Path(__file__).parent
ACCOUNT_FILE = DATA_DIR / "account.json"
TRADES_FILE = DATA_DIR / "trades.json"

# 監視する通貨ペア（8ペア）
PAIRS = [
    {"name": "USD/JPY", "ticker": "JPY=X", "pip_size": 0.01, "pip_value": 0.01, "spread": 0.3},
    {"name": "EUR/USD", "ticker": "EURUSD=X", "pip_size": 0.0001, "pip_value": 0.015, "spread": 0.2},
    {"name": "GBP/USD", "ticker": "GBPUSD=X", "pip_size": 0.0001, "pip_value": 0.015, "spread": 0.5},
    {"name": "AUD/USD", "ticker": "AUDUSD=X", "pip_size": 0.0001, "pip_value": 0.015, "spread": 0.4},
    {"name": "USD/CHF", "ticker": "CHF=X", "pip_size": 0.0001, "pip_value": 0.017, "spread": 0.5},
    {"name": "EUR/JPY", "ticker": "EURJPY=X", "pip_size": 0.01, "pip_value": 0.01, "spread": 0.5},
    {"name": "GBP/JPY", "ticker": "GBPJPY=X", "pip_size": 0.01, "pip_value": 0.01, "spread": 1.0},
    {"name": "AUD/JPY", "ticker": "AUDJPY=X", "pip_size": 0.01, "pip_value": 0.01, "spread": 0.6},
]

PAIR_MAP = {p["name"]: p for p in PAIRS}


# === アカウント管理 ===

def load_account() -> dict:
    """アカウント情報を読み込み"""
    if ACCOUNT_FILE.exists():
        return json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))
    account = {
        "initial_balance": INITIAL_BALANCE,
        "balance": INITIAL_BALANCE,
        "peak_balance": INITIAL_BALANCE,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_account(account)
    return account


def save_account(account: dict):
    ACCOUNT_FILE.write_text(json.dumps(account, indent=2, ensure_ascii=False), encoding="utf-8")


def load_trades() -> list:
    if TRADES_FILE.exists():
        return json.loads(TRADES_FILE.read_text(encoding="utf-8"))
    return []


def save_trades(trades: list):
    TRADES_FILE.write_text(json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8")


def next_trade_id(trades: list) -> int:
    if not trades:
        return 1
    return max(t["id"] for t in trades) + 1


# === 価格取得 ===

def fetch_current_price(ticker: str, pair_name: str) -> float | None:
    """現在価格を取得"""
    try:
        t = yf.Ticker(ticker)
        data = t.history(period="1d", interval="1m")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"{pair_name}: Price fetch failed: {e}")
        return None


def fetch_4h_data(ticker: str, pair_name: str) -> pd.DataFrame | None:
    """4時間足データ取得（シグナル計算用）"""
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="90d", interval="1h")
        if df.empty:
            return None
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df_4h = df.resample("4h").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()
        return df_4h
    except Exception as e:
        logger.error(f"{pair_name}: Data fetch failed: {e}")
        return None


# === ポジション管理 ===

def calculate_position_size(balance: float, atr: float, pip_size: float, pip_value: float) -> int:
    """ポジションサイズを計算（1%リスクルール）"""
    risk_amount = balance * RISK_PER_TRADE
    sl_pips = (atr * 2.0) / pip_size
    if sl_pips <= 0:
        return 0
    size = risk_amount / (sl_pips * pip_value)
    return int(size)


def open_position(account: dict, trades: list, signal: dict, pair: dict):
    """ポジションを建てる"""
    price = signal["price"]
    atr = signal["atr"]
    spread = pair["spread"] * pair["pip_size"]

    # スプレッド考慮のエントリー価格
    if signal["signal"] == "LONG":
        entry_price = price + spread / 2
        stop_loss = entry_price - atr * 2.0
        take_profit = entry_price + atr * 3.0
    else:
        entry_price = price - spread / 2
        stop_loss = entry_price + atr * 2.0
        take_profit = entry_price - atr * 3.0

    # ポジションサイズ
    size = calculate_position_size(
        account["balance"], atr, pair["pip_size"], pair["pip_value"]
    )
    if size <= 0:
        logger.warning(f"Position size too small, skipping")
        return None

    trade = {
        "id": next_trade_id(trades),
        "pair": signal["pair"],
        "direction": signal["signal"],
        "entry_price": round(entry_price, 5),
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "units": size,
        "stop_loss": round(stop_loss, 5),
        "take_profit": round(take_profit, 5),
        "initial_stop_loss": round(stop_loss, 5),  # トレーリング前のSL
        "atr_at_entry": round(atr, 5),
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "exit_reason": None,
        "pnl_jpy": None,
        "rsi": signal.get("rsi"),
        "signal_time": signal.get("time"),
    }

    trades.append(trade)
    save_trades(trades)

    logger.info(f"OPENED #{trade['id']}: {trade['pair']} {trade['direction']} "
                f"@ {entry_price:.5f} (SL={stop_loss:.5f} TP={take_profit:.5f} Units={size:,})")

    # デスクトップ通知
    send_notification(
        f"Demo Trade OPENED: {trade['pair']}",
        f"{trade['direction']} @ {entry_price:.5f}\nSL: {stop_loss:.5f}  TP: {take_profit:.5f}\nUnits: {size:,}"
    )

    return trade


def check_and_close_positions(account: dict, trades: list) -> bool:
    """全オープンポジションの価格をチェックし、SL/TP/トレーリングで決済。
    Returns: True if any action was taken (close or trailing update)."""
    open_trades = [t for t in trades if t["status"] == "OPEN"]
    if not open_trades:
        return False
    action_taken = False

    # ペアごとに価格をまとめて取得
    pairs_needed = set(t["pair"] for t in open_trades)
    prices = {}
    for pair_name in pairs_needed:
        pair = PAIR_MAP.get(pair_name)
        if pair:
            price = fetch_current_price(pair["ticker"], pair_name)
            if price is not None:
                prices[pair_name] = price

    for trade in open_trades:
        if trade["pair"] not in prices:
            continue

        current_price = prices[trade["pair"]]
        pair = PAIR_MAP[trade["pair"]]
        atr = trade["atr_at_entry"]

        if trade["direction"] == "LONG":
            # 損切りチェック
            if current_price <= trade["stop_loss"]:
                close_position(account, trades, trade, trade["stop_loss"], "sl")
                action_taken = True
                continue
            # 利確チェック
            if current_price >= trade["take_profit"]:
                close_position(account, trades, trade, trade["take_profit"], "tp")
                action_taken = True
                continue
            # トレーリングストップ
            profit = current_price - trade["entry_price"]
            if profit > atr * 2.0:
                new_sl = trade["entry_price"] + profit - atr
                if new_sl > trade["stop_loss"]:
                    old_sl = trade["stop_loss"]
                    trade["stop_loss"] = round(new_sl, 5)
                    save_trades(trades)
                    logger.info(f"  #{trade['id']} Trailing SL updated: {old_sl:.5f} -> {new_sl:.5f}")
                    action_taken = True
        else:  # SHORT
            if current_price >= trade["stop_loss"]:
                close_position(account, trades, trade, trade["stop_loss"], "sl")
                action_taken = True
                continue
            if current_price <= trade["take_profit"]:
                close_position(account, trades, trade, trade["take_profit"], "tp")
                action_taken = True
                continue
            profit = trade["entry_price"] - current_price
            if profit > atr * 2.0:
                new_sl = trade["entry_price"] - profit + atr
                if new_sl < trade["stop_loss"]:
                    old_sl = trade["stop_loss"]
                    trade["stop_loss"] = round(new_sl, 5)
                    save_trades(trades)
                    logger.info(f"  #{trade['id']} Trailing SL updated: {old_sl:.5f} -> {new_sl:.5f}")
                    action_taken = True

        # 含み損益表示
        if trade["direction"] == "LONG":
            unrealized = current_price - trade["entry_price"]
        else:
            unrealized = trade["entry_price"] - current_price
        pips = unrealized / pair["pip_size"]
        logger.info(f"  #{trade['id']} {trade['pair']} {trade['direction']}: "
                    f"current={current_price:.5f} unrealized={pips:+.1f}pips")

    return action_taken


def close_position(account: dict, trades: list, trade: dict, exit_price: float, reason: str):
    """ポジションを決済"""
    pair = PAIR_MAP[trade["pair"]]

    trade["exit_price"] = round(exit_price, 5)
    trade["exit_time"] = datetime.now(timezone.utc).isoformat()
    trade["exit_reason"] = reason
    trade["status"] = "CLOSED"

    # 損益計算
    if trade["direction"] == "LONG":
        price_diff = exit_price - trade["entry_price"]
    else:
        price_diff = trade["entry_price"] - exit_price

    pnl_pips = price_diff / pair["pip_size"]
    pnl_jpy = pnl_pips * pair["pip_value"] * trade["units"]
    trade["pnl_jpy"] = round(pnl_jpy, 0)
    trade["pnl_pips"] = round(pnl_pips, 1)

    # 口座残高更新
    account["balance"] = round(account["balance"] + pnl_jpy, 0)
    account["peak_balance"] = max(account["peak_balance"], account["balance"])
    save_account(account)
    save_trades(trades)

    result = "WIN" if pnl_jpy > 0 else "LOSS"
    logger.info(f"CLOSED #{trade['id']}: {trade['pair']} {trade['direction']} "
                f"@ {exit_price:.5f} [{reason}] "
                f"PnL={pnl_jpy:+,.0f}JPY ({pnl_pips:+.1f}pips) [{result}]")
    logger.info(f"  Balance: ¥{account['balance']:,.0f} "
                f"(Return: {(account['balance'] - account['initial_balance']) / account['initial_balance'] * 100:+.1f}%)")

    send_notification(
        f"Demo Trade CLOSED: {trade['pair']} [{result}]",
        f"{trade['direction']} @ {exit_price:.5f}\n"
        f"PnL: {pnl_jpy:+,.0f} JPY ({pnl_pips:+.1f}pips)\n"
        f"Balance: ¥{account['balance']:,.0f}"
    )


# === シグナル検出 ===

def check_signals(account: dict, trades: list):
    """全ペアのシグナルをチェックし、条件を満たせばポジションを建てる"""
    now = datetime.now(timezone.utc)
    logger.info(f"=== Signal Check @ {now.strftime('%Y-%m-%d %H:%M UTC')} ===")

    open_trades = [t for t in trades if t["status"] == "OPEN"]
    open_count = len(open_trades)
    open_pairs = set(t["pair"] for t in open_trades)

    logger.info(f"Balance: ¥{account['balance']:,.0f}  Open: {open_count}/{MAX_POSITIONS}")

    # ドローダウンチェック
    dd = (account["peak_balance"] - account["balance"]) / account["peak_balance"] if account["peak_balance"] > 0 else 0
    if dd >= 0.20:
        logger.warning(f"Max drawdown reached ({dd:.1%}). Trading suspended.")
        return

    signals_opened = 0

    for pair in PAIRS:
        if open_count + signals_opened >= MAX_POSITIONS:
            logger.info(f"{pair['name']}: Skipped (position limit)")
            continue

        # 同一ペアの重複ポジションを回避
        if pair["name"] in open_pairs:
            logger.info(f"{pair['name']}: Skipped (already has open position)")
            continue

        df = fetch_4h_data(pair["ticker"], pair["name"])
        if df is None or len(df) < 201:
            logger.info(f"{pair['name']}: Insufficient data")
            continue

        strategy = DualMomentumStrategy()
        strategy.prepare(df)
        data = strategy.data
        idx = len(data) - 1

        signal, skip_reasons = strategy.filtered_signal(idx)

        if skip_reasons:
            logger.info(f"{pair['name']}: Filtered ({', '.join(skip_reasons)})")
            continue

        if signal is None:
            logger.info(f"{pair['name']}: No signal")
            continue

        row = data.iloc[idx]
        atr = strategy.get_atr(idx)

        sig_data = {
            "pair": pair["name"],
            "time": str(data.index[idx]),
            "signal": signal.value,
            "price": round(float(row["Close"]), 5),
            "atr": round(float(atr), 5),
            "rsi": round(float(row["RSI"]), 1),
        }

        logger.info(f"{pair['name']}: SIGNAL -> {signal.value} @ {sig_data['price']}")
        trade = open_position(account, trades, sig_data, pair)
        if trade:
            signals_opened += 1
            open_pairs.add(pair["name"])

    if signals_opened == 0:
        logger.info("No new positions opened.")


# === 通知 ===

def send_notification(title: str, message: str):
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="FX Demo Trader", timeout=30)
    except Exception:
        pass  # 通知失敗は無視


# === ステータス表示 ===

def show_status():
    """現在の状態を表示"""
    account = load_account()
    trades = load_trades()
    open_trades = [t for t in trades if t["status"] == "OPEN"]
    closed_trades = [t for t in trades if t["status"] == "CLOSED"]

    ret = (account["balance"] - account["initial_balance"]) / account["initial_balance"] * 100
    dd = (account["peak_balance"] - account["balance"]) / account["peak_balance"] * 100 if account["peak_balance"] > 0 else 0

    print(f"\n{'='*55}")
    print(f"  FX Demo Trader - Status")
    print(f"{'='*55}")
    print(f"  Initial:  ¥{account['initial_balance']:>10,.0f}")
    print(f"  Balance:  ¥{account['balance']:>10,.0f}  ({ret:+.1f}%)")
    print(f"  Peak:     ¥{account['peak_balance']:>10,.0f}")
    print(f"  DD:       {dd:.1f}%")
    print(f"  Started:  {account['created_at'][:10]}")
    print(f"{'='*55}")

    if open_trades:
        print(f"\n  Open Positions ({len(open_trades)}/{MAX_POSITIONS}):")
        for t in open_trades:
            print(f"    #{t['id']} {t['pair']} {t['direction']} @ {t['entry_price']:.5f}"
                  f"  SL={t['stop_loss']:.5f}  TP={t['take_profit']:.5f}  Units={t['units']:,}")
    else:
        print(f"\n  No open positions.")

    if closed_trades:
        wins = sum(1 for t in closed_trades if t.get("pnl_jpy", 0) > 0)
        total_pnl = sum(t.get("pnl_jpy", 0) for t in closed_trades)
        wr = wins / len(closed_trades) * 100 if closed_trades else 0
        print(f"\n  Closed: {len(closed_trades)} trades  WR: {wr:.0f}%  PnL: ¥{total_pnl:+,.0f}")

        # 直近5件
        print(f"\n  Recent trades:")
        for t in closed_trades[-5:]:
            pnl = t.get("pnl_jpy", 0)
            result = "W" if pnl > 0 else "L"
            print(f"    #{t['id']} {t['pair']:8s} {t['direction']:5s} "
                  f"¥{pnl:+8,.0f} [{t.get('exit_reason', '?')}] {result}")

    print()


# === 次の4H境界 ===

def next_4h_boundary() -> int:
    now = datetime.now(timezone.utc)
    next_hour = ((now.hour // 4) + 1) * 4
    if next_hour >= 24:
        next_hour = 0
    next_time = now.replace(hour=next_hour % 24, minute=5, second=0, microsecond=0)
    if next_time <= now:
        next_time = next_time + pd.Timedelta(days=1)
    return int((next_time - now).total_seconds())


# === メインループ ===

def main():
    parser = argparse.ArgumentParser(description="FX Demo Trader")
    parser.add_argument("--once", action="store_true", help="1回だけ実行")
    parser.add_argument("--status", action="store_true", help="状態表示")
    parser.add_argument("--reset", action="store_true", help="全データリセット")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.reset:
        confirm = input("全トレードデータをリセットしますか？ (yes/no): ")
        if confirm.lower() == "yes":
            if ACCOUNT_FILE.exists():
                ACCOUNT_FILE.unlink()
            if TRADES_FILE.exists():
                TRADES_FILE.unlink()
            print("リセット完了。")
        else:
            print("キャンセルしました。")
        return

    account = load_account()
    trades = load_trades()

    logger.info("=" * 55)
    logger.info("FX Demo Trader - Dual Momentum Trend Following")
    logger.info(f"Balance: ¥{account['balance']:,.0f}  Pairs: {len(PAIRS)}")
    logger.info(f"Risk: {RISK_PER_TRADE*100}% per trade  Max positions: {MAX_POSITIONS}")
    logger.info("=" * 55)

    if args.once:
        # 1回だけ: シグナルチェック + ポジション監視
        check_signals(account, trades)
        trades = load_trades()
        action = check_and_close_positions(account, trades)

        # アクションがあった場合、5分後に再チェック（最大3回）
        for i in range(3):
            if not action:
                break
            remaining = [t for t in load_trades() if t["status"] == "OPEN"]
            if not remaining:
                break
            logger.info(f"Action detected. Follow-up check in 5 minutes... ({i+1}/3)")
            sleep(300)
            account = load_account()
            trades = load_trades()
            action = check_and_close_positions(account, trades)

        show_status()
        return

    # 継続モード
    send_notification(
        "FX Demo Trader Started",
        f"Balance: ¥{account['balance']:,.0f}\n{len(PAIRS)} pairs monitored"
    )

    last_signal_check = 0  # 最後にシグナルチェックした時刻（epoch）

    while True:
        try:
            now = datetime.now(timezone.utc)
            now_epoch = now.timestamp()

            # シグナルチェック（4H境界 or 初回）
            current_4h_block = now.hour // 4
            if last_signal_check == 0 or (now.minute < 10 and now_epoch - last_signal_check > 3600):
                # 4H境界の最初の10分以内、かつ前回から1時間以上経過
                account = load_account()
                trades = load_trades()
                check_signals(account, trades)
                last_signal_check = now_epoch

            # ポジション監視（毎回）
            account = load_account()
            trades = load_trades()
            check_and_close_positions(account, trades)

            # 次のチェックまで待機
            logger.info(f"Next price check in {PRICE_CHECK_INTERVAL}s...")
            sleep(PRICE_CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Demo Trader stopped by user.")
            show_status()
            break
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            sleep(60)


if __name__ == "__main__":
    main()
