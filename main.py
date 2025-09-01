import os
import time
import math
import requests
import ccxt

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not all([API_KEY, API_SECRET, BOT_TOKEN, CHAT_ID]):
    raise RuntimeError("Missing one or more required env vars: API_KEY, API_SECRET, BOT_TOKEN, CHAT_ID")

exchange = ccxt.mexc({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})
exchange.load_markets()

http = requests.Session()

def send_tg(msg: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = http.post(url, timeout=10, data={"chat_id": CHAT_ID, "text": msg})
        r.raise_for_status()
    except Exception as e:
        print(f"Telegram send error: {e}")

def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

last_symbols = set()
sleep_base = 5 

while True:
    try:
        positions = exchange.fetch_positions()
        open_now = {}
        for p in positions or []:
            contracts = safe_float(p.get("contracts"))
            if contracts > 0:
                sym = p.get("symbol")
                if sym:
                    open_now[sym] = p

        new_symbols = set(open_now) - last_symbols
        for sym in new_symbols:
            pos = open_now[sym]
            side = pos.get("side", "unknown")
            entry = pos.get("entryPrice", "n/a")
            msg = f"{sym}\n{side}\nentry: {entry}"
            send_tg(msg)

        last_symbols = set(open_now)
        time.sleep(sleep_base)
    except KeyboardInterrupt:
        print("Exiting.")
        break
    except Exception as e:
        print("Error:", e)
        sleep_base = min(60, max(5, int(math.ceil(sleep_base * 1.5))))
        time.sleep(sleep_base)
