import os
import time
import math
import requests
import ccxt
import logging
import sys

# ========== LOGGER ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ========== ENV VARS ==========
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not all([API_KEY, API_SECRET, BOT_TOKEN, CHAT_ID]):
    raise RuntimeError("Missing one or more required env vars: API_KEY, API_SECRET, BOT_TOKEN, CHAT_ID")

# ========== EXCHANGE ==========
exchange = ccxt.mexc({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},  # futures
})
exchange.load_markets()

http = requests.Session()

def send_tg(msg: str) -> None:
    """Send Telegram message"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = http.post(url, timeout=10, data={"chat_id": CHAT_ID, "text": msg})
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

# ========== STATE ==========
last_positions = {}  # {symbol: {"side":..., "entry":..., "tp":..., "sl":...}}
sleep_base = 5

# ========== LOOP ==========
while True:
    try:
        positions = exchange.fetch_positions()
        snapshot = {}

        for p in positions or []:
            logger.info(f"Position data: {p}")
            contracts = safe_float(p.get("contracts"))
            if contracts <= 0:
                continue

            sym = p.get("symbol")
            side = p.get("side", "unknown")
            entry = p.get("entryPrice", "n/a")

            # --- fetch TP/SL orders ---
            tp, sl = None, None
            try:
                orders = exchange.fetch_open_orders(sym)
                for o in orders:
                    otype = (o.get("type") or "").lower()
                    if "take_profit" in otype:
                        tp = o.get("stopPrice") or o.get("price")
                    elif "stop_loss" in otype:
                        sl = o.get("stopPrice") or o.get("price")
            except Exception as e:
                logger.warning(f"Could not fetch TP/SL for {sym}: {e}")

            current = {"side": side, "entry": entry, "tp": tp, "sl": sl}
            prev = last_positions.get(sym)

            # --- new position ---
            if prev is None:
                msg = f"{sym}\n{side}\nentry: {entry}"
                if tp:
                    msg += f"\nTP: {tp}"
                if sl:
                    msg += f"\nSL: {sl}"
                send_tg(msg)
                logger.info(f"New position detected: {msg}")

            # --- existing position updated ---
            else:
                if tp != prev.get("tp") or sl != prev.get("sl"):
                    msg = f"🔄 Update {sym}\n{side}\nentry: {entry}"
                    if tp:
                        msg += f"\nTP: {tp}"
                    if sl:
                        msg += f"\nSL: {sl}"
                    send_tg(msg)
                    logger.info(f"Position updated: {msg}")

            snapshot[sym] = current

        # --- detect closed positions ---
        closed = set(last_positions) - set(snapshot)
        for sym in closed:
            send_tg(f"✅ Position closed: {sym}")
            logger.info(f"Position closed: {sym}")

        last_positions = snapshot
        sleep_base = 5
        time.sleep(sleep_base)

    except KeyboardInterrupt:
        logger.info("Exiting.")
        break
    except Exception as e:
        logger.error(f"Error: {e}")
        sleep_base = min(60, max(5, int(math.ceil(sleep_base * 1.5))))
        time.sleep(sleep_base)

#-1002926066972