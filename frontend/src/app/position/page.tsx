"use client";

import { useEffect, useState, useCallback } from "react";
import { getPosition, exitPosition, type Position } from "@/lib/api";

export default function PositionPage() {
  const [pos, setPos] = useState<Position | null | undefined>(undefined);
  const [exiting, setExiting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    const p = await getPosition();
    setPos(p);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [load]);

  const handleExit = async () => {
    if (!confirm("Exit the open position at current price?")) return;
    setExiting(true);
    try {
      const res: any = await exitPosition();
      setToast(`Position closed. P&L: ₹${res.pnl?.toLocaleString("en-IN")}`);
      load();
    } catch (e: any) {
      setToast(e.message);
    } finally {
      setExiting(false);
    }
  };

  const fmt = (n: number) =>
    n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

  const trailLabel = (tier: number) => {
    if (tier === 0) return "Initial SL";
    if (tier === 1) return "Breakeven";
    return `+${(tier - 1) * 3}% lock`;
  };

  if (pos === undefined) {
    return <div className="text-slate-500 text-sm">Loading…</div>;
  }

  return (
    <div className="space-y-6 max-w-xl">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-indigo-700 text-white px-4 py-3 rounded shadow-lg text-sm">
          {toast}
        </div>
      )}

      <h1 className="text-xl font-bold text-white">Active Position</h1>

      {!pos ? (
        <div className="card p-10 text-center text-slate-500">
          No open position. Execute a signal from the Scanner.
        </div>
      ) : (
        <div className="card p-6 space-y-5">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <span className="text-2xl font-bold text-white">{pos.symbol}</span>
              <span
                className={`ml-3 text-sm font-semibold px-2 py-0.5 rounded ${
                  pos.direction === "BUY"
                    ? "bg-green-800/50 text-green-300"
                    : "bg-red-800/50 text-red-300"
                }`}
              >
                {pos.direction}
              </span>
            </div>
            <button
              className="btn-danger"
              onClick={handleExit}
              disabled={exiting}
            >
              {exiting ? "Exiting…" : "Exit Now"}
            </button>
          </div>

          {/* P&L */}
          <div
            className={`text-4xl font-bold ${
              pos.pnl >= 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            {pos.pnl >= 0 ? "+" : ""}₹{fmt(pos.pnl)}
            <span className="text-xl ml-2">
              ({pos.pnl_pct >= 0 ? "+" : ""}{pos.pnl_pct.toFixed(2)}%)
            </span>
          </div>

          {/* Details grid */}
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Entry Price" value={`₹${fmt(pos.entry_price)}`} />
            <Stat label="Current Price" value={`₹${fmt(pos.current_price)}`} highlight />
            <Stat label="Stop Loss" value={`₹${fmt(pos.sl_price)}`} danger />
            <Stat label="Original SL" value={`₹${fmt(pos.original_sl)}`} />
            <Stat label="Lots" value={`${pos.lots} × ${pos.lot_size}`} />
            <Stat label="Trailing Tier" value={trailLabel(pos.trailing_tier)} />
            <Stat
              label="Entry Time"
              value={new Date(pos.entry_time).toLocaleString("en-IN")}
            />
            <Stat
              label="SL Distance"
              value={`${Math.abs(
                ((pos.current_price - pos.sl_price) / pos.entry_price) * 100
              ).toFixed(2)}%`}
            />
          </div>

          {/* Trailing stop ladder */}
          <div>
            <p className="text-xs text-slate-400 mb-2 uppercase tracking-wide">
              Trailing Stop Ladder
            </p>
            <div className="flex gap-2 flex-wrap">
              {[0, 1, 2, 3, 4].map((tier) => (
                <div
                  key={tier}
                  className={`px-3 py-1 rounded text-xs font-medium border ${
                    tier <= pos.trailing_tier
                      ? "border-indigo-500 text-indigo-300 bg-indigo-900/30"
                      : "border-[#1e2435] text-slate-600"
                  }`}
                >
                  {tier === 0 ? "Entry" : `+${tier * 3}%`}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  highlight,
  danger,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  danger?: boolean;
}) {
  return (
    <div className="bg-[#0d1120] rounded p-3">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p
        className={`text-sm font-semibold ${
          highlight ? "text-white" : danger ? "text-red-400" : "text-slate-200"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
