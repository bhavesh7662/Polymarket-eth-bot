import os
import time
import requests
from datetime import datetime
from math import fabs

# ---------- CONFIGURE THESE VALUES ----------

# Polymarket CLOB host (may change; check docs)
CLOB_HOST = "https://clob.polymarket.com"  # default host

# Your wallet details (put real ones here or use environment variables)
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "YOUR_PRIVATE_KEY_HERE")
FUNDER = os.getenv("FUNDER", "YOUR_FUNDER_ADDRESS_HERE")

# Polygon chain id (check Polymarket docs; often 137 or 8453 for Base etc.)
CHAIN_ID = int(os.getenv("CHAIN_ID", "137"))

# Ethereum "UP" token id for the chosen market (you must look this up)
UP_TOKEN_ID = "REPLACE_WITH_ETH_UP_TOKEN_ID"

# Basic trading parameters
MAX_HOURLY_SPEND = 20.0      # USDC max per hour
ORDER_SIZE = 5.0             # USDC per trade
EDGE_THRESHOLD = 10.0        # minimum edge (in percentage points) to trade
LOOP_INTERVAL_SEC = 20       # run every 20 seconds

# --------------------------------------------

# Polymarket CLOB client imports
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY


# ---------- HELPER FUNCTIONS ----------

def create_client():
    """
    Create an authenticated Polymarket CLOB client.
    """
    if PRIVATE_KEY.startswith("YOUR_") or FUNDER.startswith("YOUR_"):
        raise RuntimeError("Please set PRIVATE_KEY and FUNDER (wallet) before running this bot.")

    client = ClobClient(
        CLOB_HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=1,    # check docs if you use a different wallet/signature type
        funder=FUNDER,
    )
    # Create or derive API credentials and attach them
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def get_eth_recent_change():
    """
    Very simple example using Binance ETH/USDT 1m candles.
    Computes % change over the last 60 minutes.
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "ETHUSDT", "interval": "1m", "limit": 60}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    if len(data) < 2:
        return 0.0

    open_1h_ago = float(data[0][1])
    last_close = float(data[-1][4])

    change_pct = (last_close - open_1h_ago) / open_1h_ago * 100.0
    return change_pct


def estimate_up_probability():
    """
    Toy model: maps last-hour price change to a probability (5–95%).
    Replace with your own strategy later.
    """
    change_pct = get_eth_recent_change()
    base = 50.0 + change_pct * 2.0   # crude mapping
    est = max(5.0, min(95.0, base))
    return est


def get_polymarket_price(client, token_id):
    """
    Get approximate Polymarket price (probability) for the given token in %.
    """
    price = client.get_price(token_id, side="BUY")  # price in dollars between 0 and 1
    if price is None:
        return None
    return float(price) * 100.0


def place_up_market_order(client, amount):
    """
    Place a Fill-Or-Kill market buy order on the UP token for 'amount' USDC.
    """
    if amount <= 0:
        return

    mo = MarketOrderArgs(
        token_id=UP_TOKEN_ID,
        amount=amount,
        side=BUY,
        order_type=OrderType.FOK,   # FOK market-style order
    )
    signed = client.create_market_order(mo)
    resp = client.post_order(signed, OrderType.FOK)
    print("Order response:", resp)
    return resp


# ---------- MAIN LOOP ----------

def run_one_hour_session():
    """
    Runs the bot for exactly 1 hour from start.
    Every LOOP_INTERVAL_SEC, it:
      - Computes its own ETH-up probability
      - Reads Polymarket UP price
      - If est - market > EDGE_THRESHOLD, buys UP (limited by MAX_HOURLY_SPEND)
    """
    client = create_client()
    start_ts = time.time()
    end_ts = start_ts + 60 * 60  # 1 hour
    spent = 0.0

    print("Starting 1-hour ETH UP bot session at", datetime.utcfromtimestamp(start_ts), "UTC")

    while time.time() < end_ts:
        try:
            est_prob = estimate_up_probability()
            market_prob = get_polymarket_price(client, UP_TOKEN_ID)

            if market_prob is None:
                print("No market price for token; skipping this loop.")
            else:
                edge = est_prob - market_prob
                print(
                    f"[{datetime.utcnow().isoformat()}] "
                    f"Est={est_prob:.1f}%, Market={market_prob:.1f}%, Edge={edge:.1f}%"
                )

                if edge > EDGE_THRESHOLD and (spent + ORDER_SIZE) <= MAX_HOURLY_SPEND:
                    print("Edge detected, placing UP buy order for", ORDER_SIZE, "USDC")
                    place_up_market_order(client, ORDER_SIZE)
                    spent += ORDER_SIZE
                else:
                    print("No trade this round (edge too small or budget used).")

        except Exception as e:
            print("Error in loop:", repr(e))

        time.sleep(LOOP_INTERVAL_SEC)

    print("Finished 1-hour session. Total spent:", spent, "USDC")


if __name__ == "__main__":
    run_one_hour_session()
