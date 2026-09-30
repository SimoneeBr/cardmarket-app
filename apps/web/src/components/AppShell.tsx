"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useDashboard, useUnreadCount } from "@/lib/queries";
import { Logo } from "@/components/Logo";

const NAV = [
  { href: "/", label: "Home", icon: "🏠", match: (p: string) => p === "/" },
  { href: "/orders", label: "Ordini", icon: "📦", match: (p: string) => p.startsWith("/orders") },
  { href: "/chat", label: "Chat", icon: "💬", match: (p: string) => p.startsWith("/chat") },
  { href: "/carts", label: "Carrelli", icon: "🛒", match: (p: string) => p.startsWith("/carts") },
  { href: "/settings", label: "Impostazioni", icon: "⚙️", match: (p: string) => p.startsWith("/settings") },
] as const;

function Counter({ value }: { value?: number }) {
  if (!value) return null;
  return (
    <span className="absolute -top-1 -right-2 min-w-5 rounded-full bg-red-600 px-1 text-center text-[10px] leading-5 font-bold text-white">
      {value > 99 ? "99+" : value}
    </span>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: dashboard } = useDashboard();
  const { data: unread } = useUnreadCount();
  const badges: Record<string, number | undefined> = {
    "/orders": dashboard?.orders.new,
    "/chat": dashboard?.messages.unread_conversations,
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-6xl">
      {/* Desktop / tablet sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-slate-200 p-4 md:flex dark:border-slate-800">
        <Link href="/" className="mb-6 flex items-center gap-2 px-2 font-bold">
          <Logo size={32} />
          <span>CM Companion</span>
        </Link>
        <nav className="flex flex-1 flex-col gap-1" aria-label="Principale">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={item.match(pathname) ? "page" : undefined}
              className={`relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium ${
                item.match(pathname)
                  ? "bg-brand-50 text-brand-700 dark:bg-slate-800 dark:text-white"
                  : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900"
              }`}
            >
              <span className="relative text-lg">
                {item.icon}
                <Counter value={badges[item.href]} />
              </span>
              {item.label}
            </Link>
          ))}
        </nav>
        <Link
          href="/notifications"
          className="relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900"
        >
          <span className="relative text-lg">
            🔔
            <Counter value={unread?.unread} />
          </span>
          Notifiche
        </Link>
      </aside>

      <div className="min-w-0 flex-1">
        {/* Mobile top-right bell */}
        <Link
          href="/notifications"
          aria-label="Notifiche"
          className="pt-safe fixed top-2 right-3 z-30 grid size-11 place-items-center rounded-full bg-white/90 text-lg shadow-sm ring-1 ring-slate-200 backdrop-blur md:hidden dark:bg-slate-900/90 dark:ring-slate-800"
        >
          <span className="relative">
            🔔
            <Counter value={unread?.unread} />
          </span>
        </Link>
        <main className="px-4 pb-28 md:px-8 md:pt-6 md:pb-10">{children}</main>
      </div>

      {/* Mobile bottom navigation: one-hand friendly */}
      <nav
        aria-label="Principale"
        className="pb-safe fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-slate-200 bg-white/95 backdrop-blur md:hidden dark:border-slate-800 dark:bg-slate-950/95"
      >
        {NAV.map((item) => {
          const active = item.match(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex flex-col items-center gap-0.5 pt-2 text-[11px] font-medium ${
                active ? "text-brand-600 dark:text-brand-100" : "text-slate-500"
              }`}
            >
              <span className="relative text-xl leading-none">
                {item.icon}
                <Counter value={badges[item.href]} />
              </span>
              {item.label === "Impostazioni" ? "Altro" : item.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
