"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getScanner, getSignals, executeSignal, dismissSignal, triggerInit,
  type ScannerRow, type Signal,
} from "@/lib/api";

type Filter = "all" | "BUY" | "SELL";

export default function ScannerPage() {
  const [rows, setRows] = useState<ScannerRow[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [lastScan, setLastScan] = useState<string | null>(null);
  const [marketOpen, setMarketOpen] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [executing, setExecuting] = useState<number | null>(null);
  const [execPrice, setExecPrice] = useState<Record<number, string>>({});
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const refresh = useCallback(async () => {
    try {
      const [scanner, sigs] = await Promise.all([getScanner(), getSignals()]);
      setRows(scanner.rows);
      setLastScan(scanner.last_scan);
      setMarketOpen(scanner.market_open);
      setInitialized(scanner.initialized);
      setError(scanner.error);
      setSignals(sigs);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  const handleExecute = async (sig: Signal) => {
    const price = parseFloat(execPrice[sig.id] || String(sig.entry_price));
    if (!price || price <= 0) return showToast("Enter a valid price", false);
    setExecuting(sig.id);
    try {
      await executeSignal(sig.id, price);
      showToast(`${sig.direction} ${sig.symbol} executed!`);
      refresh();
    } catch (e: any) {
      showToast(e.message, false);
    } finally {
      setExecuting(null);
    }
  };

  const handleDismiss = async (id: number) => {
    await dismissSignal(id);
    refresh();
  };

  const handleTriggerInit = async () => {
    await triggerInit();
    showToast("Pre-market init triggered");
  };

  const filtered = rows.filter((r) => {
    if (filter === "BUY" && r.signal !== "BUY") return false;
    if (filter === "SELL" && r.signal !== "SELL") return false;
    if (search && !r.symbol.includes(search.toUpperCase())) return false;
    return true;
  });

  const fmt = (n: number | null | undefined) =>
    n == null ? "—" : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

  return (
    <div className="space-y-6">
      {/* Toast */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded shadow-lg text-sm font-medium ${
            toast.ok ? "bg-green-700 text-white" : "bg-red-700 text-white"
          }`}
        >
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Scanner</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {lastScan ? `Last scan: ${new Date(lastScan).toLocaleTimeString("en-IN")}` : "Not scanned yet"}
            {" · "}
            <span className={marketOpen ? "text-green-400" : "text-slate-500"}>
              {marketOpen ? "Market OPEN" : "Market CLOSED"}
            </span>
            {" · "}
            <span className={initialized ? "text-green-400" : "text-amber-400"}>
              {initialized ? "Initialized" : "Not initialized"}
            </span>
          </p>
          {error && <p className="text-xs text-red-400 mt-1">Error: {error}</p>}
        </div>
        <button onClick={handleTriggerInit} className="btn-ghost text-xs">
          Manual Init
        </button>
      </div>

      {/* Pending signals */}
      {signals.length > 0 && (
        <div className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold text-white">
            Pending Signals ({signals.length})
          </h2>
          {signals.map((sig) => (
            <div
              key={sig.id}
              className="flex flex-wrap items-center gap-3 py-2 border-t border-[#1e2435]"
            >
              <span className={sig.direction === "BUY" ? "badge-buy" : "badge-sell"}>
                {sig.direction}
              </span>
              <span className="font-semibold text-white">{sig.symbol}</span>
              <span className="text-slate-400 text-xs">
                {sig.signal_type.replace("_", "-").toUpperCase()}
              </span>
              <span className="text-slate-300 text-sm">
                Entry ₹{fmt(sig.entry_price)} · SL ₹{fmt(sig.sl_price)} ({sig.sl_pct.toFixed(2)}%) · {sig.lots} lot(s)
              </span>
              <div className="flex items-center gap-2 ml-auto">
                <input
                  type="number"
                  placeholder={String(sig.entry_price)}
                  value={execPrice[sig.id] ?? ""}
                  onChange={(e) =>
                    setExecPrice((p) => ({ ...p, [sig.id]: e.target.value }))
                  }
                  className="w-28 bg-[#0b0e17] border border-[#1e2435] rounded px-2 py-1 text-sm text-white"
                />
                <button
                  className="btn-primary"
                  disabled={executing === sig.id}
                  onClick={() => handleExecute(sig)}
                >
                  {executing === sig.id ? "…" : "Execute"}
                </button>
                <button className="btn-ghost" onClick={() => handleDismiss(sig.id)}>
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filter bar */}
      <div className="flex items-center gap-3">
        {(["all", "BUY", "SELL"] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              filter === f
                ? f === "BUY"
                  ? "bg-green-700/50 text-green-300"
                  : f === "SELL"
                  ? "bg-red-700/50 text-red-300"
                  : "bg-indigo-600 text-white"
                : "text-slate-400 hover:text-white border border-[#1e2435]"
            }`}
          >
            {f === "all" ? "All" : f}
          </button>
        ))}
        <input
          type="text"
          placeholder="Search symbol…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="ml-auto w-44 bg-[#141824] border border-[#1e2435] rounded px-3 py-1.5 text-sm text-white placeholder-slate-600"
        />
        <span className="text-slate-500 text-xs">{filtered.length} stocks</span>
      </div>

      {/* Scanner table */}
      <div className="card overflow-x-auto">
        <table className="w-full min-w-[900px]">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Lot</th>
              <th>Prev H</th>
              <th>Prev L</th>
              <th>Prev C</th>
              <th>Current</th>
              <th>Buy Trigger</th>
              <th>Sell Trigger</th>
              <th>→ Buy</th>
              <th>→ Sell</th>
              <th>Signal</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={11} className="text-center text-slate-500 py-10">
                  {initialized ? "No stocks match filter" : "Scanner not initialized — click Manual Init or wait for 8:45 AM"}
                </td>
              </tr>
            )}
            {filtered.map((row) => (
              <tr key={row.symbol} className="hover:bg-white/[0.02]">
                <td className="font-semibold text-white">{row.symbol}</td>
                <td className="text-slate-400">{row.lot_size}</td>
                <td>{fmt(row.prev_high)}</td>
                <td>{fmt(row.prev_low)}</td>
                <td>{fmt(row.prev_close)}</td>
                <td className="font-mono font-medium text-white">{fmt(row.current_price)}</td>
                <td className="text-green-400/80">{fmt(row.buy_trigger)}</td>
                <td className="text-red-400/80">{fmt(row.sell_trigger)}</td>
                <td className={row.dist_to_buy_pct > 0 ? "text-slate-400" : "text-green-400"}>
                  {row.dist_to_buy_pct > 0 ? fmtPct(row.dist_to_buy_pct) : "✓"}
                </td>
                <td className={row.dist_to_sell_pct > 0 ? "text-slate-400" : "text-red-400"}>
                  {row.dist_to_sell_pct > 0 ? fmtPct(row.dist_to_sell_pct) : "✓"}
                </td>
                <td>
                  {row.signal ? (
                    <span className={row.signal === "BUY" ? "badge-buy" : "badge-sell"}>
                      {row.signal}
                    </span>
                  ) : (
                    <span className="text-slate-600 text-xs">—</span>
                  )}
                  {(row.is_gap_up || row.is_gap_down) && (
                    <span className="ml-1 text-amber-400 text-xs">
                      {row.is_gap_up ? "↑gap" : "↓gap"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
