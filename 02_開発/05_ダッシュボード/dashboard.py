"""
FX Trading Dashboard

シグナル・相場・トレード記録を一画面で確認するダッシュボード。

起動:
    cd 02_開発/05_ダッシュボード
    streamlit run dashboard.py
"""

import sys
import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

# パス解決
BASE = Path(__file__).parent.parent
PROJECT_ROOT = BASE.parent
SIGNAL_HISTORY = BASE / "04_シグナル通知" / "signal_history.json"
TRADES_FILE = PROJECT_ROOT / "03_運用" / "01_デモトレード記録" / "trades.json"
REPORTS_DIR = BASE / "reports"

# デモトレーダー パス・検証設定
DEMO_TRIAL_MONTHS = 6  # 検証期間（月）
DEMO_DIR = PROJECT_ROOT / "03_運用" / "02_デモトレーダー"
DEMO_ACCOUNT_FILE = DEMO_DIR / "account.json"
DEMO_TRADES_FILE = DEMO_DIR / "trades.json"
DEMO_LOG_FILE = DEMO_DIR / "logs" / "demo_trader.log"

# 戦略パス追加
sys.path.insert(0, str(BASE / "02_バックテスト基盤"))
sys.path.insert(0, str(BASE / "03_戦略実装"))

from dual_momentum import DualMomentumStrategy

# ── ページ設定 ──────────────────────────────────
st.set_page_config(
    page_title="FX Trading Dashboard",
    page_icon="📊",
    layout="wide",
)

