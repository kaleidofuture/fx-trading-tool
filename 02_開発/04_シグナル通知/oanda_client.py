"""
OANDA API クライアント

デモ口座への接続、データ取得、注文執行を行う。

使い方:
    python oanda_client.py --test     # 接続テスト（口座情報を表示）
    python oanda_client.py --candles  # 直近のローソク足を取得
"""

import sys
import io
import json
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import oandapyV20
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.trades as trades
import oandapyV20.endpoints.instruments as instruments
from oandapyV20.contrib.requests import (
    MarketOrderRequest,
    TakeProfitDetails,
    StopLossDetails,
)

# Windows cp932 対策
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 設定ファイル
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.json"


def load_config() -> dict:
    """config.json を読み込む"""
    if not CONFIG_PATH.exists():
        print(f"Error: {CONFIG_PATH} not found.")
        print("Please create config.json with:")
        print(json.dumps({
            "oanda_token": "YOUR_API_TOKEN",
            "oanda_account_id": "xxx-xxx-xxxxxxx-xxx",
            "environment": "practice",
        }, indent=2))
        sys.exit(1)

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    required = ["oanda_token", "oanda_account_id"]
    for key in required:
        if key not in config or config[key].startswith("YOUR") or config[key].startswith("xxx"):
            print(f"Error: config.json の '{key}' を設定してください。")
            print("OANDA デモ口座のセットアップ手順:")
            print("  → 03_運用/01_デモトレード記録/OANDA_SETUP.md を参照")
            sys.exit(1)

    return config


class OandaClient:
    """OANDA API クライアント"""

    def __init__(self, token: str, account_id: str, environment: str = "practice"):
        self.account_id = account_id
        self.environment = environment
        self.api = oandapyV20.API(
            access_token=token,
            environment=environment,
        )

    def get_account_info(self) -> dict:
        """口座情報を取得"""
        r = accounts.AccountDetails(self.account_id)
        rv = self.api.request(r)
        return rv["account"]

    def get_candles(
        self,
        instrument: str = "USD_JPY",
        granularity: str = "H4",
        count: int = 200,
    ) -> pd.DataFrame:
        """ローソク足データを取得"""
        params = {
            "granularity": granularity,
            "count": count,
        }
        r = instruments.InstrumentsCandles(instrument=instrument, params=params)
        rv = self.api.request(r)

        rows = []
        for candle in rv["candles"]:
            if candle["complete"]:
                mid = candle["mid"]
                rows.append({
                    "Datetime": candle["time"],
                    "Open": float(mid["o"]),
                    "High": float(mid["h"]),
                    "Low": float(mid["l"]),
                    "Close": float(mid["c"]),
                    "Volume": int(candle["volume"]),
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["Datetime"] = pd.to_datetime(df["Datetime"])
            df.set_index("Datetime", inplace=True)
            df.index = df.index.tz_localize(None)

        return df

    def place_market_order(
        self,
        instrument: str,
        units: int,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> dict:
        """成行注文を発注"""
        # units: 正=買い、負=売り
        order_data = MarketOrderRequest(
            instrument=instrument,
            units=units,
            takeProfitOnFill=TakeProfitDetails(price=take_profit_price).data,
            stopLossOnFill=StopLossDetails(price=stop_loss_price).data,
        )

        r = orders.OrderCreate(self.account_id, data=order_data.data)
        rv = self.api.request(r)
        return rv

    def get_open_trades(self) -> list:
        """オープンポジション一覧を取得"""
        r = trades.OpenTrades(self.account_id)
        rv = self.api.request(r)
        return rv.get("trades", [])

    def close_trade(self, trade_id: str) -> dict:
        """ポジションを閉じる"""
        r = trades.TradeClose(self.account_id, tradeID=trade_id)
        rv = self.api.request(r)
        return rv

    def get_open_orders(self) -> list:
        """未約定の注文一覧"""
        r = orders.OrdersPending(self.account_id)
        rv = self.api.request(r)
        return rv.get("orders", [])


def test_connection(client: OandaClient):
    """接続テスト"""
    print("=== OANDA API Connection Test ===\n")

    # 口座情報
    info = client.get_account_info()
    print(f"Account ID:   {info['id']}")
    print(f"Currency:     {info['currency']}")
    print(f"Balance:      {float(info['balance']):,.0f} {info['currency']}")
    print(f"NAV:          {float(info['NAV']):,.0f} {info['currency']}")
    print(f"Unrealized PL: {float(info['unrealizedPL']):,.0f} {info['currency']}")
    print(f"Open Trades:  {info['openTradeCount']}")
    print(f"Environment:  {client.environment}")
    print()

    # ローソク足テスト
    print("=== Latest USD/JPY 4H Candles ===\n")
    df = client.get_candles("USD_JPY", "H4", count=5)
    if not df.empty:
        print(df.to_string())
    else:
        print("(No candle data - market may be closed)")

    print("\n=== Latest EUR/USD 4H Candles ===\n")
    df = client.get_candles("EUR_USD", "H4", count=5)
    if not df.empty:
        print(df.to_string())
    else:
        print("(No candle data - market may be closed)")

    print("\nConnection test PASSED.")


def show_candles(client: OandaClient):
    """直近のローソク足を表示"""
    for inst in ["USD_JPY", "EUR_USD"]:
        print(f"\n=== {inst} 4H (last 20 bars) ===")
        df = client.get_candles(inst, "H4", count=20)
        if not df.empty:
            print(df.to_string())
        else:
            print("(No data)")


def main():
    parser = argparse.ArgumentParser(description="OANDA API Client")
    parser.add_argument("--test", action="store_true", help="Run connection test")
    parser.add_argument("--candles", action="store_true", help="Show recent candles")
    args = parser.parse_args()

    config = load_config()
    client = OandaClient(
        token=config["oanda_token"],
        account_id=config["oanda_account_id"],
        environment=config.get("environment", "practice"),
    )

    if args.test:
        test_connection(client)
    elif args.candles:
        show_candles(client)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
