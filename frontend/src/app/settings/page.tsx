"use client";

import { useEffect, useState } from "react";
import { getSettings, updateSettings, type Settings } from "@/lib/api";

export default function SettingsPage() {
  const [form, setForm] = useState<Settings>({
    capital: 500000,
    risk_pct: 3,
    sl_pct_intraday: 1.5,
    sl_pct_nextday: 3,
    trailing_step: 3,
  });
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setForm({ ...s }))
      .catch(console.error);
  }, []);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await updateSettings(form);
      showToast("Settings saved");
    } catch (err: any) {
      showToast(err.message, false);
    } finally {
      setSaving(false);
    }
  };

  const field = (
    key: keyof Settings,
    label: string,
    hint: string,
    prefix?: string,
    suffix?: string
  ) => (
    <div>
      <label className="block text-sm font-medium text-slate-300 mb-1">
        {label}
      </label>
      <p className="text-xs text-slate-500 mb-2">{hint}</p>
      <div className="flex items-center gap-2">
        {prefix && <span className="text-slate-400 text-sm">{prefix}</span>}
        <input
          type="number"
          value={form[key] as number}
          onChange={(e) =>
            setForm((f) => ({ ...f, [key]: parseFloat(e.target.value) || 0 }))
          }
          step={key === "capital" ? 10000 : 0.1}
          min={key === "capital" ? 1000 : 0.1}
          className="w-40 bg-[#0b0e17] border border-[#1e2435] rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
        />
        {suffix && <span className="text-slate-400 text-sm">{suffix}</span>}
      </div>
    </div>
  );

  return (
    <div className="max-w-lg space-y-6">
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded shadow-lg text-sm font-medium ${
            toast.ok ? "bg-green-700 text-white" : "bg-red-700 text-white"
          }`}
        >
          {toast.msg}
        </div>
      )}

      <h1 className="text-xl font-bold text-white">Settings</h1>

      <form onSubmit={handleSave} className="card p-6 space-y-6">
        {field("capital", "Trading Capital", "Total paper-trading capital for position sizing", "₹")}
        {field("risk_pct", "Risk per Trade", "Max % of capital to risk on a single trade", "", "%")}
        {field("sl_pct_intraday", "Intraday Stop Loss", "SL % applied on entry day (below entry for BUY)", "", "%")}
        {field("sl_pct_nextday", "Next-Day Stop Loss / 3% Rule", "Used for next-day SL and breakout trigger (prev close ±%)", "", "%")}
        {field("trailing_step", "Trailing Step", "P&L % at which trailing stop advances one tier", "", "%")}

        <div className="pt-2 border-t border-[#1e2435]">
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save Settings"}
          </button>
        </div>

        {/* Summary card */}
        <div className="bg-[#0d1120] rounded p-4 text-xs text-slate-400 space-y-1">
          <p className="font-semibold text-slate-300 mb-2">Trailing Stop Tiers</p>
          {[0, 1, 2, 3].map((tier) => (
            <p key={tier}>
              {tier === 0
                ? `Tier 0 — Initial SL at ${form.sl_pct_intraday}% below entry`
                : `Tier ${tier} — price +${tier * form.trailing_step}% → SL moves to ${
                    tier === 1 ? "breakeven" : `+${(tier - 1) * form.trailing_step}%`
                  }`}
            </p>
          ))}
        </div>
      </form>
    </div>
  );
}