# ── 多言語辞書 ──────────────────────────────────
LANG = {
    "ja": {
        "title": "FX トレーディング ダッシュボード",
        "open_positions": "保有ポジション",
        "tab_chart": "チャート",
        "tab_signals": "シグナル履歴",
        "tab_trades": "トレード記録",
        "tab_performance": "パフォーマンス",
        "pair_select": "通貨ペア",
        "loading": "データ取得中...",
        "no_data": "データを取得できませんでした（市場が閉まっている可能性があります）",
        "latest_indicators": "最新インジケーター",
        "trend_status": "トレンド状況",
        "price_vs_ema": "価格 vs EMA(200)",
        "above": "上",
        "below": "下",
        "golden_cross": "ゴールデンクロス",
        "dead_cross": "デッドクロス",
        "rsi_zone": "RSI ゾーン",
        "rsi_ok": "正常",
        "rsi_extreme": "過熱",
        "no_signals": "シグナル履歴がありません。シグナルモニターを起動するとここに表示されます。",
        "signal_history": "シグナル履歴",
        "signals": "件",
        "new_trade": "+ 新規トレードを記録",
        "direction": "方向",
        "long": "LONG (買い)",
        "short": "SHORT (売り)",
        "units": "数量",
        "entry_price": "エントリー価格",
        "sl": "ストップロス (SL)",
        "tp": "テイクプロフィット (TP)",
        "memo": "メモ (任意)",
        "submit_trade": "記録する",
        "trade_recorded": "を記録しました",
        "enter_price": "価格を入力してください",
        "open_pos": "保有ポジション",
        "close_trade": "をクローズ",
        "exit_price": "決済価格",
        "exit_reason": "決済理由",
        "reason_tp": "TP (利確)",
        "reason_sl": "SL (損切り)",
        "reason_manual": "手動決済",
        "reason_other": "その他",
        "close_btn": "クローズ",
        "win": "勝ち",
        "lose": "負け",
        "enter_exit_price": "決済価格を入力してください",
        "no_open": "保有ポジションはありません",
        "closed_trades": "決済済みトレード",
        "no_trades": "トレード記録がありません。上の「+ 新規トレードを記録」から始めてください。",
        "no_closed": "決済済みトレードがありません。トレードを記録・クローズするとパフォーマンスが表示されます。",
        "backtest_reports": "バックテストレポート",
        "demo_performance": "デモトレード パフォーマンス",
        "total_trades": "トレード数",
        "win_rate": "勝率",
        "profit_factor": "プロフィットファクター",
        "total_pnl": "合計損益",
        "equity_curve": "エクイティカーブ",
        "by_pair": "通貨ペア別",
        "trades_label": "トレード",
        "backtest_ref": "バックテストレポート（参考）",
        "info": "情報",
        "strategy": "戦略",
        "timeframe": "時間足",
        "pairs": "通貨ペア",
        "trade_count": "トレード",
        "open_label": "保有",
        "closed_label": "決済済み",
        "refresh": "データ更新",
        "market_closed": "市場休場",
        "lang_label": "言語 / Language",
        "trade_num": "トレード数",
        "cum_pnl": "累計損益 (円)",
        "tab_demo": "デモトレーダー",
        "demo_account": "デモ口座状況",
        "demo_initial": "初期資金",
        "demo_balance": "残高（確定）",
        "demo_equity": "評価額（含み込み）",
        "demo_unrealized": "含み損益",
        "demo_return": "リターン",
        "demo_drawdown": "ドローダウン",
        "demo_peak": "最高残高",
        "demo_started": "開始日",
        "demo_open_pos": "デモ 保有ポジション",
        "demo_closed": "デモ 決済済みトレード",
        "demo_no_account": "デモ口座データがありません。demo_trader.py を実行してください。",
        "demo_exec_history": "スケジューラー実行履歴",
        "demo_no_log": "実行ログがありません。",
        "demo_time": "実行時刻",
        "demo_signals_found": "シグナル検出",
        "demo_details": "詳細",
        "demo_yes": "あり",
        "demo_no": "なし",
        "demo_period": "検証期間",
        "demo_end_date": "終了予定",
        "demo_remaining": "残り",
        "demo_days": "日",
        "demo_elapsed": "経過",
        "demo_progress": "進捗",
    },
    "en": {
        "title": "FX Trading Dashboard",
        "open_positions": "Open Positions",
        "tab_chart": "Charts",
        "tab_signals": "Signal History",
        "tab_trades": "Trade Log",
        "tab_performance": "Performance",
        "pair_select": "Currency Pair",
        "loading": "Loading data...",
        "no_data": "No data available (market may be closed)",
        "latest_indicators": "Latest Indicators",
        "trend_status": "Trend Status",
        "price_vs_ema": "Price vs EMA(200)",
        "above": "ABOVE",
        "below": "BELOW",
        "golden_cross": "Golden Cross",
        "dead_cross": "Dead Cross",
        "rsi_zone": "RSI Zone",
        "rsi_ok": "OK",
        "rsi_extreme": "Extreme",
        "no_signals": "No signal history. Start the signal monitor to see signals here.",
        "signal_history": "Signal History",
        "signals": "signals",
        "new_trade": "+ New Trade",
        "direction": "Direction",
        "long": "LONG (Buy)",
        "short": "SHORT (Sell)",
        "units": "Units",
        "entry_price": "Entry Price",
        "sl": "Stop Loss (SL)",
        "tp": "Take Profit (TP)",
        "memo": "Note (optional)",
        "submit_trade": "Record",
        "trade_recorded": "recorded",
        "enter_price": "Please enter prices",
        "open_pos": "Open Positions",
        "close_trade": "Close",
        "exit_price": "Exit Price",
        "exit_reason": "Exit Reason",
        "reason_tp": "TP (Take Profit)",
        "reason_sl": "SL (Stop Loss)",
        "reason_manual": "Manual",
        "reason_other": "Other",
        "close_btn": "Close",
        "win": "Win",
        "lose": "Loss",
        "enter_exit_price": "Please enter exit price",
        "no_open": "No open positions",
        "closed_trades": "Closed Trades",
        "no_trades": "No trades recorded. Use '+ New Trade' above to get started.",
        "no_closed": "No closed trades yet. Record and close trades to see performance.",
        "backtest_reports": "Backtest Reports",
        "demo_performance": "Demo Trading Performance",
        "total_trades": "Total Trades",
        "win_rate": "Win Rate",
        "profit_factor": "Profit Factor",
        "total_pnl": "Total PnL",
        "equity_curve": "Equity Curve",
        "by_pair": "By Pair",
        "trades_label": "trades",
        "backtest_ref": "Backtest Reports (Reference)",
        "info": "Info",
        "strategy": "Strategy",
        "timeframe": "Timeframe",
        "pairs": "Pairs",
        "trade_count": "Trades",
        "open_label": "Open",
        "closed_label": "Closed",
        "refresh": "Refresh Data",
        "market_closed": "Market closed",
        "lang_label": "Language / 言語",
        "trade_num": "Trades",
        "cum_pnl": "Cumulative PnL (JPY)",
        "tab_demo": "Demo Trader",
        "demo_account": "Demo Account",
        "demo_initial": "Initial Balance",
        "demo_balance": "Balance (Realized)",
        "demo_equity": "Equity (w/ Unrealized)",
        "demo_unrealized": "Unrealized PnL",
        "demo_return": "Return",
        "demo_drawdown": "Drawdown",
        "demo_peak": "Peak Balance",
        "demo_started": "Started",
        "demo_open_pos": "Demo Open Positions",
        "demo_closed": "Demo Closed Trades",
        "demo_no_account": "No demo account data. Run demo_trader.py first.",
        "demo_exec_history": "Scheduler Execution History",
        "demo_no_log": "No execution log found.",
        "demo_time": "Time",
        "demo_signals_found": "Signals Found",
        "demo_details": "Details",
        "demo_yes": "Yes",
        "demo_no": "No",
        "demo_period": "Trial Period",
        "demo_end_date": "End Date",
        "demo_remaining": "Remaining",
        "demo_days": "days",
        "demo_elapsed": "Elapsed",
        "demo_progress": "Progress",
    },
}

