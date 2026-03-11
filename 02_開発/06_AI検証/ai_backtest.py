"""
AI強化バックテスト比較

ルールベースのみ vs AI判断付きの成績を比較する。
Claude Code CLI (claude -p) を使ってAI判断を取得。

使い方:
    python ai_backtest.py                    # 全ステップ実行
    python ai_backtest.py --extract-only     # シグナル抽出のみ（AI呼び出しなし）
    python ai_backtest.py --skip-ai          # 既存AI判断を使って比較のみ
    python ai_backtest.py --pair USDJPY      # 特定ペアのみ
"""

import sys
import io
import json
import argparse
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from time import sleep

import pandas as pd
import numpy as np

# Windows cp932 対策
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# パス解決
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE / "02_バックテスト基盤"))
sys.path.insert(0, str(BASE / "03_戦略実装"))

from backtest_engine import BacktestEngine, Side
from dual_momentum import DualMomentumStrategy

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# 定数
DATA_DIR = BASE / "01_データ取得" / "data"
RESULT_DIR = Path(__file__).parent / "results"
RESULT_DIR.mkdir(exist_ok=True)

# 検証対象ペア（CSVデータがあるもの）
PAIRS = [
    {
        "name": "USD/JPY",
        "csv": "USDJPY_1h.csv",
        "pip_size": 0.01,
        "pip_value": 0.01,
        "spread": 0.3,
        "price_format": ".3f",
    },
    {
        "name": "EUR/USD",
        "csv": "EURUSD_1h.csv",
        "pip_size": 0.0001,
        "pip_value": 0.015,
        "spread": 0.2,
        "price_format": ".5f",
    },
]


def load_4h_data(csv_filename: str) -> pd.DataFrame:
    """1時間足CSVを4時間足にリサンプリング"""
    csv_path = DATA_DIR / csv_filename
    df = pd.read_csv(csv_path, index_col="Datetime")
    df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
    df_4h = df.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()
    return df_4h


def extract_signals(pair: dict) -> list[dict]:
    """ルールベースのフィルター済みシグナルを全て抽出"""
    df = load_4h_data(pair["csv"])
    strategy = DualMomentumStrategy()
    strategy.prepare(df)
    data = strategy.data
    fmt = pair["price_format"]

    signals = []
    for i in range(strategy.ema_long, len(data)):
        sig, skip_reasons = strategy.filtered_signal(i)
        if sig is None and not skip_reasons:
            continue  # シグナルなし

        row = data.iloc[i]
        atr = strategy.get_atr(i)

        # 直近20本の価格推移サマリ
        lookback = min(20, i)
        recent = data.iloc[i - lookback : i + 1]
        price_changes = []
        for j in range(max(1, len(recent) - 5), len(recent)):
            r = recent.iloc[j]
            prev = recent.iloc[j - 1]
            chg = (r["Close"] - prev["Close"]) / prev["Close"] * 100
            price_changes.append(f"{chg:+.2f}%")

        # トレンド判定
        ema_short = row["EMA_short"]
        ema_mid = row["EMA_mid"]
        ema_long = row["EMA_long"]
        if ema_short > ema_mid > ema_long:
            trend = "Strong Uptrend"
        elif ema_short < ema_mid < ema_long:
            trend = "Strong Downtrend"
        elif row["Close"] > ema_long:
            trend = "Weak Uptrend"
        else:
            trend = "Weak Downtrend"

        # ボラティリティ（ATRの相対値）
        atr_pct = atr / row["Close"] * 100 if atr else 0

        # 直近の高値安値
        recent_high = recent["High"].max()
        recent_low = recent["Low"].min()
        price_range_pct = (recent_high - recent_low) / recent_low * 100

        signal_data = {
            "pair": pair["name"],
            "index": i,
            "time": str(data.index[i]),
            "signal": strategy.signal(i).value if strategy.signal(i) else None,
            "filtered": len(skip_reasons) > 0,
            "filter_reasons": skip_reasons,
            "price": round(float(row["Close"]), 5),
            "ema_short": round(float(ema_short), 5),
            "ema_mid": round(float(ema_mid), 5),
            "ema_long": round(float(ema_long), 5),
            "rsi": round(float(row["RSI"]), 1),
            "atr": round(float(atr), 5) if atr else None,
            "atr_pct": round(atr_pct, 3),
            "trend": trend,
            "recent_changes": price_changes,
            "recent_high": round(float(recent_high), 5),
            "recent_low": round(float(recent_low), 5),
            "price_range_pct": round(price_range_pct, 2),
        }
        signals.append(signal_data)

    return signals


