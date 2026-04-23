"use client";

import { useEffect, useState } from "react";
import { getHistory, type Trade, type HistoryResponse } from "@/lib/api";

export default function HistoryPage() {
  const [data, setData] = useState<HistoryResponse | null>(null);

  useEffect(() => {
    getHistory().then(setData).catch(console.error);
  }, []);

  const fmt = (n: number | null | undefined) =>
    n == null ? "—" : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

  const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

  const exitLabel: Record<string, string> = {
    sl_hit: "SL Hit",
    trailing_sl: "Trailing SL",
    manual_exit: "Manual",
    market_close: "EOD Close",
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-white">Trade History</h1>

      {/* Stats */}
      {data?.stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { label: "Total Trades", val: data.stats.total_trades },
            { label: "Wins", val: data.stats.winning_trades, green: true },
            { label: "Losses", val: data.stats.losing_trades, red: true },
            { label: "Win Rate", val: `${data.stats.win_rate}%` },
            { label: "Total P&L", val: `₹${fmt(data.stats.total_pnl)}`, pnl: data.stats.total_pnl },
            { label: "Avg P&L", val: `₹${fmt(data.stats.avg_pnl)}`, pnl: data.stats.avg_pnl },
          ].map((s) => (
            <div key={s.label} className="card p-4">
              <p className="text-xs text-slate-500 mb-1">{s.label}</p>
              <p
                className={`text-lg font-bold ${
                  s.green
                    ? "text-green-400"
                    : s.red
                    ? "text-red-400"
                    : s.pnl != null
                    ? s.pnl >= 0
                      ? "text-green-400"
                      : "text-red-400"
                    : "text-white"
                }`}
              >
                {s.val}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Table */}
      <div className="card overflow-x-auto">
        <table className="w-full min-w-[750px]">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Dir</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Lots</th>
              <th>P&L ₹</th>
              <th>P&L %</th>
              <th>Reason</th>
              <th>Duration</th>
              <th>Entry Time</th>
            </tr>
          </thead>
          <tbody>
            {!data || data.trades.length === 0 ? (
              <tr>
                <td colSpan={10} className="text-center text-slate-500 py-10">
                  No trades yet
                </td>
              </tr>
            ) : (
              data.trades.map((t) => (
                <tr key={t.id} className="hover:bg-white/[0.02]">
                  <td className="font-semibold text-white">{t.symbol}</td>
                  <td>
                    <span className={t.direction === "BUY" ? "badge-buy" : "badge-sell"}>
                      {t.direction}
                    </span>
                  </td>
                  <td>₹{fmt(t.entry_price)}</td>
                  <td>₹{fmt(t.exit_price)}</td>
                  <td>{t.lots} × {t.lot_size}</td>
                  <td className={t.pnl >= 0 ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>
                    {t.pnl >= 0 ? "+" : ""}₹{fmt(t.pnl)}
                  </td>
                  <td className={t.pnl_pct >= 0 ? "text-green-400" : "text-red-400"}>
                    {fmtPct(t.pnl_pct)}
                  </td>
                  <td className="text-slate-400 text-xs">
                    {exitLabel[t.exit_reason] ?? t.exit_reason}
                  </td>
                  <td className="text-slate-400 text-xs">
                    {t.duration_min != null ? `${t.duration_min}m` : "—"}
                  </td>
                  <td className="text-slate-500 text-xs">
                    {t.entry_time
                      ? new Date(t.entry_time).toLocaleString("en-IN")
                      : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