# ── 通貨ペア定義 ────────────────────────────────
PAIRS = {
    # メジャーペア
    "USD/JPY": {"ticker": "JPY=X", "pip_size": 0.01, "decimals": 3},
    "EUR/USD": {"ticker": "EURUSD=X", "pip_size": 0.0001, "decimals": 5},
    "GBP/USD": {"ticker": "GBPUSD=X", "pip_size": 0.0001, "decimals": 5},
    "AUD/USD": {"ticker": "AUDUSD=X", "pip_size": 0.0001, "decimals": 5},
    "USD/CHF": {"ticker": "CHF=X", "pip_size": 0.0001, "decimals": 5},
    # クロス円
    "EUR/JPY": {"ticker": "EURJPY=X", "pip_size": 0.01, "decimals": 3},
    "GBP/JPY": {"ticker": "GBPJPY=X", "pip_size": 0.01, "decimals": 3},
    "AUD/JPY": {"ticker": "AUDJPY=X", "pip_size": 0.01, "decimals": 3},
}


# ── データ取得 ──────────────────────────────────
@st.cache_data(ttl=300)
def fetch_data(ticker: str, period: str = "90d", interval: str = "1h") -> pd.DataFrame:
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval)
    if df.empty:
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("4h").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    strategy = DualMomentumStrategy()
    strategy.prepare(df)
    return strategy.data