def build_ai_prompt(sig: dict, pair: dict) -> str:
    """AI判断用のプロンプトを構築"""
    direction = "BUY (LONG)" if sig["signal"] == "LONG" else "SELL (SHORT)"
    fmt = pair["price_format"]

    price = sig['price']
    ema_s = sig['ema_short']
    ema_m = sig['ema_mid']
    ema_l = sig['ema_long']
    atr = sig['atr']
    rh = sig['recent_high']
    rl = sig['recent_low']

    prompt = f"""Analyze this FX trade signal and respond with ONLY one line.

{sig['pair']} {direction} at {price} on {sig['time']}
EMA20={ema_s} EMA50={ema_m} EMA200={ema_l}
RSI={sig['rsi']} ATR={atr} ({sig['atr_pct']:.2f}%)
Trend: {sig['trend']}
Recent 5-bar changes: {', '.join(sig['recent_changes'])}
Range: {rl} - {rh} ({sig['price_range_pct']:.1f}%)

Strategy: Dual Momentum (4H), SL=ATRx2, TP=ATRx3 (RR 1:1.5)

Should we take this trade? Consider trend strength, momentum quality, and volatility.

YOUR RESPONSE MUST BE EXACTLY ONE LINE in this format:
GO|8|Strong trend with clean crossover
or
SKIP|7|Choppy action suggests false breakout"""

    return prompt


def call_claude_cli(prompt: str, timeout: int = 120) -> str | None:
    """Claude Code CLI を呼び出してAI判断を取得"""
    import tempfile, os
    try:
        # プロンプトを一時ファイルに書き出し（Windows の引数長制限回避）
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            # ファイルからプロンプトを読み込んでパイプで渡す
            claude_cmd = "claude.cmd" if sys.platform == "win32" else "claude"
            with open(prompt_file, "r", encoding="utf-8") as pf:
                result = subprocess.run(
                    [
                        claude_cmd, "-p", "-",
                        "--model", "sonnet",
                        "--output-format", "text",
                    ],
                    stdin=pf,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    shell=(sys.platform == "win32"),
                )
        finally:
            os.unlink(prompt_file)

        if result.returncode != 0:
            logger.error(f"Claude CLI error: {result.stderr[:200]}")
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error("Claude CLI timeout")
        return None
    except FileNotFoundError:
        logger.error("Claude CLI not found. Is it installed?")
        return None


def parse_ai_response(response: str) -> dict:
    """AI応答をパース"""
    if not response:
        return {"decision": "ERROR", "confidence": 0, "reason": "No response"}

    # 最後の行からGO/SKIPを探す
    for line in reversed(response.strip().split("\n")):
        line = line.strip()
        if line.startswith("GO|") or line.startswith("SKIP|"):
            parts = line.split("|", 2)
            if len(parts) >= 3:
                return {
                    "decision": parts[0].strip(),
                    "confidence": int(parts[1].strip()) if parts[1].strip().isdigit() else 5,
                    "reason": parts[2].strip(),
                }
            elif len(parts) == 2:
                return {
                    "decision": parts[0].strip(),
                    "confidence": int(parts[1].strip()) if parts[1].strip().isdigit() else 5,
                    "reason": "",
                }

    # フォールバック: GOまたはSKIPが含まれているか
    upper = response.upper()
    if "SKIP" in upper:
        return {"decision": "SKIP", "confidence": 5, "reason": response[:50]}
    elif "GO" in upper:
        return {"decision": "GO", "confidence": 5, "reason": response[:50]}

    return {"decision": "ERROR", "confidence": 0, "reason": f"Unparseable: {response[:50]}"}


