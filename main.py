import os, time, math, requests, ccxt, logging, sys

# ---------- LOGGER ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ---------- ENV ----------
API_KEY   = os.getenv("API_KEY")
API_SECRET= os.getenv("API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")  # -100... or @public_channel

if not all([API_KEY, API_SECRET, BOT_TOKEN, CHAT_ID]):
    raise RuntimeError("Missing one or more required env vars: API_KEY, API_SECRET, BOT_TOKEN, CHAT_ID")

# ---------- EXCHANGE ----------
exchange = ccxt.mexc({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},  # futures
})
exchange.load_markets()

http = requests.Session()

def send_tg(msg: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = http.post(url, timeout=10, data={"chat_id": CHAT_ID, "text": msg})
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

def safe_float(v, default=None):
    try: return float(v)
    except Exception: return default

def almost_equal(a, b, tol=1e-8):
    if a is None or b is None:
        return a == b
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return str(a) == str(b)

# --- Fetch TP/SL via MEXC swap raw endpoints (plan/stop orders) ---
def fetch_tp_sl(symbol: str):
    """
    Try all places TP/SL may appear on MEXC swap:
      1) open orders (stopLossPrice/takeProfitPrice attached)
      2) stoporder list (combined TP/SL per position)
      3) planorder list (standalone triggers)
    Returns (tp, sl) as floats or None.
    """
    def safe_float(v):
        try: return float(v)
        except: return None

    tp, sl = None, None
    market = exchange.market(symbol)
    contract_sym = market.get("id", symbol)  # e.g. BTC_USDT

    # --- (1) Open orders with attached TP/SL ---
    try:
        # NOTE: this is the *futures* endpoint (not spot)
        # GET /api/v1/private/order/list/open_orders/{symbol}
        # It returns stopLossPrice and takeProfitPrice per order.
        res = exchange.contractPrivateGetOrderListOpenOrdersSymbol({
            "symbol": contract_sym,
            "page_num": 1,
            "page_size": 100,
        })
        items = res.get("data", []) if isinstance(res, dict) else res
        for it in items:
            tpp = safe_float(it.get("takeProfitPrice"))
            slp = safe_float(it.get("stopLossPrice"))
            if tpp is not None and tp is None:
                tp = tpp
            if slp is not None and sl is None:
                sl = slp
            if tp is not None and sl is not None:
                return tp, sl
    except Exception as e:
        logger.debug(f"open_orders fetch failed for {symbol}: {e}")

    # --- (2) Stop-Limit list (TP/SL attached to position) ---
    try:
        # GET /api/v1/private/stoporder/list/orders
        res = exchange.contractPrivateGetStoporderListOrders({
            "symbol": contract_sym,
            "is_finished": 0,    # only active
            "page_num": 1,
            "page_size": 100,
        })
        items = res.get("data", []) if isinstance(res, dict) else res
        for it in items:
            # These entries can contain BOTH prices in one row
            tpp = safe_float(it.get("takeProfitPrice"))
            slp = safe_float(it.get("stopLossPrice"))
            if tpp is not None and tp is None:
                tp = tpp
            if slp is not None and sl is None:
                sl = slp
        if tp is not None or sl is not None:
            return tp, sl
    except Exception as e:
        logger.debug(f"stoporder list fetch failed for {symbol}: {e}")

    # --- (3) Trigger/plan list (standalone TP or SL) ---
    try:
        # GET /api/v1/private/planorder/list/orders
        res = exchange.contractPrivateGetPlanorderListOrders({
            "symbol": contract_sym,
            "states": "1",       # 1 = untriggered
            "page_num": 1,
            "page_size": 100,
        })
        items = res.get("data", []) if isinstance(res, dict) else res
        for it in items:
            order_type = str(it.get("orderType", "")).upper()
            trig_price = safe_float(it.get("triggerPrice"))
            if trig_price is None:
                continue
            # Heuristic: MEXC labels include TAKE_PROFIT / STOP_LOSS in orderType
            if "TAKE_PROFIT" in order_type and tp is None:
                tp = trig_price
            elif "STOP_LOSS" in order_type and sl is None:
                sl = trig_price
        return tp, sl
    except Exception as e:
        logger.debug(f"planorder list fetch failed for {symbol}: {e}")

    return tp, sl


# ---------- STATE ----------
# {symbol: {"side":..., "entry":..., "tp":..., "sl":...}}
last_positions = {}
sleep_base = 5

# ---------- LOOP ----------
while True:
    try:
        positions = exchange.fetch_positions()
        snapshot = {}

        for p in positions or []:
            contracts = safe_float(p.get("contracts"), 0.0)
            if contracts <= 0:
                continue
            sym   = p.get("symbol")
            if not sym:
                continue
            side  = p.get("side", "unknown")
            entry = p.get("entryPrice", "n/a")

            # First try any TP/SL on the position itself (some ccxt versions expose these)
            tp_pos = safe_float(p.get("takeProfitPrice") or p.get("takeProfit") or p.get("tp"))
            sl_pos = safe_float(p.get("stopLossPrice")  or p.get("stopLoss")   or p.get("sl"))

            # Then query raw plan/stop lists (most reliable on MEXC swaps)
            tp, sl = tp_pos, sl_pos
            if tp is None or sl is None:
                tp, sl = fetch_tp_sl(sym)
                tp = tp if tp is not None else t2
                sl = sl if sl is not None else s2

            current = {"side": side, "entry": entry, "tp": tp, "sl": sl}
            prev = last_positions.get(sym)

            if prev is None:
                # New position
                msg = f"{sym}\n{side}\nentry: {entry}"
                if tp is not None: msg += f"\nTP: {tp}"
                if sl is not None: msg += f"\nSL: {sl}"
                send_tg(msg)
            else:
                # TP/SL added or changed
                tp_changed = not almost_equal(tp, prev.get("tp"))
                sl_changed = not almost_equal(sl, prev.get("sl"))
                if (prev.get("tp") is None and tp is not None) or \
                   (prev.get("sl") is None and sl is not None) or \
                   tp_changed or sl_changed:
                    if tp_changed or sl_changed:
                        msg = f"🔄 Update {sym}\n{side}\nentry: {entry}"
                        if tp is not None: msg += f"\nTP: {tp}"
                        if sl is not None: msg += f"\nSL: {sl}"
                        send_tg(msg)

            snapshot[sym] = current

        # Closed positions
        closed = set(last_positions) - set(snapshot)
        for sym in closed:
            send_tg(f"✅ Position closed: {sym}")

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
