"use client";

import { use } from "react";

import { CartStatusBadge } from "@/components/StatusBadges";
import { ErrorState, KeyValue, PageHeader, Section, Spinner } from "@/components/ui";
import { formatDateTime, formatMoney } from "@/lib/format";
import { useCart } from "@/lib/queries";

export default function CartDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: cart, error, isLoading, refetch } = useCart(Number(id));
  if (isLoading) return <Spinner />;
  if (error || !cart) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return (
    <div>
      <PageHeader back="/carts" title={`Carrello ${cart.cardmarket_id}`} subtitle={cart.buyer_name} />
      <div className="card mb-4 p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-2xl font-bold tabular-nums">{formatMoney(cart.total_amount, cart.currency)}</span>
          <CartStatusBadge status={cart.status} />
        </div>
        <KeyValue label="Acquirente">{cart.buyer_name}</KeyValue>
        <KeyValue label="Creato">{formatDateTime(cart.cardmarket_created_at ?? cart.created_at)}</KeyValue>
        <KeyValue label="Articoli">{cart.item_count ?? "—"}</KeyValue>
        <KeyValue label="Ultimo aggiornamento">{formatDateTime(cart.last_seen_at)}</KeyValue>
      </div>
      <Section title="Articoli">
        {cart.items.length === 0 ? (
          <p className="card p-4 text-sm text-slate-500">Dettaglio articoli non disponibile.</p>
        ) : (
          <ul className="card divide-y divide-slate-100 dark:divide-slate-800">
            {cart.items.map((item) => (
              <li key={item.id} className="flex items-start gap-3 px-4 py-3">
                <span className="w-8 shrink-0 text-sm font-bold tabular-nums">{item.quantity}×</span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{item.card_name}</p>
                  <p className="text-xs text-slate-500">{[item.expansion, item.language, item.condition].filter(Boolean).join(" · ")}</p>
                </div>
                <span className="text-sm tabular-nums">{formatMoney(item.total_price ?? item.unit_price, cart.currency)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
