import os
import json
import time
import logging
import threading
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
# CONSTANTS
# ============================================================

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CONFIG_FILE      = 'config.json'
STATE_FILE       = 'state.json'
IST              = pytz.timezone('Asia/Kolkata')

# ============================================================
# CONFIG — symbol & risk saved here, updated via bot commands
# ============================================================

def load_config() -> dict:
    defaults = {
        'symbol':        os.getenv('SYMBOL', 'RELIANCE.NS'),
        'risk_per_trade': int(os.getenv('RISK_PER_TRADE', '10000'))
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            defaults.update(json.load(f))
    return defaults

def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    logger.info(f"Config saved: {config}")

# ============================================================
# STATE
# ============================================================

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'position': 0, 'buy_price': 0.0, 'stop_loss': 0.0, 'position_added': False}

def save_state(state: dict):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    logger.info(f"State saved: {state}")

# ============================================================
# TELEGRAM — send message
# ============================================================

def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            'chat_id':    TELEGRAM_CHAT_ID,
            'text':       message,
            'parse_mode': 'HTML'
        }, timeout=10)
        r.raise_for_status()
        logger.info("Telegram message sent")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

# ============================================================
# DATA & INDICATORS
# ============================================================

def get_data(symbol: str) -> pd.DataFrame:
    logger.info(f"Downloading data for {symbol}...")
    ticker = yf.Ticker(symbol)
    data   = ticker.history(start='2015-01-01', auto_adjust=True)

    logger.info(f"Raw shape: {data.shape} | Columns: {data.columns.tolist()}")

    if data.empty:
        raise ValueError(f"No data returned for {symbol}. Check symbol (e.g. RELIANCE.NS, TCS.NS)")

    data = data[['Open', 'High', 'Low', 'Close', 'Volume']]
    data = data[data['Close'].notna()]
    data.index = data.index.tz_localize(None) if data.index.tzinfo else data.index

    logger.info(f"Clean data: {len(data)} candles ({data.index[0].date()} → {data.index[-1].date()})")
    return data