def run_ai_judgments(signals: list[dict], pair: dict, save_path: Path) -> list[dict]:
    """全シグナルに対してAI判断を取得（中断再開対応）"""
    # 既存結果の読み込み（再開用）
    existing = {}
    if save_path.exists():
        try:
            existing_data = json.loads(save_path.read_text(encoding="utf-8"))
            existing = {s["time"]: s for s in existing_data}
            logger.info(f"Loaded {len(existing)} existing AI judgments")
        except json.JSONDecodeError:
            pass

    # フィルター済み（ルールベースで既にスキップ）は除外
    active_signals = [s for s in signals if not s["filtered"]]
    logger.info(f"Active signals to judge: {len(active_signals)} (filtered out: {len(signals) - len(active_signals)})")

    results = []
    for i, sig in enumerate(active_signals):
        # 既に判断済みならスキップ
        if sig["time"] in existing:
            results.append(existing[sig["time"]])
            logger.info(f"  [{i+1}/{len(active_signals)}] {sig['time']} - CACHED: {existing[sig['time']].get('ai_decision', 'N/A')}")
            continue

        logger.info(f"  [{i+1}/{len(active_signals)}] {sig['time']} {sig['signal']} @ {sig['price']} ...")

        prompt = build_ai_prompt(sig, pair)
        response = call_claude_cli(prompt)
        parsed = parse_ai_response(response)

        sig_with_ai = {**sig, **{
            "ai_decision": parsed["decision"],
            "ai_confidence": parsed["confidence"],
            "ai_reason": parsed["reason"],
            "ai_raw_response": response[:200] if response else None,
        }}
        results.append(sig_with_ai)

        logger.info(f"           -> {parsed['decision']} (conf={parsed['confidence']}) {parsed['reason']}")

        # 中間保存（中断対応）
        save_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

        # レート制限対策: 少し間隔を空ける
        sleep(2)

    return results


class AIFilteredStrategy:
    """AI判断を反映した戦略ラッパー"""

    def __init__(self, base_strategy: DualMomentumStrategy, allowed_indices: set[int]):
        self.base = base_strategy
        self.allowed_indices = allowed_indices
        self.data = None

    def prepare(self, data: pd.DataFrame):
        self.base.prepare(data)
        self.data = self.base.data

    def signal(self, idx: int):
        if idx not in self.allowed_indices:
            return None
        sig, skip = self.base.filtered_signal(idx)
        return sig

    def get_atr(self, idx: int):
        return self.base.get_atr(idx)


class RuleBasedFilteredStrategy:
    """ルールベースフィルター済み戦略"""

    def __init__(self, base_strategy: DualMomentumStrategy):
        self.base = base_strategy
        self.data = None

    def prepare(self, data: pd.DataFrame):
        self.base.prepare(data)
        self.data = self.base.data

    def signal(self, idx: int):
        sig, skip = self.base.filtered_signal(idx)
        return sig

    def get_atr(self, idx: int):
        return self.base.get_atr(idx)


