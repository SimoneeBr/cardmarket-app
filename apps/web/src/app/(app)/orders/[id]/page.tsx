"use client";

import type { ActionBrief, OrderDetail } from "@cmc/types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";

import { ActionStatusBadge, OrderStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { Badge, ErrorState, KeyValue, PageHeader, Section, Spinner } from "@/components/ui";
import { api, ApiError, clientKey } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { invalidateCommerce, keys, useMe, useOrder } from "@/lib/queries";

const PAYMENT: Record<string, string> = { PAID: "Pagato", UNPAID: "Non pagato", REFUNDED: "Rimborsato", UNKNOWN: "—" };
const SHIPPING: Record<string, string> = { NOT_SHIPPED: "Non spedito", SHIPPED: "Spedito", DELIVERED: "Consegnato", UNKNOWN: "—" };

function ShipPanel({ order }: { order: OrderDetail }) {
  const client = useQueryClient();
  const toast = useToast();
  const [tracking, setTracking] = useState("");
  const key = useRef(clientKey());
  const ship = useMutation({
    mutationFn: () =>
      api.post<ActionBrief>(`/orders/${order.id}/ship`, {
        tracking_number: tracking.trim() || null,
        client_key: key.current,
      }),
    onSuccess: () => {
      toast("Spedizione in coda: verrà confermata su Cardmarket", "success");
      void client.invalidateQueries({ queryKey: keys.order(order.id) });
    },
    onError: (err) => toast(err instanceof ApiError ? err.message : "Errore", "error"),
  });

  if (order.pending_action) {
    return (
      <div className="card p-4" data-testid="ship-pending">
        <div className="flex items-center justify-between">
          <p className="font-semibold">Segna come spedito</p>
          <ActionStatusBadge status={order.pending_action.status} />
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {order.pending_action.status === "NEEDS_ATTENTION"
            ? "L'esito su Cardmarket non è verificabile: controlla manualmente dalla sezione Operazioni."
            : "L'agent sta eseguendo l'operazione su Cardmarket e ne verificherà l'esito."}
        </p>
      </div>
    );
  }
  if (order.status !== "PAID") return null;
  return (
    <form
      className="card space-y-3 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        ship.mutate();
      }}
    >
      <p className="font-semibold">Segna come spedito</p>
      <input
        className="input"
        placeholder="Numero di tracking (facoltativo)"
        aria-label="Numero di tracking"
        value={tracking}
        onChange={(e) => setTracking(e.target.value)}
        maxLength={80}
      />
      <button className="btn-primary w-full" disabled={ship.isPending}>
        🚚 Conferma spedizione
      </button>
    </form>
  );
}

export default function OrderDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const orderId = Number(id);
  const client = useQueryClient();
  const { data: me } = useMe();
  const { data: order, error, isLoading, refetch } = useOrder(orderId);
  const acknowledged = useRef(false);

  useEffect(() => {
    if (order?.is_new && !acknowledged.current) {
      acknowledged.current = true;
      void api.post<OrderDetail>(`/orders/${orderId}/acknowledge`).then((updated) => {
        client.setQueryData(keys.order(orderId), updated);
        invalidateCommerce(client);
      });
    }
  }, [order?.is_new, orderId, client]);

  if (isLoading) return <Spinner />;
  if (error || !order) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const canShip = me?.permissions.includes("UPDATE_ORDER");
  const conversation = order.conversations[0];

  return (
    <div>
      <PageHeader back="/orders" title={`Ordine #${order.cardmarket_id}`} subtitle={order.buyer_name} />

      <div className="card mb-4 p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-2xl font-bold tabular-nums">{formatMoney(order.total_amount, order.currency)}</span>
          <OrderStatusBadge status={order.status} />
        </div>
        <KeyValue label="Acquirente">{order.buyer_name}</KeyValue>
        <KeyValue label="Data ordine">{formatDateTime(order.order_date)}</KeyValue>
        <KeyValue label="Pagamento">
          {PAYMENT[order.payment_status]} {order.paid_at && <span className="text-slate-500">· {formatDateTime(order.paid_at)}</span>}
        </KeyValue>
        <KeyValue label="Spedizione">
          {SHIPPING[order.shipping_status]} {order.shipped_at && <span className="text-slate-500">· {formatDateTime(order.shipped_at)}</span>}
        </KeyValue>
        {order.tracking_number && <KeyValue label="Tracking">{order.tracking_number}</KeyValue>}
        <KeyValue label="Articoli">{order.item_count ?? "—"}</KeyValue>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3">
        {conversation ? (
          <Link href={`/chat/${conversation.id}`} className="btn-secondary">
            💬 Chat {conversation.unread && <Badge tone="danger">nuovo</Badge>}
          </Link>
        ) : (
          <span className="btn-secondary opacity-60">Nessuna chat</span>
        )}
        {order.raw_source_reference?.startsWith("http") ? (
          <a href={order.raw_source_reference} target="_blank" rel="noreferrer noopener" className="btn-secondary">
            ↗ Cardmarket
          </a>
        ) : (
          <span className="btn-secondary opacity-60">↗ Cardmarket</span>
        )}
      </div>

      {canShip && (
        <div className="mb-4">
          <ShipPanel order={order} />
        </div>
      )}

      <Section title={`Articoli (${order.items.length})`}>
        {order.items.length === 0 ? (
          <p className="card p-4 text-sm text-slate-500">Dettaglio articoli non ancora sincronizzato.</p>
        ) : (
          <ul className="card divide-y divide-slate-100 dark:divide-slate-800" data-testid="order-items">
            {order.items.map((item) => (
              <li key={item.id} className="flex items-start gap-3 px-4 py-3">
                <span className="mt-0.5 w-8 shrink-0 text-sm font-bold tabular-nums">{item.quantity}×</span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{item.card_name}</p>
                  <p className="text-xs text-slate-500">
                    {[item.expansion, item.language, item.condition].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <span className="text-sm tabular-nums">{formatMoney(item.total_price ?? item.unit_price, order.currency)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <p className="text-center text-xs text-slate-400">
        Aggiornato: {formatDateTime(order.detail_fetched_at ?? order.last_seen_at)}
      </p>
    </div>
  );
}
