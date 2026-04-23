"use client";

import { useEffect, useState } from "react";
import {
  getWatchlist, addToWatchlist, removeFromWatchlist, updateLotSize,
  type WatchlistItem,
} from "@/lib/api";

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [symbol, setSymbol] = useState("");
  const [lotSize, setLotSize] = useState("");
  const [adding, setAdding] = useState(false);
  const [editingLot, setEditingLot] = useState<Record<string, string>>({});
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const load = () => getWatchlist().then(setItems).catch(console.error);

  useEffect(() => { load(); }, []);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    setAdding(true);
    try {
      await addToWatchlist(sym, parseInt(lotSize) || 0);
      setSymbol("");
      setLotSize("");
      showToast(`${sym} added. Lot size auto-detected (edit below if wrong).`);
      load();
    } catch (err: any) {
      showToast(err.message, false);
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (sym: string) => {
    if (!confirm(`Remove ${sym} from watchlist?`)) return;
    await removeFromWatchlist(sym);
    showToast(`${sym} removed`);
    load();
  };

  const handleLotSave = async (sym: string) => {
    const val = parseInt(editingLot[sym] || "0");
    if (!val || val <= 0) return showToast("Enter a valid lot size", false);
    await updateLotSize(sym, val);
    showToast(`${sym} lot size updated to ${val}`);
    setEditingLot((p) => { const n = { ...p }; delete n[sym]; return n; });
    load();
  };

  return (
    <div className="max-w-xl space-y-6">
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded shadow-lg text-sm font-medium ${
          toast.ok ? "bg-green-700 text-white" : "bg-red-700 text-white"
        }`}>
          {toast.msg}
        </div>
      )}

      <div>
        <h1 className="text-xl font-bold text-white">Watchlist</h1>
        <p className="text-xs text-slate-500 mt-1">
          Only these stocks will be scanned. Use NSE symbol format (e.g. RELIANCE, TCS, INFY).
        </p>
      </div>

      {/* Add form */}
      <form onSubmit={handleAdd} className="card p-4 flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-xs text-slate-400 mb-1">NSE Symbol</label>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="e.g. RELIANCE"
            className="w-full bg-[#0b0e17] border border-[#1e2435] rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div className="w-28">
          <label className="block text-xs text-slate-400 mb-1">Lot Size (optional)</label>
          <input
            type="number"
            value={lotSize}
            onChange={(e) => setLotSize(e.target.value)}
            placeholder="Auto"
            className="w-full bg-[#0b0e17] border border-[#1e2435] rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
          />
        </div>
        <button type="submit" className="btn-primary" disabled={adding}>
          {adding ? "Adding…" : "Add"}
        </button>
      </form>

      <p className="text-xs text-slate-500">
        Lot size is auto-fetched from NSE. If it shows 0, enter it manually below.
      </p>

      {/* Watchlist table */}
      <div className="card overflow-hidden">
        {items.length === 0 ? (
          <div className="p-10 text-center text-slate-500 text-sm">
            No stocks in watchlist. Add your first stock above.
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Lot Size</th>
                <th>Added</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.symbol} className="hover:bg-white/[0.02]">
                  <td className="font-semibold text-white">{item.symbol}</td>
                  <td>
                    {editingLot[item.symbol] !== undefined ? (
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          value={editingLot[item.symbol]}
                          onChange={(e) =>
                            setEditingLot((p) => ({ ...p, [item.symbol]: e.target.value }))
                          }
                          className="w-20 bg-[#0b0e17] border border-indigo-500 rounded px-2 py-1 text-white text-sm"
                          autoFocus
                        />
                        <button
                          className="text-xs text-indigo-400 hover:text-white"
                          onClick={() => handleLotSave(item.symbol)}
                        >
                          Save
                        </button>
                        <button
                          className="text-xs text-slate-500 hover:text-white"
                          onClick={() =>
                            setEditingLot((p) => { const n = { ...p }; delete n[item.symbol]; return n; })
                          }
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() =>
                          setEditingLot((p) => ({ ...p, [item.symbol]: String(item.lot_size) }))
                        }
                        className={`text-sm ${item.lot_size === 0 ? "text-amber-400 font-semibold" : "text-slate-300"} hover:text-white`}
                      >
                        {item.lot_size === 0 ? "⚠ Set lot size" : item.lot_size}
                      </button>
                    )}
                  </td>
                  <td className="text-slate-500 text-xs">
                    {item.added_at ? new Date(item.added_at).toLocaleDateString("en-IN") : "—"}
                  </td>
                  <td className="text-right">
                    <button
                      onClick={() => handleRemove(item.symbol)}
                      className="text-xs text-slate-500 hover:text-red-400 transition-colors px-2"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card p-4 text-xs text-slate-500 space-y-1">
        <p className="font-semibold text-slate-400">Tips</p>
        <p>• Symbols must match NSE exactly — check nseindia.com if unsure</p>
        <p>• Lot sizes change quarterly — update them after NSE revision</p>
        <p>• After adding stocks, click <strong className="text-slate-300">Manual Init</strong> on the Scanner page to load them immediately</p>
        <p>• Otherwise the scanner auto-loads them at 8:45 AM next trading day</p>
      </div>
    </div>
  );
}