def compute_indicators(data: pd.DataFrame):
    weekly = data.resample('W-FRI').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
    })
    weekly = weekly[weekly['Close'].notna()]
    weekly['RSI']  = ta.momentum.RSIIndicator(weekly['Close'], window=14).rsi()
    weekly['MA20'] = weekly['Close'].rolling(20).mean()

    monthly = data.resample('ME').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
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
    config         = load_config()
    symbol         = config['symbol']
    risk_per_trade = config['risk_per_trade']
    now_ist        = datetime.now(IST).strftime('%d %b %Y %H:%M IST')

    logger.info(f"=== Signal Check — {symbol} ===")

    try:
        data            = get_data(symbol)
        weekly, monthly = compute_indicators(data)
        state           = load_state()

        if len(weekly) < 2:
            raise ValueError(f"Not enough weekly data: {len(weekly)} rows")
        if len(monthly) < 1:
            raise ValueError(f"Not enough monthly data: {len(monthly)} rows")

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

        monthly_ok    = monthly_rsi > 60 and monthly_close > monthly_ma20
        rsi_crossover = prev_weekly_rsi < 60 and weekly_rsi > 60

        logger.info(
            f"Price={current_price:.2f} | WeeklyRSI={weekly_rsi:.1f} "
            f"(prev={prev_weekly_rsi:.1f}) | MA20={weekly_ma20:.2f} | "
            f"MonthlyRSI={monthly_rsi:.1f} | MonthlyOK={monthly_ok} | Cross={rsi_crossover}"
        )

        # ---- No position: look for entry ----
        if state['position'] == 0:
            if monthly_ok and rsi_crossover:
                risk_per_share = current_price - weekly_ma20
                if risk_per_share <= 0:
                    send_telegram(
                        f"⚠️ <b>Signal Skipped — {symbol}</b>\n"
                        f"Entry at or below MA20 — no valid risk."
                    )
                    return

                qty   = int(risk_per_trade / risk_per_share)
                state = {'position': qty, 'buy_price': current_price,
                         'stop_loss': weekly_ma20, 'position_added': False}
                save_state(state)

                send_telegram(
                    f"🟢 <b>BUY SIGNAL — {symbol}</b>\n"
                    f"📅 {now_ist}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Entry Price   : ₹{current_price:.2f}\n"
                    f"Stop Loss     : ₹{weekly_ma20:.2f}  (Weekly 20 MA)\n"
                    f"Risk/Share    : ₹{risk_per_share:.2f}\n"
                    f"Quantity      : {qty} shares\n"
                    f"Risk Amount   : ₹{risk_per_trade:,}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Weekly RSI    : {weekly_rsi:.1f}  (Crossed above 60 ✅)\n"
                    f"Monthly RSI   : {monthly_rsi:.1f}  (> 60 ✅)\n"
                    f"Price > MA20  : ✅\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ Enter manually on <b>Monday open</b>"
                )

            else:
                send_telegram(
                    f"📊 <b>Weekly Scan — {symbol}</b>\n"
                    f"📅 {now_ist}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"No entry signal this week.\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Monthly RSI   : {monthly_rsi:.1f}  {'✅' if monthly_rsi > 60 else '❌'}\n"
                    f"Price > MA20  : {'✅' if monthly_close > monthly_ma20 else '❌'}\n"
                    f"Weekly RSI    : {weekly_rsi:.1f}  (prev: {prev_weekly_rsi:.1f})\n"
                    f"RSI Cross 60  : {'✅' if rsi_crossover else '❌'}\n"
                )

        # ---- Position open: trail SL, check exit/add ----
        else:
            new_sl    = weekly_ma20
            old_sl    = state['stop_loss']
            buy_price = state['buy_price']
            qty       = state['position']

            if current_price < new_sl:
                pnl = (current_price - buy_price) * qty
                send_telegram(
                    f"🔴 <b>EXIT SIGNAL — {symbol}</b>\n"
                    f"📅 {now_ist}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Exit Price    : ₹{current_price:.2f}\n"
                    f"Buy Price     : ₹{buy_price:.2f}\n"
                    f"Stop Loss Hit : ₹{new_sl:.2f}  (Weekly 20 MA)\n"
                    f"Quantity      : {qty} shares\n"
                    f"P&L           : ₹{pnl:,.2f}  {'📈' if pnl >= 0 else '📉'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ <b>Exit at market on Monday open</b>"
                )
                state = {'position': 0, 'buy_price': 0.0, 'stop_loss': 0.0, 'position_added': False}
                save_state(state)

            elif new_sl >= buy_price and not state['position_added']:
                risk_per_share = current_price - new_sl
                if risk_per_share > 0:
                    add_qty                 = int(risk_per_trade / risk_per_share)
                    state['position']      += add_qty
                    state['position_added'] = True
                    state['stop_loss']      = new_sl
                    save_state(state)

                    send_telegram(
                        f"🔵 <b>ADD POSITION — {symbol}</b>\n"
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

            else:
                sl_change          = new_sl - old_sl
                state['stop_loss'] = new_sl
                save_state(state)

                send_telegram(
                    f"📈 <b>Trail Update — {symbol}</b>\n"
                    f"📅 {now_ist}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Current Price  : ₹{current_price:.2f}\n"
                    f"Stop Loss      : ₹{new_sl:.2f}  (was ₹{old_sl:.2f})\n"
                    f"SL Change      : {'▲' if sl_change >= 0 else '▼'} ₹{abs(sl_change):.2f}\n"
                    f"Buy Price      : ₹{buy_price:.2f}\n"
                    f"Quantity       : {qty} shares\n"
                    f"Unrealised P&L : ₹{(current_price - buy_price) * qty:,.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Holding. SL trailed ✅"
                )

    except Exception as e:
        logger.error(f"Signal check failed: {e}", exc_info=True)
        send_telegram(
            f"⚠️ <b>Scanner Error — {symbol}</b>\n"
            f"📅 {now_ist}\n\n"
            f"<code>{str(e)}</code>\n\n"
            f"Check Railway logs."
        )

# ============================================================
# BOT COMMANDS — two-way Telegram communication
# ============================================================

def handle_command(text: str):
    parts  = text.strip().split()
    cmd    = parts[0].lower()
    config = load_config()
    state  = load_state()

    # ---- /help ----
    if cmd == '/help':
        send_telegram(
            "<b>Available Commands</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "/symbol RELIANCE.NS — change stock\n"
            "/risk 15000 — change risk per trade (₹)\n"
            "/scan — run scan right now\n"
            "/status — show current position\n"
            "/config — show active settings\n"
            "/reset — clear open position\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Scan runs automatically every Friday 16:30 IST"
        )

    # ---- /symbol ----
    elif cmd == '/symbol':
        if len(parts) < 2:
            send_telegram("Usage: <code>/symbol RELIANCE.NS</code>")
            return
        new_symbol = parts[1].upper()
        send_telegram(f"🔍 Validating <b>{new_symbol}</b>...")
        try:
            test = yf.Ticker(new_symbol).history(period='5d')
            if test.empty:
                send_telegram(
                    f"❌ <b>{new_symbol}</b> not found.\n"
                    f"Use NSE format: RELIANCE.NS, TCS.NS, HDFCBANK.NS"
                )
                return
        except Exception as e:
            send_telegram(f"❌ Could not validate {new_symbol}: {e}")
            return

        config['symbol'] = new_symbol
        save_config(config)
        send_telegram(
            f"✅ Symbol changed to <b>{new_symbol}</b>\n"
            f"Send /scan to run a scan now."
        )

    # ---- /risk ----
    elif cmd == '/risk':
        if len(parts) < 2:
            send_telegram("Usage: <code>/risk 15000</code>")
            return
        try:
            new_risk = int(parts[1])
            if new_risk <= 0:
                raise ValueError
        except ValueError:
            send_telegram("❌ Invalid amount. Example: <code>/risk 15000</code>")
            return

        config['risk_per_trade'] = new_risk
        save_config(config)
        send_telegram(f"✅ Risk per trade set to <b>₹{new_risk:,}</b>")

    # ---- /scan ----
    elif cmd == '/scan':
        send_telegram(f"🔍 Running scan for <b>{config['symbol']}</b>...")
        threading.Thread(target=check_signals, daemon=True).start()

    # ---- /status ----
    elif cmd == '/status':
        sym  = config['symbol']
        risk = config['risk_per_trade']
        if state['position'] == 0:
            send_telegram(
                f"📊 <b>Status — {sym}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Position      : No open trade\n"
                f"Risk/Trade    : ₹{risk:,}"
            )
        else:
            send_telegram(
                f"📊 <b>Status — {sym}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Position      : {state['position']} shares\n"
                f"Buy Price     : ₹{state['buy_price']:.2f}\n"
                f"Stop Loss     : ₹{state['stop_loss']:.2f}\n"
                f"Added Qty     : {'Yes' if state['position_added'] else 'No'}\n"
                f"Risk/Trade    : ₹{risk:,}"
            )

    # ---- /config ----
    elif cmd == '/config':
        send_telegram(
            f"⚙️ <b>Active Config</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Symbol        : {config['symbol']}\n"
            f"Risk/Trade    : ₹{config['risk_per_trade']:,}\n"
            f"Schedule      : Every Friday 16:30 IST"
        )

    # ---- /reset ----
    elif cmd == '/reset':
        save_state({'position': 0, 'buy_price': 0.0, 'stop_loss': 0.0, 'position_added': False})
        send_telegram("🔄 Position reset. Scanner will look for fresh entry signals.")

    else:
        send_telegram(
            f"❓ Unknown command: <code>{cmd}</code>\n"
            f"Send /help for available commands."
        )

# ============================================================
# TELEGRAM LONG POLLING — runs in background thread
# ============================================================

def poll_telegram():
    offset = 0
    logger.info("Telegram polling started — listening for commands...")

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            r   = requests.get(url, params={'offset': offset, 'timeout': 30}, timeout=35)
            data = r.json()

            if not data.get('ok'):
                logger.warning(f"Polling response not OK: {data}")
                time.sleep(5)
                continue

            for update in data.get('result', []):
                offset  = update['update_id'] + 1
                msg     = update.get('message', {})
                text    = msg.get('text', '').strip()
                chat_id = str(msg.get('chat', {}).get('id', ''))

                if not text or not chat_id:
                    continue

                # Only respond to the authorised chat
                if chat_id != str(TELEGRAM_CHAT_ID):
                    logger.warning(f"Ignored message from unknown chat: {chat_id}")
                    continue

                logger.info(f"Command received: {text}")
                try:
                    handle_command(text)
                except Exception as e:
                    logger.error(f"Command error: {e}", exc_info=True)
                    send_telegram(f"❌ Error handling command:\n<code>{str(e)}</code>")

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)

# ============================================================
# MAIN — start polling thread + scheduler
# ============================================================

def run_scheduler():
    config = load_config()

    logger.info(f"Starting scanner | Symbol: {config['symbol']} | Risk: ₹{config['risk_per_trade']:,}")

    send_telegram(
        f"🚀 <b>Signal Scanner Started</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol       : {config['symbol']}\n"
        f"Risk/Trade   : ₹{config['risk_per_trade']:,}\n"
        f"Schedule     : Every Friday 16:30 IST\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Two-way bot active. Send /help for commands.\n"
        f"Running initial scan now..."
    )

    # Start Telegram polling in background thread
    threading.Thread(target=poll_telegram, daemon=True).start()

    # Run scan immediately on startup
    check_signals()

    # Schedule weekly — every Friday 11:00 UTC = 16:30 IST
    schedule.every().friday.at("11:00").do(check_signals)

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == '__main__':
    run_scheduler()
