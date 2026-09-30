"use client";

import Link from "next/link";

import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ErrorState, Section, Spinner } from "@/components/ui";
import { formatMoney, formatTime, formatRelative } from "@/lib/format";
import { useDashboard } from "@/lib/queries";

function Stat({
  href,
  icon,
  value,
  label,
  highlight,
  testId,
}: {
  href: string;
  icon: string;
  value: number | string;
  label: string;
  highlight?: "red" | "orange" | "blue";
  testId?: string;
}) {
  const ring =
    highlight === "red"
      ? "ring-2 ring-red-400/60"
      : highlight === "orange"
        ? "ring-2 ring-amber-400/60"
        : highlight === "blue"
          ? "ring-2 ring-brand-500/40"
          : "";
  return (
    <Link
      href={href}
      data-testid={testId}
      className={`card flex flex-col gap-1 p-4 transition active:scale-[0.98] ${ring}`}
    >
      <span className="text-xl">{icon}</span>
      <span className="text-2xl font-bold tabular-nums md:text-3xl">{value}</span>
      <span className="text-sm text-slate-500">{label}</span>
    </Link>
  );
}

export default function DashboardPage() {
  const { data, error, isLoading, refetch } = useDashboard();

  if (isLoading) return <Spinner />;
  if (error || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const primarySales = data.sales.by_currency[0];
  const attention =
    data.attention.failed_syncs_24h +
    data.attention.actions_needing_attention +
    data.attention.failed_actions_24h;

  return (
    <div>
      <header className="pt-safe flex min-h-14 items-center pr-12 md:pr-0">
        <h1 className="text-xl font-bold md:text-2xl">Cardmarket Companion</h1>
      </header>

      <ConnectionBanner />

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat testId="stat-new" href="/orders?filter=new" icon="🔴" value={data.orders.new} label="Nuovi ordini" highlight={data.orders.new ? "red" : undefined} />
        <Stat testId="stat-to-ship" href="/orders?filter=to_ship" icon="🟠" value={data.orders.to_ship} label="Da spedire" highlight={data.orders.to_ship ? "orange" : undefined} />
        <Stat testId="stat-unread" href="/chat?filter=unread" icon="💬" value={data.messages.unread_conversations} label="Chat non lette" highlight={data.messages.unread_conversations ? "blue" : undefined} />
        <Stat testId="stat-unpaid" href="/orders?filter=unpaid" icon="⏳" value={data.orders.unpaid} label="In attesa di pagamento" />
      </div>

      <div className="mb-5 grid gap-3 md:grid-cols-3">
        <Link href="/carts" className="card p-4" data-testid="carts-summary">
          <p className="mb-2 text-sm font-semibold text-slate-500">🛒 Carrelli</p>
          <div className="flex gap-6">
            <div>
              <p className="text-2xl font-bold tabular-nums">{data.carts.to_pay}</p>
              <p className="text-sm text-slate-500">da pagare</p>
            </div>
            <div>
              <p className="text-2xl font-bold tabular-nums">{data.carts.paid}</p>
              <p className="text-sm text-slate-500">pagati</p>
            </div>
          </div>
        </Link>
        <Link href="/orders?filter=paid" className="card p-4">
          <p className="mb-2 text-sm font-semibold text-slate-500">
            💰 Vendite ultimi {data.sales.window_days} giorni
          </p>
          <p className="text-2xl font-bold tabular-nums">
            {primarySales ? formatMoney(primarySales.total, primarySales.currency) : formatMoney(0)}
          </p>
          <p className="text-sm text-slate-500">
            {primarySales?.orders ?? 0} ordini · {data.orders.paid_24h} pagati nelle ultime 24h
          </p>
        </Link>
        <Link
          href="/settings/operations"
          className={`card p-4 ${attention ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/50" : ""}`}
          data-testid="attention"
        >
          <p className="mb-2 text-sm font-semibold text-slate-500">⚠️ Richiede attenzione</p>
          {attention ? (
            <ul className="space-y-0.5 text-sm">
              {data.attention.failed_syncs_24h > 0 && <li>{data.attention.failed_syncs_24h} errori di sincronizzazione (24h)</li>}
              {data.attention.actions_needing_attention > 0 && <li>{data.attention.actions_needing_attention} azioni da verificare</li>}
              {data.attention.failed_actions_24h > 0 && <li>{data.attention.failed_actions_24h} azioni fallite (24h)</li>}
            </ul>
          ) : (
            <p className="text-sm text-emerald-700 dark:text-emerald-400">Tutto in ordine ✓</p>
          )}
        </Link>
      </div>

      <Section title="Ultime attività">
        {data.activity.length === 0 ? (
          <p className="card p-4 text-sm text-slate-500">Nessuna attività recente.</p>
        ) : (
          <ul className="card divide-y divide-slate-100 dark:divide-slate-800" data-testid="activity">
            {data.activity.map((item) => {
              const inner = (
                <>
                  <span className="w-12 shrink-0 text-xs text-slate-500 tabular-nums" title={formatRelative(item.occurred_at)}>
                    {formatTime(item.occurred_at)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm">{item.title}</span>
                </>
              );
              return (
                <li key={item.id}>
                  {item.link ? (
                    <Link href={item.link} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                      {inner}
                    </Link>
                  ) : (
                    <div className="flex items-center gap-3 px-4 py-3">{inner}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Section>
    </div>
  );
}
