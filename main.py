import os
import json
import time
import logging
from datetime import datetime

import pytz
import schedule
import requests
import pandas as pd
import yfinance as yf
import ta

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIG — from Railway environment variables
# ============================================================

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SYMBOL           = os.getenv('SYMBOL', 'RELIANCE.NS')
RISK_PER_TRADE   = int(os.getenv('RISK_PER_TRADE', '10000'))
STATE_FILE       = 'state.json'

IST = pytz.timezone('Asia/Kolkata')

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Telegram message sent successfully")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

# ============================================================
# STATE — persisted in state.json (Railway volume or local)
# ============================================================

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        'position': 0,
        'buy_price': 0.0,
        'stop_loss': 0.0,
        'position_added': False
    }

def save_state(state: dict):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    logger.info(f"State saved: {state}")

# ============================================================
# DATA & INDICATORS
# ============================================================

def get_data(symbol: str) -> pd.DataFrame:
    logger.info(f"Downloading data for {symbol}...")
    data = yf.download(symbol, start='2015-01-01', auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    # Only drop rows where Close is missing
    data = data[data['Close'].notna()]
    logger.info(f"Downloaded {len(data)} daily candles")
    return data

def compute_indicators(data: pd.DataFrame):
    # --- Weekly ---
    weekly = data.resample('W-FRI').agg({
        'Open': 'first', 'High': 'max',
        'Low': 'min',    'Close': 'last',
        'Volume': 'sum'
    })
    # Drop only weeks with no Close (missing week entirely)
    weekly = weekly[weekly['Close'].notna()]
    weekly['RSI']  = ta.momentum.RSIIndicator(weekly['Close'], window=14).rsi()
    weekly['MA20'] = weekly['Close'].rolling(20).mean()

    # --- Monthly ---
    monthly = data.resample('ME').agg({
        'Open': 'first', 'High': 'max',
        'Low': 'min',    'Close': 'last',
        'Volume': 'sum'
    })
    monthly = monthly[monthly['Close'].notna()]
    monthly['RSI']  = ta.momentum.RSIIndicator(monthly['Close'], window=14).rsi()
    monthly['MA20'] = monthly['Close'].rolling(20).mean()

    logger.info(f"Weekly rows: {len(weekly)} | Monthly rows: {len(monthly)}")
    return weekly, monthly

# ============================================================
# SIGNAL ENGINE
# ============================================================

def check_signals():
    logger.info(f"=== Weekly Signal Check — {SYMBOL} ===")
    now_ist = datetime.now(IST).strftime('%d %b %Y %H:%M IST')

    try:
        data            = get_data(SYMBOL)
        weekly, monthly = compute_indicators(data)
        state           = load_state()

        # Guard: need at least 2 weekly rows and 1 monthly row
        if len(weekly) < 2:
            raise ValueError(f"Not enough weekly data: only {len(weekly)} rows. Try again later.")
        if len(monthly) < 1:
            raise ValueError(f"Not enough monthly data: only {len(monthly)} rows.")

        # Latest candles
        w_curr  = weekly.iloc[-1]
        w_prev  = weekly.iloc[-2]
        m_curr  = monthly.iloc[-1]

        current_price   = float(w_curr['Close'])
        weekly_ma20     = float(w_curr['MA20']) if pd.notna(w_curr['MA20']) else 0.0
        weekly_rsi      = float(w_curr['RSI'])  if pd.notna(w_curr['RSI'])  else 0.0
        prev_weekly_rsi = float(w_prev['RSI'])  if pd.notna(w_prev['RSI'])  else 0.0
        monthly_rsi     = float(m_curr['RSI'])  if pd.notna(m_curr['RSI'])  else 0.0
        monthly_ma20    = float(m_curr['MA20']) if pd.notna(m_curr['MA20']) else 0.0
        monthly_close   = float(m_curr['Close'])

        # ---- Conditions ----
        monthly_ok   = monthly_rsi > 60 and monthly_close > monthly_ma20
        rsi_crossover = prev_weekly_rsi < 60 and weekly_rsi > 60

        logger.info(
            f"Price={current_price:.2f} | WeeklyRSI={weekly_rsi:.1f} (prev={prev_weekly_rsi:.1f}) | "
            f"WeeklyMA20={weekly_ma20:.2f} | MonthlyRSI={monthly_rsi:.1f} | "
            f"MonthlyOK={monthly_ok} | RSICross={rsi_crossover}"
        )

        # ==================================================
        # CASE 1 — No open position: look for fresh entry
        # ==================================================
        if state['position'] == 0:

            if monthly_ok and rsi_crossover:
                risk_per_share = current_price - weekly_ma20

                if risk_per_share <= 0:
                    logger.warning("RSI crossover found but risk_per_share <= 0 — skipping")
                    send_telegram(
                        f"⚠️ <b>Signal Found but Skipped — {SYMBOL}</b>\n"
                        f"Entry price is at or below MA20. No valid risk."
                    )
                    return

                qty = int(RISK_PER_TRADE / risk_per_share)

                state = {
                    'position': qty,
                    'buy_price': current_price,
                    'stop_loss': weekly_ma20,
                    'position_added': False
                }
                save_state(state)

                send_telegram(
                    f"🟢 <b>BUY SIGNAL — {SYMBOL}</b>\n"
                    f"📅 {now_ist}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Entry Price   : ₹{current_price:.2f}\n"
                    f"Stop Loss     : ₹{weekly_ma20:.2f}  (Weekly 20 MA)\n"
                    f"Risk/Share    : ₹{risk_per_share:.2f}\n"
                    f"Quantity      : {qty} shares\n"
                    f"Risk Amount   : ₹{RISK_PER_TRADE:,}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Weekly RSI    : {weekly_rsi:.1f}  (Crossed above 60 ✅)\n"
                    f"Monthly RSI   : {monthly_rsi:.1f}  (> 60 ✅)\n"
                    f"Price > MA20  : ✅\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ Enter manually on <b>Monday open</b>"
                )
                logger.info(f"BUY signal — {qty} shares @ ₹{current_price:.2f}")

            else:
                # No signal this week
                send_telegram(
                    f"📊 <b>Weekly Scan — {SYMBOL}</b>\n"
                    f"📅 {now_ist}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"No entry signal this week.\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Monthly RSI   : {monthly_rsi:.1f}  {'✅' if monthly_rsi > 60 else '❌'}\n"
                    f"Price > MA20  : {'✅' if monthly_close > monthly_ma20 else '❌'}\n"
                    f"Weekly RSI    : {weekly_rsi:.1f}  (prev: {prev_weekly_rsi:.1f})\n"
                    f"RSI Cross 60  : {'✅' if rsi_crossover else '❌'}\n"
                )
                logger.info("No entry signal this week")

        # ==================================================
        # CASE 2 — Position open: trail SL, check exit / add
        # ==================================================
        else:
            new_sl   = weekly_ma20
            old_sl   = state['stop_loss']
            buy_price = state['buy_price']
            qty       = state['position']

            # ---- EXIT — price closed below 20 MA ----
            if current_price < new_sl:
                pnl = (current_price - buy_price) * qty

                send_telegram(
                    f"🔴 <b>EXIT SIGNAL — {SYMBOL}</b>\n"
                    f"📅 {now_ist}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Exit Price    : ₹{current_price:.2f}\n"
                    f"Buy Price     : ₹{buy_price:.2f}\n"
                    f"Stop Loss Hit : ₹{new_sl:.2f}  (Weekly 20 MA)\n"
                    f"Quantity      : {qty} shares\n"
                    f"P&L           : ₹{pnl:,.2f}  {'📈' if pnl >= 0 else '📉'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Weekly RSI    : {weekly_rsi:.1f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ <b>Exit at market on Monday open</b>"
                )

                state = {'position': 0, 'buy_price': 0.0, 'stop_loss': 0.0, 'position_added': False}
                save_state(state)
                logger.info(f"EXIT signal — P&L ₹{pnl:,.2f}")

            # ---- ADD POSITION — MA has crossed above buy price (trade risk-free) ----
            elif new_sl >= buy_price and not state['position_added']:
                risk_per_share = current_price - new_sl

                if risk_per_share > 0:
                    add_qty = int(RISK_PER_TRADE / risk_per_share)
                    state['position']      += add_qty
                    state['position_added'] = True
                    state['stop_loss']      = new_sl
                    save_state(state)

                    send_telegram(
                        f"🔵 <b>ADD POSITION — {SYMBOL}</b>\n"
                        f"📅 {now_ist}\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Add Price     : ₹{current_price:.2f}\n"
                        f"Stop Loss     : ₹{new_sl:.2f}  (Weekly 20 MA)\n"
                        f"Risk/Share    : ₹{risk_per_share:.2f}\n"
                        f"Add Quantity  : {add_qty} shares\n"
                        f"Total Qty     : {state['position']} shares\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"MA20 ₹{new_sl:.2f} >= Buy ₹{buy_price:.2f} ✅\n"
                        f"Trade is now <b>risk-free</b> — pyramid entry\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚡ <b>Add qty manually on Monday open</b>"
                    )
                    logger.info(f"ADD signal — {add_qty} shares @ ₹{current_price:.2f}")

            # ---- TRAIL UPDATE — position holding, just update SL ----
            else:
                sl_change = new_sl - old_sl
                state['stop_loss'] = new_sl
                save_state(state)

                send_telegram(
                    f"📈 <b>Trail Update — {SYMBOL}</b>\n"
                    f"📅 {now_ist}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Current Price : ₹{current_price:.2f}\n"
                    f"Stop Loss     : ₹{new_sl:.2f}  (was ₹{old_sl:.2f})\n"
                    f"SL Change     : {'▲' if sl_change >= 0 else '▼'} ₹{abs(sl_change):.2f}\n"
                    f"Buy Price     : ₹{buy_price:.2f}\n"
                    f"Quantity      : {qty} shares\n"
                    f"Unrealised P&L: ₹{(current_price - buy_price) * qty:,.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Weekly RSI    : {weekly_rsi:.1f}\n"
                    f"Position added: {'Yes' if state['position_added'] else 'No'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Holding position. SL trailed ✅"
                )
                logger.info(f"Trail SL: ₹{old_sl:.2f} → ₹{new_sl:.2f}")

    except Exception as e:
        logger.error(f"Signal check failed: {e}", exc_info=True)
        send_telegram(
            f"⚠️ <b>Scanner Error — {SYMBOL}</b>\n"
            f"📅 {now_ist}\n\n"
            f"<code>{str(e)}</code>\n\n"
            f"Check Railway logs."
        )

# ============================================================
# SCHEDULER — Every Friday 16:30 IST (after NSE closes 15:30)
# ============================================================

def run_scheduler():
    logger.info(f"Scheduler started — will run every Friday 16:30 IST")
    logger.info(f"Symbol: {SYMBOL} | Risk/Trade: ₹{RISK_PER_TRADE:,}")

    send_telegram(
        f"🚀 <b>Signal Scanner Started</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol       : {SYMBOL}\n"
        f"Risk/Trade   : ₹{RISK_PER_TRADE:,}\n"
        f"Schedule     : Every Friday 16:30 IST\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Running initial scan now..."
    )

    # Run once immediately on startup
    check_signals()

    # Schedule weekly Friday 16:30 IST
    schedule.every().friday.at("11:00").do(check_signals)  # 11:00 UTC = 16:30 IST

    while True:
        schedule.run_pending()
        time.sleep(60)

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == '__main__':
    run_scheduler()
