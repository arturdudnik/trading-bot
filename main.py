import time, ccxt, requests

BOT_TOKEN = '8330804880:AAG-FbkQ_e-pdme8iNwjzDnefnFHwK8dUXU'
API_KEY = 'mx0vglXTIUHauePQAu'
API_SECRET = '98976cc19e894e728a88f62af22c6b29'

CHAT_ID = '-1002926066972'

exchange = ccxt.mexc({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}, 
})
exchange.load_markets()

def send_tg(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

last_positions = set()

while True:
    try:
        positions = exchange.fetch_positions()
        open_now = {}
        for p in positions:
            contracts = float(p.get("contracts", 0) or 0)
            if contracts > 0:
                open_now[p["symbol"]] = p

        # detect new positions
        new_symbols = set(open_now.keys()) - last_positions
        for sym in new_symbols:
            pos = open_now[sym]
            msg = f"{pos['symbol']}\n{pos['side']}\nentry: {pos['entryPrice']}"
            send_tg(msg)

        last_positions = set(open_now.keys())
    except Exception as e:
        print("Error:", e)

    time.sleep(5)