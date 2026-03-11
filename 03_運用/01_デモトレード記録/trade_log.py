"""
デモトレード記録ツール

シグナル通知を受けて手動発注した結果を記録・集計する。

使い方:
    python trade_log.py add                    # 新規トレードを記録（対話形式）
    python trade_log.py close <trade_id>       # トレードをクローズ
    python trade_log.py list                   # オープンポジション一覧
    python trade_log.py history                # 全トレード履歴
    python trade_log.py report                 # パフォーマンスレポート
"""

import sys
import io
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Windows cp932 対策
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TRADES_FILE = Path(__file__).parent / "trades.json"


def load_trades() -> list:
    if TRADES_FILE.exists():
        return json.loads(TRADES_FILE.read_text(encoding="utf-8"))
    return []


def save_trades(trades: list):
    TRADES_FILE.write_text(
        json.dumps(trades, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def next_id(trades: list) -> int:
    if not trades:
        return 1
    return max(t["id"] for t in trades) + 1


def add_trade(trades: list) -> dict:
    """対話形式で新規トレードを記録"""
    print("\n=== 新規トレード記録 ===\n")

    print("通貨ペア: 1=USD/JPY 2=EUR/USD 3=GBP/USD 4=AUD/USD")
    print("         5=USD/CHF 6=EUR/JPY 7=GBP/JPY 8=AUD/JPY")
    pair = input("番号または通貨ペア名: ").strip()
    pair_map = {
        "1": "USD/JPY", "2": "EUR/USD", "3": "GBP/USD", "4": "AUD/USD",
        "5": "USD/CHF", "6": "EUR/JPY", "7": "GBP/JPY", "8": "AUD/JPY",
    }
    pair_name = pair_map.get(pair, pair)

    direction = input("方向 (L=LONG/買い, S=SHORT/売り): ").strip().upper()
    direction = "LONG" if direction.startswith("L") else "SHORT"

    entry_price = float(input("エントリー価格: ").strip())
    units = int(input("取引数量 (通貨単位): ").strip())
    sl = float(input("ストップロス価格: ").strip())
    tp = float(input("テイクプロフィット価格: ").strip())
    note = input("メモ (任意): ").strip()

    trade = {
        "id": next_id(trades),
        "pair": pair_name,
        "direction": direction,
        "entry_price": entry_price,
        "units": units,
        "stop_loss": sl,
        "take_profit": tp,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "exit_price": None,
        "exit_time": None,
        "pnl_jpy": None,
        "status": "OPEN",
        "note": note,
    }

    trades.append(trade)
    save_trades(trades)

    print(f"\nTrade #{trade['id']} を記録しました。")
    print(f"  {pair_name} {direction} @ {entry_price}")
    print(f"  SL: {sl}  TP: {tp}  Units: {units}")
    return trade


def close_trade(trades: list, trade_id: int):
    """トレードをクローズ"""
    trade = None
    for t in trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            trade = t
            break

    if not trade:
        print(f"Trade #{trade_id} が見つからないか、既にクローズされています。")
        return

    print(f"\n=== Trade #{trade_id} クローズ ===")
    print(f"  {trade['pair']} {trade['direction']} @ {trade['entry_price']}")

    exit_price = float(input("決済価格: ").strip())
    reason = input("決済理由 (TP/SL/手動/その他): ").strip()

    trade["exit_price"] = exit_price
    trade["exit_time"] = datetime.now(timezone.utc).isoformat()
    trade["status"] = "CLOSED"
    trade["exit_reason"] = reason

    # PnL計算
    diff = exit_price - trade["entry_price"]
    if trade["direction"] == "SHORT":
        diff = -diff
    if trade["pair"].endswith("/JPY"):
        # クロス円: 差額 × 数量 = 円建てPnL
        trade["pnl_jpy"] = round(diff * trade["units"], 0)
    else:
        # ドルストレート等: 差額 × 数量 × 概算150円
        trade["pnl_jpy"] = round(diff * trade["units"] * 150, 0)

    save_trades(trades)

    result = "勝ち" if trade["pnl_jpy"] > 0 else "負け" if trade["pnl_jpy"] < 0 else "引き分け"
    print(f"\n  決済価格: {exit_price}")
    print(f"  損益: {trade['pnl_jpy']:+,.0f} 円 ({result})")
    print(f"  理由: {reason}")


def list_open(trades: list):
    """オープンポジション一覧"""
    open_trades = [t for t in trades if t["status"] == "OPEN"]
    if not open_trades:
        print("\nオープンポジションはありません。")
        return

    print(f"\n=== オープンポジション ({len(open_trades)}件) ===\n")
    print(f"{'ID':>4}  {'ペア':<8}  {'方向':<6}  {'エントリー':>12}  {'SL':>12}  {'TP':>12}  {'数量':>8}")
    print("-" * 75)
    for t in open_trades:
        print(f"{t['id']:>4}  {t['pair']:<8}  {t['direction']:<6}  {t['entry_price']:>12.5f}  "
              f"{t['stop_loss']:>12.5f}  {t['take_profit']:>12.5f}  {t['units']:>8,}")


def show_history(trades: list):
    """全トレード履歴"""
    if not trades:
        print("\nトレード履歴はありません。")
        return

    print(f"\n=== トレード履歴 ({len(trades)}件) ===\n")
    print(f"{'ID':>4}  {'ペア':<8}  {'方向':<6}  {'Entry':>10}  {'Exit':>10}  {'損益(円)':>10}  {'状態':<6}  {'理由':<6}")
    print("-" * 80)
    for t in trades:
        exit_p = f"{t['exit_price']:.5f}" if t["exit_price"] else "-"
        pnl = f"{t['pnl_jpy']:+,.0f}" if t["pnl_jpy"] is not None else "-"
        reason = t.get("exit_reason", "-")
        print(f"{t['id']:>4}  {t['pair']:<8}  {t['direction']:<6}  "
              f"{t['entry_price']:>10.5f}  {exit_p:>10}  {pnl:>10}  {t['status']:<6}  {reason:<6}")


def show_report(trades: list):
    """パフォーマンスレポート"""
    closed = [t for t in trades if t["status"] == "CLOSED" and t["pnl_jpy"] is not None]

    if not closed:
        print("\nクローズ済みトレードがありません。レポートを生成できません。")
        return

    total_trades = len(closed)
    wins = [t for t in closed if t["pnl_jpy"] > 0]
    losses = [t for t in closed if t["pnl_jpy"] < 0]
    breakeven = [t for t in closed if t["pnl_jpy"] == 0]

    total_pnl = sum(t["pnl_jpy"] for t in closed)
    total_win = sum(t["pnl_jpy"] for t in wins) if wins else 0
    total_loss = abs(sum(t["pnl_jpy"] for t in losses)) if losses else 0
    pf = total_win / total_loss if total_loss > 0 else float("inf")

    avg_win = total_win / len(wins) if wins else 0
    avg_loss = total_loss / len(losses) if losses else 0

    # 最大連敗
    max_consecutive_loss = 0
    current_streak = 0
    for t in closed:
        if t["pnl_jpy"] < 0:
            current_streak += 1
            max_consecutive_loss = max(max_consecutive_loss, current_streak)
        else:
            current_streak = 0

    # 最大ドローダウン
    equity = 0
    peak = 0
    max_dd = 0
    for t in closed:
        equity += t["pnl_jpy"]
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)

    print("\n" + "=" * 50)
    print("  デモトレード パフォーマンスレポート")
    print("=" * 50)
    print(f"\n期間: {closed[0]['entry_time'][:10]} 〜 {closed[-1]['exit_time'][:10]}")
    print(f"\n{'トレード数:':<20} {total_trades}")
    print(f"{'勝ち:':<20} {len(wins)}  ({len(wins)/total_trades*100:.1f}%)")
    print(f"{'負け:':<20} {len(losses)}  ({len(losses)/total_trades*100:.1f}%)")
    print(f"{'引き分け:':<20} {len(breakeven)}")
    print(f"\n{'合計損益:':<20} {total_pnl:+,.0f} 円")
    print(f"{'平均勝ち:':<20} {avg_win:+,.0f} 円")
    print(f"{'平均負け:':<20} {-avg_loss:,.0f} 円")
    print(f"{'PF:':<20} {pf:.2f}")
    print(f"{'最大連敗:':<20} {max_consecutive_loss}")
    print(f"{'最大DD:':<20} {max_dd:,.0f} 円")

    # 通貨ペア別
    for pair in ["USD/JPY", "EUR/USD"]:
        pair_trades = [t for t in closed if t["pair"] == pair]
        if pair_trades:
            pair_wins = len([t for t in pair_trades if t["pnl_jpy"] > 0])
            pair_pnl = sum(t["pnl_jpy"] for t in pair_trades)
            print(f"\n  {pair}: {len(pair_trades)}トレード, "
                  f"勝率{pair_wins/len(pair_trades)*100:.1f}%, "
                  f"損益{pair_pnl:+,.0f}円")

    print()


def main():
    parser = argparse.ArgumentParser(description="Demo Trade Logger")
    parser.add_argument("command", choices=["add", "close", "list", "history", "report"],
                        help="add/close/list/history/report")
    parser.add_argument("trade_id", nargs="?", type=int, help="Trade ID (for close)")
    args = parser.parse_args()

    trades = load_trades()

    if args.command == "add":
        add_trade(trades)
    elif args.command == "close":
        if args.trade_id is None:
            print("Error: trade_id を指定してください。例: python trade_log.py close 1")
            return
        close_trade(trades, args.trade_id)
    elif args.command == "list":
        list_open(trades)
    elif args.command == "history":
        show_history(trades)
    elif args.command == "report":
        show_report(trades)


if __name__ == "__main__":
    main()