def run_comparison(pair: dict, ai_judgments: list[dict]):
    """ルールベース vs AI強化 のバックテスト比較"""
    df = load_4h_data(pair["csv"])

    logger.info(f"\n{'='*60}")
    logger.info(f"  {pair['name']} - COMPARISON: Rule-Based vs AI-Enhanced")
    logger.info(f"{'='*60}")

    # --- 1. ルールベースのみ（フィルター付き） ---
    strategy_rb = RuleBasedFilteredStrategy(DualMomentumStrategy())
    engine_rb = BacktestEngine(
        data=df,
        initial_balance=500_000,
        spread_pips=pair["spread"],
        pip_size=pair["pip_size"],
        pip_value_per_unit=pair["pip_value"],
    )
    result_rb = engine_rb.run(strategy_rb)

    # --- 2. AI強化版 ---
    # AIがGOと判断したシグナルのインデックスのみ許可
    go_indices = set()
    skip_indices = set()
    for j in ai_judgments:
        if j.get("ai_decision") == "GO":
            go_indices.add(j["index"])
        elif j.get("ai_decision") == "SKIP":
            skip_indices.add(j["index"])

    strategy_ai = AIFilteredStrategy(DualMomentumStrategy(), go_indices)
    engine_ai = BacktestEngine(
        data=df,
        initial_balance=500_000,
        spread_pips=pair["spread"],
        pip_size=pair["pip_size"],
        pip_value_per_unit=pair["pip_value"],
    )
    result_ai = engine_ai.run(strategy_ai)

    # --- 3. 比較レポート ---
    report = []
    report.append(f"\n{'='*70}")
    report.append(f"  {pair['name']} COMPARISON REPORT")
    report.append(f"{'='*70}")
    report.append(f"  初期資金: ¥500,000")
    report.append(f"  データ: {len(df)} bars ({df.index[0]} ~ {df.index[-1]})")
    report.append(f"")
    report.append(f"  AI判断サマリ: GO={len(go_indices)}, SKIP={len(skip_indices)}")
    report.append(f"")

    header = f"  {'':20s} {'Rule-Based':>15s} {'AI-Enhanced':>15s} {'Diff':>10s}"
    report.append(header)
    report.append(f"  {'-'*60}")

    metrics = [
        ("Total Trades", result_rb.total_trades, result_ai.total_trades, "d"),
        ("Win Rate", result_rb.win_rate * 100, result_ai.win_rate * 100, ".1f"),
        ("Total PnL (JPY)", result_rb.total_pnl, result_ai.total_pnl, ",.0f"),
        ("Return %", result_rb.total_return_pct, result_ai.total_return_pct, ".1f"),
        ("Profit Factor", result_rb.profit_factor, result_ai.profit_factor, ".2f"),
        ("Max Drawdown %", result_rb.max_drawdown, result_ai.max_drawdown, ".1f"),
        ("Avg Win (JPY)", result_rb.avg_win, result_ai.avg_win, ",.0f"),
        ("Avg Loss (JPY)", result_rb.avg_loss, result_ai.avg_loss, ",.0f"),
        ("RR Ratio", result_rb.risk_reward_ratio, result_ai.risk_reward_ratio, ".2f"),
    ]

    for name, rb_val, ai_val, fmt in metrics:
        diff = ai_val - rb_val
        if fmt == "d":
            report.append(f"  {name:20s} {rb_val:>15d} {ai_val:>15d} {diff:>+10d}")
        elif fmt == ",.0f":
            report.append(f"  {name:20s} {rb_val:>15,.0f} {ai_val:>15,.0f} {diff:>+10,.0f}")
        else:
            rb_str = f"{rb_val:{fmt}}"
            ai_str = f"{ai_val:{fmt}}"
            diff_str = f"{diff:+{fmt}}"
            report.append(f"  {name:20s} {rb_str:>15s} {ai_str:>15s} {diff_str:>10s}")

    report.append(f"  {'-'*60}")

    # AI SKIPしたトレードの結末分析
    report.append(f"\n  --- AI SKIP Analysis ---")
    skipped_trades = []
    for j in ai_judgments:
        if j.get("ai_decision") != "SKIP":
            continue
        # ルールベース結果からこのインデックスのトレードを探す
        for t in result_rb.trades:
            t_time = str(t.entry_time)
            if j["time"] in t_time or t_time in j["time"]:
                skipped_trades.append((j, t))
                break

    if skipped_trades:
        wins = sum(1 for _, t in skipped_trades if t.pnl and t.pnl > 0)
        losses = sum(1 for _, t in skipped_trades if t.pnl and t.pnl <= 0)
        total_pnl = sum(t.pnl for _, t in skipped_trades if t.pnl)
        report.append(f"  AIがSKIPしたトレード: {len(skipped_trades)}件")
        report.append(f"    うち勝ち: {wins}件, 負け: {losses}件")
        report.append(f"    合計損益: ¥{total_pnl:+,.0f}")
        if total_pnl < 0:
            report.append(f"    -> AIが正しく負けトレードを回避!")
        else:
            report.append(f"    -> AIが利益機会を逃した...")

        report.append(f"\n  SKIP詳細:")
        for j, t in skipped_trades:
            pnl_str = f"¥{t.pnl:+,.0f}" if t.pnl else "N/A"
            report.append(f"    {j['time']} {j['signal']:5s} -> {pnl_str} [{t.exit_reason}] AI: {j.get('ai_reason', '')}")
    else:
        report.append(f"  (SKIPトレードとルールベーストレードの照合なし)")

    report_text = "\n".join(report)
    logger.info(report_text)

    # レポート保存
    report_path = RESULT_DIR / f"{pair['name'].replace('/', '')}_comparison.txt"
    report_path.write_text(report_text, encoding="utf-8")
    logger.info(f"\n  Report saved: {report_path}")

    return {
        "pair": pair["name"],
        "rule_based": {
            "trades": result_rb.total_trades,
            "win_rate": round(result_rb.win_rate * 100, 1),
            "pnl": round(result_rb.total_pnl),
            "pf": round(result_rb.profit_factor, 2),
            "max_dd": round(result_rb.max_drawdown, 1),
        },
        "ai_enhanced": {
            "trades": result_ai.total_trades,
            "win_rate": round(result_ai.win_rate * 100, 1),
            "pnl": round(result_ai.total_pnl),
            "pf": round(result_ai.profit_factor, 2),
            "max_dd": round(result_ai.max_drawdown, 1),
        },
        "ai_stats": {
            "go": len(go_indices),
            "skip": len(skip_indices),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="AI-Enhanced Backtest Comparison")
    parser.add_argument("--extract-only", action="store_true", help="シグナル抽出のみ")
    parser.add_argument("--skip-ai", action="store_true", help="既存AI判断で比較のみ")
    parser.add_argument("--pair", type=str, help="特定ペアのみ (e.g. USDJPY)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("AI-Enhanced Backtest Comparison")
    logger.info("Rule-Based (filtered) vs AI-Augmented")
    logger.info("=" * 60)

    pairs = PAIRS
    if args.pair:
        pairs = [p for p in PAIRS if args.pair.upper() in p["name"].replace("/", "")]
        if not pairs:
            logger.error(f"Pair not found: {args.pair}")
            return

    all_results = []

    for pair in pairs:
        pair_tag = pair["name"].replace("/", "")
        signals_path = RESULT_DIR / f"{pair_tag}_signals.json"
        ai_path = RESULT_DIR / f"{pair_tag}_ai_judgments.json"

        # Step 1: シグナル抽出
        logger.info(f"\n--- {pair['name']}: Extracting signals ---")
        signals = extract_signals(pair)
        active = [s for s in signals if not s["filtered"]]
        filtered = [s for s in signals if s["filtered"]]
        logger.info(f"  Total signals: {len(signals)} (active: {len(active)}, filtered: {len(filtered)})")
        signals_path.write_text(json.dumps(signals, indent=2, ensure_ascii=False), encoding="utf-8")

        if args.extract_only:
            continue

        # Step 2: AI判断取得
        if not args.skip_ai:
            logger.info(f"\n--- {pair['name']}: Getting AI judgments ---")
            ai_judgments = run_ai_judgments(signals, pair, ai_path)
        else:
            if not ai_path.exists():
                logger.error(f"  No AI judgments found at {ai_path}")
                continue
            ai_judgments = json.loads(ai_path.read_text(encoding="utf-8"))
            logger.info(f"  Loaded {len(ai_judgments)} AI judgments from cache")

        # Step 3: 比較バックテスト
        logger.info(f"\n--- {pair['name']}: Running comparison ---")
        result = run_comparison(pair, ai_judgments)
        all_results.append(result)

    # 全体サマリ
    if all_results:
        logger.info(f"\n{'='*70}")
        logger.info("  OVERALL SUMMARY")
        logger.info(f"{'='*70}")
        total_rb_pnl = sum(r["rule_based"]["pnl"] for r in all_results)
        total_ai_pnl = sum(r["ai_enhanced"]["pnl"] for r in all_results)
        logger.info(f"  Rule-Based Total PnL:  ¥{total_rb_pnl:+,.0f}")
        logger.info(f"  AI-Enhanced Total PnL: ¥{total_ai_pnl:+,.0f}")
        logger.info(f"  Difference:            ¥{total_ai_pnl - total_rb_pnl:+,.0f}")

        if total_ai_pnl > total_rb_pnl:
            logger.info(f"\n  -> AI強化版がルールベースを上回りました!")
        elif total_ai_pnl < total_rb_pnl:
            logger.info(f"\n  -> ルールベースの方が良い結果でした（AI判断はコスト）")
        else:
            logger.info(f"\n  -> 差なし")

        # 全体結果保存
        summary_path = RESULT_DIR / "comparison_summary.json"
        summary_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"\n  Summary saved: {summary_path}")


if __name__ == "__main__":
    main()