def load_signal_history() -> list:
    if SIGNAL_HISTORY.exists():
        try:
            return json.loads(SIGNAL_HISTORY.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def load_trades() -> list:
    if TRADES_FILE.exists():
        try:
            return json.loads(TRADES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def save_trades(trades: list):
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRADES_FILE.write_text(json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8")


def next_trade_id(trades: list) -> int:
    if not trades:
        return 1
    return max(t["id"] for t in trades) + 1


def load_demo_account() -> dict | None:
    if DEMO_ACCOUNT_FILE.exists():
        try:
            return json.loads(DEMO_ACCOUNT_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return None


def load_demo_trades() -> list:
    if DEMO_TRADES_FILE.exists():
        try:
            return json.loads(DEMO_TRADES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def calc_unrealized_pnl(open_trades: list) -> tuple[float, dict]:
    """保有ポジションの含み損益を計算。(合計円建てP&L, {trade_id: {pnl_jpy, pnl_pips, current_price}})"""
    if not open_trades:
        return 0.0, {}

    total_pnl = 0.0
    details = {}
    usdjpy_rate = None  # 遅延取得（非JPYペアがあるときのみ）

    for t in open_trades:
        pair = t["pair"]
        pair_info = PAIRS.get(pair)
        if not pair_info:
            continue
        try:
            ticker = yf.Ticker(pair_info["ticker"])
            hist = ticker.history(period="1d", interval="1m")
            if hist.empty:
                hist = ticker.history(period="5d", interval="1h")
            if hist.empty:
                continue
            current = float(hist["Close"].iloc[-1])
        except Exception:
            continue

        pip_size = pair_info["pip_size"]
        entry = t["entry_price"]
        units = t["units"]
        direction = t["direction"]

        if direction == "LONG":
            pips = (current - entry) / pip_size
        else:
            pips = (entry - current) / pip_size

        # 円建てP&L計算
        if "JPY" in pair:
            pnl_jpy = pips * pip_size * units
        else:
            if usdjpy_rate is None:
                try:
                    usdjpy_ticker = yf.Ticker("JPY=X")
                    usdjpy_hist = usdjpy_ticker.history(period="1d", interval="1m")
                    if usdjpy_hist.empty:
                        usdjpy_hist = usdjpy_ticker.history(period="5d", interval="1h")
                    usdjpy_rate = float(usdjpy_hist["Close"].iloc[-1])
                except Exception:
                    usdjpy_rate = 148.0
            pnl_jpy = pips * pip_size * units * usdjpy_rate

        total_pnl += pnl_jpy
        details[t["id"]] = {
            "pnl_jpy": pnl_jpy,
            "pnl_pips": pips,
            "current_price": current,
        }
    return total_pnl, details


JST = timezone(timedelta(hours=9))


def _to_jst(time_str: str) -> str:
    """ログのローカル時刻文字列をJST表示に変換（ログ自体がJSTの場合そのまま）"""
    # demo_trader.log はローカル時刻（JST）で記録されている
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%m/%d %H:%M") + " JST"
    except ValueError:
        return time_str


def parse_demo_log() -> list:
    """デモトレーダーのログを解析して実行履歴を返す"""
    if not DEMO_LOG_FILE.exists():
        return []

    executions = []
    current_exec = None

    for line in DEMO_LOG_FILE.read_text(encoding="utf-8").splitlines():
        # 実行開始: "=== Signal Check @ ... ==="
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] === Signal Check @", line)
        if m:
            if current_exec:
                executions.append(current_exec)
            current_exec = {
                "time": m.group(1),
                "time_jst": _to_jst(m.group(1)),
                "signals": [],
                "pairs_checked": [],
                "opened": [],
            }
            continue

        if current_exec is None:
            continue

        # ペアごとの結果
        m_no = re.search(r"(\w+/\w+): No signal", line)
        if m_no:
            current_exec["pairs_checked"].append({"pair": m_no.group(1), "result": "No signal"})
            continue

        m_filtered = re.search(r"(\w+/\w+): Filtered \((.+?)\)", line)
        if m_filtered:
            current_exec["pairs_checked"].append({"pair": m_filtered.group(1), "result": f"Filtered ({m_filtered.group(2)})"})
            continue

        m_insuf = re.search(r"(\w+/\w+): Insufficient data", line)
        if m_insuf:
            current_exec["pairs_checked"].append({"pair": m_insuf.group(1), "result": "Insufficient data"})
            continue

        m_skip = re.search(r"(\w+/\w+): Skipped \((.+?)\)", line)
        if m_skip:
            current_exec["pairs_checked"].append({"pair": m_skip.group(1), "result": f"Skipped ({m_skip.group(2)})"})
            continue

        m_sig = re.search(r"(\w+/\w+): SIGNAL -> (\w+) @ ([\d.]+)", line)
        if m_sig:
            current_exec["signals"].append({"pair": m_sig.group(1), "direction": m_sig.group(2), "price": m_sig.group(3)})
            current_exec["pairs_checked"].append({"pair": m_sig.group(1), "result": f"SIGNAL {m_sig.group(2)}"})
            continue

        m_open = re.search(r"OPENED #(\d+): (\w+/\w+) (\w+) @ ([\d.]+)", line)
        if m_open:
            current_exec["opened"].append({"id": int(m_open.group(1)), "pair": m_open.group(2), "direction": m_open.group(3), "price": m_open.group(4)})

    if current_exec:
        executions.append(current_exec)

    return executions


def calc_pnl_jpy(pair: str, direction: str, entry_price: float, exit_price: float, units: int) -> float:
    diff = exit_price - entry_price
    if direction == "SHORT":
        diff = -diff
    # クロス円ペア（xxx/JPY）: 差額 × 数量 = 円建てPnL
    if pair.endswith("/JPY"):
        return round(diff * units, 0)
    # ドルストレート等: 差額 × 数量 × 概算レート(150円)
    else:
        return round(diff * units * 150, 0)


# ── チャート作成 ─────────────────────────────────
def create_price_chart(df: pd.DataFrame, pair_name: str, signals: list) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=[f"{pair_name} 4H", "RSI(14)", "ATR(14)"],
    )

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Price", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ), row=1, col=1)

    for col, color, name in [
        ("EMA_short", "#ff9800", "EMA(20)"),
        ("EMA_mid", "#2196f3", "EMA(50)"),
        ("EMA_long", "#9c27b0", "EMA(200)"),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col], line=dict(width=1, color=color), name=name,
            ), row=1, col=1)

    pair_signals = [s for s in signals if s["pair"] == pair_name]
    for sig in pair_signals:
        try:
            sig_time = pd.Timestamp(sig["time"])
            color = "#26a69a" if sig["signal"] == "LONG" else "#ef5350"
            symbol = "triangle-up" if sig["signal"] == "LONG" else "triangle-down"
            fig.add_trace(go.Scatter(
                x=[sig_time], y=[sig["price"]], mode="markers",
                marker=dict(size=14, color=color, symbol=symbol, line=dict(width=1, color="white")),
                name=f"{sig['signal']} @ {sig['price']}", showlegend=False,
            ), row=1, col=1)
        except (KeyError, ValueError):
            pass

    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"], line=dict(width=1, color="#ff9800"), name="RSI",
        ), row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)

    if "ATR" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ATR"], line=dict(width=1, color="#2196f3"),
            name="ATR", fill="tozeroy", fillcolor="rgba(33,150,243,0.1)",
        ), row=3, col=1)

    fig.update_layout(
        height=700, xaxis_rangeslider_visible=False, template="plotly_dark",
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        legend=dict(orientation="h", y=1.02, x=0), margin=dict(l=60, r=20, t=40, b=20),
    )
    return fig


