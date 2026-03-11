"""
Dual Momentum Trend Following 戦略

学術的根拠:
- Jegadeesh & Titman (1993): モメンタム効果
- Asness, Moskowitz & Pedersen (2013): 通貨市場でのモメンタム

エントリー条件（ロング）:
  1. 価格 > EMA(200)  （長期上昇トレンド）
  2. EMA(20) > EMA(50) （中期トレンド転換）
  3. 30 < RSI(14) < 70  （極端な過熱でない）

エントリー条件（ショート）:
  1. 価格 < EMA(200)
  2. EMA(20) < EMA(50)
  3. 30 < RSI(14) < 70

損切り: ATR(14) × 2.0
利確:   ATR(14) × 3.0  （RR = 1:1.5）

品質フィルター（バックテスト分析に基づく改善 v2）:
  - ウィップソー除外: 直前20本以内に別のシグナルあり → 見送り
  - RSI極端除外: SHORT + RSI < 35 → 底値売りを回避
  - EMA200近接除外: EMA200との距離 < 0.3% → トレンド不明確で見送り
"""

from typing import Optional

import pandas as pd
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "02_バックテスト基盤"))
from backtest_engine import Side


class DualMomentumStrategy:
    """Dual Momentum Trend Following"""

    def __init__(
        self,
        ema_short: int = 20,
        ema_mid: int = 50,
        ema_long: int = 200,
        rsi_period: int = 14,
        atr_period: int = 14,
        rsi_lower: float = 30,
        rsi_upper: float = 70,
    ):
        self.ema_short = ema_short
        self.ema_mid = ema_mid
        self.ema_long = ema_long
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.rsi_lower = rsi_lower
        self.rsi_upper = rsi_upper

        self.data: Optional[pd.DataFrame] = None

    def prepare(self, data: pd.DataFrame):
        """指標を計算してデータに追加"""
        self.data = data.copy()
        close = self.data["Close"]

        # EMA
        self.data["EMA_short"] = close.ewm(span=self.ema_short, adjust=False).mean()
        self.data["EMA_mid"] = close.ewm(span=self.ema_mid, adjust=False).mean()
        self.data["EMA_long"] = close.ewm(span=self.ema_long, adjust=False).mean()

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        self.data["RSI"] = 100 - (100 / (1 + rs))

        # ATR
        high = self.data["High"]
        low = self.data["Low"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        self.data["ATR"] = tr.rolling(window=self.atr_period).mean()

        # クロスオーバー検出用（前回の状態）
        self.data["EMA_cross"] = (
            self.data["EMA_short"] > self.data["EMA_mid"]
        ).astype(int)
        self.data["EMA_cross_prev"] = self.data["EMA_cross"].shift(1)

    def signal(self, idx: int) -> Optional[Side]:
        """idx番目のバーでのシグナルを返す"""
        if self.data is None or idx < self.ema_long:
            return None

        row = self.data.iloc[idx]

        # NaN チェック
        required = ["EMA_short", "EMA_mid", "EMA_long", "RSI", "ATR", "EMA_cross_prev"]
        if any(pd.isna(row[col]) for col in required):
            return None

        price = row["Close"]
        ema_short = row["EMA_short"]
        ema_mid = row["EMA_mid"]
        ema_long = row["EMA_long"]
        rsi = row["RSI"]
        cross = row["EMA_cross"]
        cross_prev = row["EMA_cross_prev"]

        # RSIフィルター
        if rsi <= self.rsi_lower or rsi >= self.rsi_upper:
            return None

        # ロングシグナル
        if (
            price > ema_long           # 長期上昇トレンド
            and ema_short > ema_mid    # 短期 > 中期
            and cross == 1             # 現在ゴールデンクロス状態
            and cross_prev == 0        # 前回はデッドクロス → 今クロスした
        ):
            return Side.LONG

        # ショートシグナル
        if (
            price < ema_long           # 長期下降トレンド
            and ema_short < ema_mid    # 短期 < 中期
            and cross == 0             # 現在デッドクロス状態
            and cross_prev == 1        # 前回はゴールデンクロス → 今クロスした
        ):
            return Side.SHORT

        return None

    def filtered_signal(
        self,
        idx: int,
        whipsaw_lookback: int = 20,
        ema200_min_dist: float = 0.3,
        rsi_short_min: float = 35,
    ) -> tuple[Optional[Side], list[str]]:
        """品質フィルター付きシグナル判定

        Returns:
            (signal, skip_reasons): シグナルとスキップ理由のリスト。
            skip_reasons が空ならエントリー可。
        """
        sig = self.signal(idx)
        if sig is None:
            return None, []

        row = self.data.iloc[idx]
        skip_reasons = []

        # Filter 1: ウィップソー（直前にシグナルが出ている = 方向感のない相場）
        for j in range(max(self.ema_long, idx - whipsaw_lookback), idx):
            if self.signal(j) is not None:
                skip_reasons.append("whipsaw")
                break

        # Filter 2: EMA200近接（トレンド不明確）
        ema200_dist_pct = abs(row["Close"] - row["EMA_long"]) / row["EMA_long"] * 100
        if ema200_dist_pct < ema200_min_dist:
            skip_reasons.append("ema200_close")

        # Filter 3: RSI極端でのSHORT（底値売りリスク）
        if sig == Side.SHORT and row["RSI"] < rsi_short_min:
            skip_reasons.append("rsi_extreme")

        if skip_reasons:
            return None, skip_reasons

        return sig, []

    def get_atr(self, idx: int) -> Optional[float]:
        """ATR値を取得"""
        if self.data is None:
            return None
        val = self.data.iloc[idx]["ATR"]
        return None if pd.isna(val) else float(val)
