const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(msg || res.statusText);
  }
  return res.json();
}

// Scanner
export const getScanner = () => req<ScannerResponse>("/api/scanner");
export const triggerInit = () => req("/api/scanner/trigger", { method: "POST" });

// Signals
export const getSignals = () => req<Signal[]>("/api/signals");
export const executeSignal = (id: number, current_price: number) =>
  req(`/api/signals/${id}/execute`, {
    method: "POST",
    body: JSON.stringify({ current_price }),
  });
export const dismissSignal = (id: number) =>
  req(`/api/signals/${id}`, { method: "DELETE" });

// Position
export const getPosition = () => req<Position | null>("/api/position");
export const exitPosition = () => req("/api/position/exit", { method: "POST" });

// History
export const getHistory = () => req<HistoryResponse>("/api/history");

// Settings
export const getSettings = () => req<Settings>("/api/settings");
export const updateSettings = (body: Settings) =>
  req("/api/settings", { method: "PUT", body: JSON.stringify(body) });

// Watchlist
export const getWatchlist = () => req<WatchlistItem[]>("/api/watchlist");
export const addToWatchlist = (symbol: string, lot_size = 0) =>
  req("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol, lot_size }) });
export const removeFromWatchlist = (symbol: string) =>
  req(`/api/watchlist/${symbol}`, { method: "DELETE" });
export const updateLotSize = (symbol: string, lot_size: number) =>
  req(`/api/watchlist/${symbol}/lot-size?lot_size=${lot_size}`, { method: "PUT" });

// ---- Types ----------------------------------------------------------------

export interface ScannerRow {
  symbol: string;
  lot_size: number;
  prev_high: number;
  prev_low: number;
  prev_close: number;
  current_price: number;
  buy_trigger: number | null;
  sell_trigger: number | null;
  is_gap_up: boolean;
  is_gap_down: boolean;
  candle_locked: boolean;
  signal: "BUY" | "SELL" | null;
  dist_to_buy_pct: number;
  dist_to_sell_pct: number;
}

export interface ScannerResponse {
  rows: ScannerRow[];
  last_scan: string | null;
  market_open: boolean;
  initialized: boolean;
  error: string | null;
}

export interface Signal {
  id: number;
  symbol: string;
  direction: "BUY" | "SELL";
  signal_type: string;
  entry_price: number;
  sl_price: number;
  sl_pct: number;
  lots: number;
  lot_size: number;
  capital_risk: number;
  status: string;
  triggered_at: string;
}

export interface Position {
  id: number;
  symbol: string;
  direction: "BUY" | "SELL";
  entry_price: number;
  entry_time: string;
  sl_price: number;
  original_sl: number;
  trailing_tier: number;
  lots: number;
  lot_size: number;
  current_price: number;
  pnl: number;
  pnl_pct: number;
  status: string;
}

export interface Trade {
  id: number;
  symbol: string;
  direction: "BUY" | "SELL";
  entry_price: number;
  exit_price: number;
  lots: number;
  lot_size: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  entry_time: string;
  exit_time: string;
  duration_min: number;
}

export interface HistoryResponse {
  trades: Trade[];
  stats: {
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate: number;
    total_pnl: number;
    avg_pnl: number;
  };
}

export interface WatchlistItem {
  symbol: string;
  lot_size: number;
  added_at: string;
}

export interface Settings {
  capital: number;
  risk_pct: number;
  sl_pct_intraday: number;
  sl_pct_nextday: number;
  trailing_step: number;
  updated_at?: string;
}