def create_equity_chart(trades: list, L: dict) -> go.Figure | None:
    closed = [t for t in trades if t["status"] == "CLOSED" and t.get("pnl_jpy") is not None]
    if not closed:
        return None

    equity = [0]
    labels = ["Start"]
    for t in closed:
        equity.append(equity[-1] + t["pnl_jpy"])
        labels.append(f"#{t['id']} {t['pair']}")

    fig = go.Figure()
    colors = ["#26a69a" if e >= 0 else "#ef5350" for e in equity]
    fig.add_trace(go.Scatter(
        x=list(range(len(equity))), y=equity, mode="lines+markers",
        line=dict(width=2, color="#2196f3"), marker=dict(size=6, color=colors),
        text=labels, hovertemplate="%{text}<br>%{y:+,.0f} 円<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        height=300, template="plotly_dark", paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        xaxis_title=L["trade_num"], yaxis_title=L["cum_pnl"], margin=dict(l=60, r=20, t=20, b=40),
    )
    return fig


# ── メイン ───────────────────────────────────────
def main():
    # 言語選択（サイドバーの最上部に配置するためsession_stateで管理）
    if "lang" not in st.session_state:
        st.session_state.lang = "ja"

    with st.sidebar:
        lang_choice = st.radio(
            "🌐 言語 / Language",
            ["日本語", "English"],
            index=0 if st.session_state.lang == "ja" else 1,
            horizontal=True,
        )
        st.session_state.lang = "ja" if lang_choice == "日本語" else "en"

    L = LANG[st.session_state.lang]

    st.title(L["title"])

    # データ読み込み
    signals = load_signal_history()
    trades = load_trades()

    # ── ヘッダー ──
    st.markdown("---")
    pair_list = list(PAIRS.items())

    # 1行目: 4ペア
    row1 = pair_list[:4]
    cols1 = st.columns(4)
    for i, (pair_name, pair_info) in enumerate(row1):
        df_1h = fetch_data(pair_info["ticker"])
        if not df_1h.empty:
            latest = df_1h["Close"].iloc[-1]
            prev = df_1h["Close"].iloc[-2] if len(df_1h) > 1 else latest
            change = latest - prev
            change_pct = (change / prev) * 100
            arrow = "+" if change >= 0 else ""
            cols1[i].metric(
                label=pair_name,
                value=f"{latest:.{pair_info['decimals']}f}",
                delta=f"{arrow}{change:.{pair_info['decimals']}f} ({arrow}{change_pct:.2f}%)",
            )
        else:
            cols1[i].metric(label=pair_name, value="N/A", delta=L["market_closed"])

    # 2行目: 4ペア
    row2 = pair_list[4:]
    cols2 = st.columns(4)
    for i, (pair_name, pair_info) in enumerate(row2):
        df_1h = fetch_data(pair_info["ticker"])
        if not df_1h.empty:
            latest = df_1h["Close"].iloc[-1]
            prev = df_1h["Close"].iloc[-2] if len(df_1h) > 1 else latest
            change = latest - prev
            change_pct = (change / prev) * 100
            arrow = "+" if change >= 0 else ""
            cols2[i].metric(
                label=pair_name,
                value=f"{latest:.{pair_info['decimals']}f}",
                delta=f"{arrow}{change:.{pair_info['decimals']}f} ({arrow}{change_pct:.2f}%)",
            )
        else:
            cols2[i].metric(label=pair_name, value="N/A", delta=L["market_closed"])

    # ── タブ ──
    tab_chart, tab_demo = st.tabs([
        L["tab_chart"], L["tab_demo"]
    ])

    # ── チャートタブ ──
    with tab_chart:
        pair_select = st.selectbox(L["pair_select"], list(PAIRS.keys()))
        pair_info = PAIRS[pair_select]

        with st.spinner(L["loading"]):
            df_1h = fetch_data(pair_info["ticker"])

        if df_1h.empty:
            st.warning(L["no_data"])
        else:
            df_4h = resample_4h(df_1h)
            df_4h = compute_indicators(df_4h)

            fig = create_price_chart(df_4h, pair_select, signals)
            st.plotly_chart(fig, use_container_width=True)

            latest = df_4h.iloc[-1]
            st.markdown(f"#### {L['latest_indicators']}")
            ind_cols = st.columns(6)
            ind_cols[0].metric("Close", f"{latest['Close']:.{pair_info['decimals']}f}")
            ind_cols[1].metric("EMA(20)", f"{latest['EMA_short']:.{pair_info['decimals']}f}")
            ind_cols[2].metric("EMA(50)", f"{latest['EMA_mid']:.{pair_info['decimals']}f}")
            ind_cols[3].metric("EMA(200)", f"{latest['EMA_long']:.{pair_info['decimals']}f}")
            ind_cols[4].metric("RSI(14)", f"{latest['RSI']:.1f}")
            ind_cols[5].metric("ATR(14)", f"{latest['ATR']:.{pair_info['decimals']}f}")

            trend_long = latest["Close"] > latest["EMA_long"]
            ema_cross = latest["EMA_short"] > latest["EMA_mid"]
            rsi_ok = 30 < latest["RSI"] < 70

            st.markdown(f"#### {L['trend_status']}")
            status_cols = st.columns(3)
            status_cols[0].markdown(
                f"{L['price_vs_ema']}: **{L['above'] if trend_long else L['below']}** "
                f"{'🟢' if trend_long else '🔴'}"
            )
            status_cols[1].markdown(
                f"EMA(20) vs EMA(50): **{L['golden_cross'] if ema_cross else L['dead_cross']}** "
                f"{'🟢' if ema_cross else '🔴'}"
            )
            status_cols[2].markdown(
                f"{L['rsi_zone']}: **{latest['RSI']:.1f}** "
                f"{'🟢 ' + L['rsi_ok'] if rsi_ok else '🟡 ' + L['rsi_extreme']}"
            )

    # ── デモトレーダータブ ──
    with tab_demo:
        demo_account = load_demo_account()

        if demo_account is None:
            st.info(L["demo_no_account"])
        else:
            demo_trades_all = load_demo_trades()
            demo_open_all = [t for t in demo_trades_all if t["status"] == "OPEN"]
            demo_closed = [t for t in demo_trades_all if t["status"] == "CLOSED"]
            unrealized_total, unrealized_details = calc_unrealized_pnl(demo_open_all)

            initial = demo_account["initial_balance"]
            balance = demo_account["balance"]
            peak = demo_account["peak_balance"]
            equity = balance + unrealized_total
            ret = (equity - initial) / initial * 100
            dd = (peak - equity) / peak * 100 if peak > 0 and equity < peak else 0
            started = demo_account.get("created_at", "")[:10]

            # ── 口座概要 ──
            st.markdown(f"### {L['demo_account']}")
            ac_main = st.columns(4)
            ac_main[0].metric(L["demo_equity"], f"¥{equity:,.0f}")
            ac_main[1].metric(L["demo_unrealized"],
                              f"¥{unrealized_total:+,.0f}",
                              delta=f"{unrealized_total:+,.0f}" if unrealized_total != 0 else None)
            ac_main[2].metric(L["demo_return"], f"{ret:+.1f}%")
            ac_main[3].metric(L["demo_drawdown"], f"{dd:.1f}%")

            ac_sub = st.columns(4)
            ac_sub[0].metric(L["demo_balance"], f"¥{balance:,.0f}")
            ac_sub[1].metric(L["demo_peak"], f"¥{peak:,.0f}")
            ac_sub[2].metric(L["open_positions"], f"{len(demo_open_all)}/3")
            ac_sub[3].metric(L["trade_count"], f"{len(demo_closed)}")

            st.divider()

            # ── 保有ポジション ──
            st.markdown(f"### {L['demo_open_pos']} ({len(demo_open_all)}/3)")
            if demo_open_all:
                for t in demo_open_all:
                    color = "#26a69a" if t["direction"] == "LONG" else "#ef5350"
                    arrow = "▲" if t["direction"] == "LONG" else "▼"
                    entry_time = t.get("entry_time", "")[:19].replace("T", " ")
                    decimals = PAIRS.get(t["pair"], {}).get("decimals", 5)

                    uinfo = unrealized_details.get(t["id"])
                    if uinfo:
                        cur_price = uinfo["current_price"]
                        pnl_pips = uinfo["pnl_pips"]
                        pnl_jpy = uinfo["pnl_jpy"]
                        pnl_color = "#26a69a" if pnl_jpy >= 0 else "#ef5350"
                        pnl_line = (
                            f'<br><span style="color:{pnl_color}; font-size:1.1em;">'
                            f'<strong>含み損益: ¥{pnl_jpy:+,.0f}</strong>  '
                            f'({pnl_pips:+.1f} pips)</span>'
                            f'<br><small>現在値: {cur_price:.{decimals}f}  |  '
                            f'エントリー: {t["entry_price"]:.{decimals}f}</small>'
                        )
                    else:
                        pnl_line = '<br><small style="color:#888">含み損益: 取得中...</small>'

                    st.markdown(
                        f'<div style="padding:10px; margin:6px 0; border-left:4px solid {color}; '
                        f'background:#1a1a2e; border-radius:4px;">'
                        f'<strong>#{t["id"]} {arrow} {t["pair"]} {t["direction"]}</strong> '
                        f'@ {t["entry_price"]:.{decimals}f}'
                        f'{pnl_line}'
                        f'<br><small>SL: {t["stop_loss"]:.{decimals}f}  |  TP: {t["take_profit"]:.{decimals}f}  |  '
                        f'Units: {t["units"]:,}  |  RSI: {t.get("rsi", "-")}</small>'
                        f'<br><small style="color:#888">{entry_time}</small>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.info("保有ポジションはありません")

            st.divider()

            # ── 決済済みトレード ──
            if demo_closed:
                st.markdown(f"### {L['demo_closed']} ({len(demo_closed)})")
                wins = len([t for t in demo_closed if t.get("pnl_jpy", 0) > 0])
                total_pnl = sum(t.get("pnl_jpy", 0) for t in demo_closed)
                wr = wins / len(demo_closed) * 100

                mc = st.columns(4)
                mc[0].metric(L["total_trades"], len(demo_closed))
                mc[1].metric(L["win_rate"], f"{wr:.0f}%")
                mc[2].metric(L["total_pnl"], f"¥{total_pnl:+,.0f}")
                mc[3].metric("W/L", f"{wins}/{len(demo_closed) - wins}")

                df_dc = pd.DataFrame(demo_closed)
                display_cols = ["id", "pair", "direction", "entry_price", "exit_price",
                                "pnl_jpy", "pnl_pips", "exit_reason"]
                available_cols = [c for c in display_cols if c in df_dc.columns]
                st.dataframe(
                    df_dc[available_cols].sort_values("id", ascending=False).style.map(
                        lambda v: "color: #26a69a" if isinstance(v, (int, float)) and v > 0
                        else "color: #ef5350" if isinstance(v, (int, float)) and v < 0 else "",
                        subset=["pnl_jpy"] if "pnl_jpy" in available_cols else [],
                    ),
                    use_container_width=True, hide_index=True,
                )
                st.divider()

            # ── 検証期間 ──
            try:
                start_dt = datetime.fromisoformat(demo_account["created_at"]).replace(tzinfo=None)
                from dateutil.relativedelta import relativedelta
                end_dt = start_dt + relativedelta(months=DEMO_TRIAL_MONTHS)
            except Exception:
                start_dt = datetime(2026, 3, 9)
                end_dt = datetime(2026, 9, 9)
            now = datetime.now()
            total_days = (end_dt - start_dt).days
            elapsed_days = (now - start_dt).days
            remaining_days = max(0, (end_dt - now).days)
            progress = min(1.0, max(0.0, elapsed_days / total_days)) if total_days > 0 else 0

            period_unit = f"{DEMO_TRIAL_MONTHS} months" if st.session_state.lang == "en" else f"{DEMO_TRIAL_MONTHS}ヶ月"
            st.markdown(f"### {L['demo_period']} ({period_unit})")
            st.progress(progress, text=f"{L['demo_progress']}: {progress*100:.0f}%")

            pr_cols = st.columns(5)
            pr_cols[0].metric(L["demo_initial"], f"¥{initial:,.0f}")
            pr_cols[1].metric(L["demo_started"], started)
            pr_cols[2].metric(L["demo_end_date"], end_dt.strftime("%Y-%m-%d"))
            pr_cols[3].metric(L["demo_elapsed"], f"{elapsed_days} {L['demo_days']}")
            pr_cols[4].metric(L["demo_remaining"], f"{remaining_days} {L['demo_days']}")

            st.divider()

            # ── スケジューラー実行履歴 ──
            st.markdown(f"### {L['demo_exec_history']}")
            executions = parse_demo_log()
            if not executions:
                st.info(L["demo_no_log"])
            else:
                PAIR_SHORT = {
                    "USD/JPY": "UJ", "EUR/USD": "EU", "GBP/USD": "GU",
                    "AUD/USD": "AU", "USD/CHF": "UC", "EUR/JPY": "EJ",
                    "GBP/JPY": "GJ", "AUD/JPY": "AJ",
                }

                # 日付でグループ化（time_jst = "03/11 09:05 JST" 形式）
                from collections import OrderedDict
                date_groups = OrderedDict()
                for exec_info in reversed(executions):
                    time_display = exec_info.get("time_jst", exec_info["time"])
                    date_key = time_display.split(" ")[0]  # "03/11"
                    date_groups.setdefault(date_key, []).append(exec_info)

                for date_idx, (date_key, group) in enumerate(date_groups.items()):
                    signal_count = sum(1 for e in group if e["signals"])
                    label = f"{date_key}  ({len(group)} runs"
                    if signal_count:
                        label += f", {signal_count} signals"
                    label += ")"

                    with st.expander(label, expanded=(date_idx == 0)):
                        for exec_info in group:
                            has_signal = len(exec_info["signals"]) > 0
                            border_color = "#26a69a" if has_signal else "#555"
                            icon = "🟢" if has_signal else "⚪"
                            signal_text = L["demo_yes"] if has_signal else L["demo_no"]
                            time_display = exec_info.get("time_jst", exec_info["time"])
                            time_only = " ".join(time_display.split(" ")[1:])  # "09:05 JST"

                            if has_signal:
                                sig_detail = ", ".join(
                                    f"{s['pair']} {s['direction']} @{s['price']}"
                                    for s in exec_info["signals"]
                                )
                                signal_text += f" ({sig_detail})"

                            opened_html = ""
                            if exec_info["opened"]:
                                opened_items = ", ".join(
                                    f"#{o['id']} {o['pair']} {o['direction']}"
                                    for o in exec_info["opened"]
                                )
                                opened_html = (
                                    f'<br><span style="color:#26a69a;font-weight:bold;">'
                                    f'→ OPENED: {opened_items}</span>'
                                )

                            pair_icons = []
                            for pc in exec_info["pairs_checked"]:
                                short = PAIR_SHORT.get(pc["pair"], pc["pair"][:2])
                                if "SIGNAL" in pc["result"]:
                                    pair_icons.append(
                                        f'<span style="color:#fff;background:#26a69a;padding:1px 5px;'
                                        f'border-radius:3px;font-size:11px;font-weight:bold;">{short}</span>')
                                elif "Filtered" in pc["result"]:
                                    pair_icons.append(
                                        f'<span style="color:#fff;background:#ff9800;padding:1px 5px;'
                                        f'border-radius:3px;font-size:11px;">{short}</span>')
                                else:
                                    pair_icons.append(
                                        f'<span style="color:#888;background:#333;padding:1px 5px;'
                                        f'border-radius:3px;font-size:11px;">{short}</span>')
                            pair_dots = " ".join(pair_icons)

                            st.markdown(
                                f'<div style="padding:10px; margin:6px 0; border-left:4px solid {border_color}; '
                                f'background:#1a1a2e; border-radius:4px;">'
                                f'{icon} <strong>{time_only}</strong><br>'
                                f'{L["demo_signals_found"]}: {signal_text}'
                                f'{opened_html}'
                                f'<br><small style="margin-top:4px;display:inline-block;">{pair_dots}</small>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                            with st.expander(f'{L["demo_details"]} - {time_only}'):
                                for pc in exec_info["pairs_checked"]:
                                    if "SIGNAL" in pc["result"]:
                                        icon_p, color = "🟢", "#26a69a"
                                    elif "Filtered" in pc["result"]:
                                        icon_p, color = "🟡", "#ff9800"
                                    elif "Skipped" in pc["result"]:
                                        icon_p, color = "⏭️", "#888"
                                    else:
                                        icon_p, color = "⚪", "#888"
                                    st.markdown(
                                        f'{icon_p} <span style="color:{color};">'
                                        f'<strong>{pc["pair"]}</strong>: {pc["result"]}</span>',
                                        unsafe_allow_html=True,
                                    )

    # ── サイドバー（続き）──
    with st.sidebar:
        st.markdown("---")
        st.markdown(f"### {L['info']}")
        st.markdown(f"**{L['strategy']}**: Dual Momentum TF v2")
        st.markdown(f"**{L['timeframe']}**: 4H")
        st.markdown(f"**{L['pairs']}**: {len(PAIRS)} pairs")
        st.markdown("**Filters**: Whipsaw, RSI, EMA200")
        st.markdown("**Max positions**: 3")

        st.markdown("---")
        st.markdown(f"### {L['trade_count']}")
        dt = load_demo_trades()
        demo_open_count = len([t for t in dt if t["status"] == "OPEN"])
        demo_closed_count = len([t for t in dt if t["status"] == "CLOSED"])
        st.markdown(f"{L['open_label']}: **{demo_open_count}/3** / {L['closed_label']}: **{demo_closed_count}**")

        st.markdown("---")
        now_utc = datetime.now(timezone.utc)
        st.markdown(f"<small>UTC: {now_utc.strftime('%Y-%m-%d %H:%M')}</small>", unsafe_allow_html=True)

        if st.button(L["refresh"]):
            st.cache_data.clear()
            st.rerun()


if __name__ == "__main__":
    main()
