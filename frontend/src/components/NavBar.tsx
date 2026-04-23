"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Scanner" },
  { href: "/position", label: "Position" },
  { href: "/history", label: "History" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/settings", label: "Settings" },
];

export default function NavBar() {
  const path = usePathname();
  return (
    <nav className="border-b border-[#1e2435] bg-[#0d1120]">
      <div className="max-w-screen-xl mx-auto px-4 flex items-center gap-1 h-14">
        <span className="text-white font-bold mr-6 text-sm tracking-widest uppercase">
          Top Bottom
        </span>
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              path === l.href
                ? "bg-indigo-600 text-white"
                : "text-slate-400 hover:text-white"
            }`}
          >
            {l.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
