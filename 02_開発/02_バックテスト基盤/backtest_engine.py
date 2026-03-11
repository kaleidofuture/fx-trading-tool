"""
バックテストエンジン

シンプルなイベント駆動型バックテストエンジン。
外部ライブラリに依存せず、ロジックが透明であることを重視。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import pandas as pd
import numpy as np


class Side(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Trade:
    """1つのトレード記録"""
    entry_time: pd.Timestamp
    exit_time: Optional[pd.Timestamp]
    side: Side
    entry_price: float
    exit_price: Optional[float]
    size: float  # 通貨単位数
    stop_loss: float
    take_profit: float
    pnl: Optional[float] = None
    pnl_pips: Optional[float] = None
    exit_reason: Optional[str] = None  # "tp", "sl", "trailing", "signal"

    @property
    def is_open(self) -> bool:
        return self.exit_price is None


@dataclass
class RiskManager:
    """リスク管理エンジン"""
    risk_per_trade: float = 0.01      # 口座の1%
    max_total_risk: float = 0.05      # 全ポジ合計5%
    max_drawdown_stop: float = 0.20   # 20%で停止
    min_risk_reward: float = 1.5      # 最低RR比

    def calculate_position_size(
        self, balance: float, stop_loss_pips: float, pip_value: float
    ) -> float:
        """ポジションサイズを計算"""
        risk_amount = balance * self.risk_per_trade
        if stop_loss_pips <= 0:
            return 0.0
        size = risk_amount / (stop_loss_pips * pip_value)
        return round(size, 0)

    def can_open_trade(self, drawdown: float, open_positions: int) -> bool:
        """トレード可能か判定"""
        if drawdown >= self.max_drawdown_stop:
            return False
        if open_positions >= 3:  # 同時ポジション上限
            return False
        return True


@dataclass
class BacktestResult:
    """バックテスト結果"""
    trades: list[Trade]
    equity_curve: pd.Series
    initial_balance: float
    final_balance: float

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl and t.pnl > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl and t.pnl <= 0)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades if t.pnl is not None)

    @property
    def total_return_pct(self) -> float:
        return (self.final_balance - self.initial_balance) / self.initial_balance * 100

    @property
    def max_drawdown(self) -> float:
        """最大ドローダウン（%）"""
        peak = self.equity_curve.expanding().max()
        dd = (self.equity_curve - peak) / peak
        return abs(dd.min()) * 100

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.trades if t.pnl and t.pnl > 0]
        return np.mean(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.trades if t.pnl and t.pnl <= 0]
        return np.mean(losses) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl and t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl and t.pnl <= 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def risk_reward_ratio(self) -> float:
        if self.avg_loss == 0:
            return 0.0
        return abs(self.avg_win / self.avg_loss)

    def summary(self) -> str:
        """結果サマリ文字列"""
        lines = [
            "=" * 50,
            "BACKTEST RESULT",
            "=" * 50,
            f"期間: {self.equity_curve.index[0]} ~ {self.equity_curve.index[-1]}",
            f"初期資金: ¥{self.initial_balance:,.0f}",
            f"最終資金: ¥{self.final_balance:,.0f}",
            f"総損益: ¥{self.total_pnl:,.0f} ({self.total_return_pct:+.1f}%)",
            "-" * 50,
            f"総トレード数: {self.total_trades}",
            f"勝ちトレード: {self.winning_trades}",
            f"負けトレード: {self.losing_trades}",
            f"勝率: {self.win_rate:.1%}",
            f"平均利益: ¥{self.avg_win:,.0f}",
            f"平均損失: ¥{self.avg_loss:,.0f}",
            f"リスクリワード比: {self.risk_reward_ratio:.2f}",
            f"プロフィットファクター: {self.profit_factor:.2f}",
            f"最大ドローダウン: {self.max_drawdown:.1f}%",
            "=" * 50,
        ]
        return "\n".join(lines)


class BacktestEngine:
    """
    バックテストエンジン本体

    使い方:
        engine = BacktestEngine(df, initial_balance=1_000_000)
        engine.run(strategy)
        result = engine.get_result()
        print(result.summary())
    """

    def __init__(
        self,
        data: pd.DataFrame,
        initial_balance: float = 1_000_000,
        spread_pips: float = 0.3,
        pip_size: float = 0.01,  # USD/JPY: 0.01, EUR/USD: 0.0001
        pip_value_per_unit: float = 1.0,  # 1通貨あたり1pipの円価値
    ):
        self.data = data.copy()
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.spread_pips = spread_pips
        self.pip_size = pip_size
        self.pip_value_per_unit = pip_value_per_unit
        self.spread = spread_pips * pip_size

        self.risk_manager = RiskManager()
        self.trades: list[Trade] = []
        self.open_trade: Optional[Trade] = None
        self.equity_history: list[tuple[pd.Timestamp, float]] = []
        self.peak_balance = initial_balance

    def run(self, strategy) -> "BacktestResult":
        """戦略を実行"""
        # 戦略にデータを渡してシグナル計算
        strategy.prepare(self.data)

        for i in range(len(self.data)):
            row = self.data.iloc[i]
            time = self.data.index[i]

            # オープンポジションの管理
            if self.open_trade is not None:
                self._manage_position(row, time)

            # 新規エントリー判定
            if self.open_trade is None:
                signal = strategy.signal(i)
                if signal is not None:
                    self._open_position(signal, row, time, strategy, i)

            # エクイティ記録
            equity = self._calculate_equity(row)
            self.equity_history.append((time, equity))

        # 未決済ポジションを強制クローズ
        if self.open_trade is not None:
            last_row = self.data.iloc[-1]
            last_time = self.data.index[-1]
            self._close_position(last_row["Close"], last_time, "end_of_data")

        return self.get_result()

    def _price_diff_to_jpy(self, price_diff: float, size: float) -> float:
        """価格差 × サイズを円建て損益に変換"""
        pips = price_diff / self.pip_size
        return pips * self.pip_value_per_unit * size

    def _calculate_equity(self, row: pd.Series) -> float:
        """現在のエクイティ（含み損益込み）を計算"""
        if self.open_trade is None:
            return self.balance

        if self.open_trade.side == Side.LONG:
            diff = row["Close"] - self.open_trade.entry_price
        else:
            diff = self.open_trade.entry_price - row["Close"]

        return self.balance + self._price_diff_to_jpy(diff, self.open_trade.size)

    def _open_position(self, side: Side, row: pd.Series, time, strategy, idx: int):
        """ポジションを開く"""
        # ドローダウンチェック
        dd = (self.peak_balance - self.balance) / self.peak_balance if self.peak_balance > 0 else 0
        if not self.risk_manager.can_open_trade(dd, 1 if self.open_trade else 0):
            return

        price = row["Close"]
        # スプレッドコスト
        if side == Side.LONG:
            entry_price = price + self.spread / 2
        else:
            entry_price = price - self.spread / 2

        # ATRベースの損切り・利確
        atr = strategy.get_atr(idx)
        if atr is None or atr <= 0:
            return

        sl_distance = atr * 2.0
        tp_distance = atr * 3.0

        if side == Side.LONG:
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        # ポジションサイズ計算
        sl_pips = sl_distance / self.pip_size
        size = self.risk_manager.calculate_position_size(
            self.balance, sl_pips, self.pip_value_per_unit
        )
        if size <= 0:
            return

        self.open_trade = Trade(
            entry_time=time,
            exit_time=None,
            side=side,
            entry_price=entry_price,
            exit_price=None,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def _manage_position(self, row: pd.Series, time):
        """オープンポジションの損切り/利確 + トレーリングストップ"""
        trade = self.open_trade
        high = row["High"]
        low = row["Low"]
        close = row["Close"]

        if trade.side == Side.LONG:
            # 損切りチェック（安値がSLに到達）
            if low <= trade.stop_loss:
                self._close_position(trade.stop_loss, time, "sl")
                return
            # 利確チェック（高値がTPに到達）
            if high >= trade.take_profit:
                self._close_position(trade.take_profit, time, "tp")
                return
            # トレーリングストップ: 含み益がATR×2.0超えたらSLを引き上げ
            atr_at_entry = (trade.take_profit - trade.entry_price) / 3.0  # ATRを逆算
            profit = close - trade.entry_price
            if profit > atr_at_entry * 2.0:
                # SLをエントリー + (含み益 - ATR) に引き上げ
                new_sl = trade.entry_price + profit - atr_at_entry
                if new_sl > trade.stop_loss:
                    trade.stop_loss = new_sl
        else:  # SHORT
            # 損切りチェック（高値がSLに到達）
            if high >= trade.stop_loss:
                self._close_position(trade.stop_loss, time, "sl")
                return
            # 利確チェック（安値がTPに到達）
            if low <= trade.take_profit:
                self._close_position(trade.take_profit, time, "tp")
                return
            # トレーリングストップ
            atr_at_entry = (trade.entry_price - trade.take_profit) / 3.0
            profit = trade.entry_price - close
            if profit > atr_at_entry * 2.0:
                new_sl = trade.entry_price - profit + atr_at_entry
                if new_sl < trade.stop_loss:
                    trade.stop_loss = new_sl

    def _close_position(self, exit_price: float, time, reason: str):
        """ポジションを閉じる"""
        trade = self.open_trade
        if trade is None:
            return

        trade.exit_price = exit_price
        trade.exit_time = time
        trade.exit_reason = reason

        # 損益計算（円建て統一）
        if trade.side == Side.LONG:
            price_diff = exit_price - trade.entry_price
        else:
            price_diff = trade.entry_price - exit_price

        pnl_pips = price_diff / self.pip_size
        pnl = self._price_diff_to_jpy(price_diff, trade.size)

        trade.pnl = round(pnl, 0)
        trade.pnl_pips = round(pnl_pips, 1)

        self.balance += pnl
        self.peak_balance = max(self.peak_balance, self.balance)
        self.trades.append(trade)
        self.open_trade = None

    def get_result(self) -> BacktestResult:
        """結果を取得"""
        eq_index = [t for t, _ in self.equity_history]
        eq_values = [v for _, v in self.equity_history]
        equity_curve = pd.Series(eq_values, index=eq_index, name="Equity")

        return BacktestResult(
            trades=self.trades,
            equity_curve=equity_curve,
            initial_balance=self.initial_balance,
            final_balance=self.balance,
        )
