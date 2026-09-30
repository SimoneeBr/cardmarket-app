"use client";

import { Suspense } from "react";

import { OrderStatusBadge } from "@/components/StatusBadges";
import {
  Avatar,
  Badge,
  EmptyState,
  ErrorState,
  FilterChips,
  ListSkeleton,
  LoadMore,
  PageHeader,
  RowLink,
  SearchInput,
} from "@/components/ui";
import { formatMoney, formatRelative } from "@/lib/format";
import { useOrders } from "@/lib/queries";
import { useUrlState } from "@/lib/useUrlState";

const FILTERS = [
  { value: "all", label: "Tutti" },
  { value: "new", label: "Nuovi" },
  { value: "to_ship", label: "Da spedire" },
  { value: "paid", label: "Pagati" },
  { value: "unpaid", label: "Non pagati" },
  { value: "shipped", label: "Spediti" },
  { value: "completed", label: "Completati" },
  { value: "cancelled", label: "Annullati" },
] as const;
type Filter = (typeof FILTERS)[number]["value"];

const SORTS = [
  { value: "date_desc", label: "Più recenti" },
  { value: "date_asc", label: "Meno recenti" },
  { value: "total_desc", label: "Totale ↓" },
  { value: "total_asc", label: "Totale ↑" },
  { value: "buyer", label: "Acquirente A-Z" },
] as const;
type Sort = (typeof SORTS)[number]["value"];

function OrdersList() {
  const [filter, setFilter] = useUrlState<Filter>("filter", "all", FILTERS.map((f) => f.value));
  const [sort, setSort] = useUrlState<Sort>("sort", "date_desc", SORTS.map((s) => s.value));
  const [q, setQ] = useUrlState<string>("q", "");
  const query = useOrders({ filter, q, sort });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total;

  return (
    <div>
      <PageHeader
        title="Ordini"
        subtitle={total !== undefined ? `${total} ordini` : undefined}
        action={
          <select
            aria-label="Ordinamento"
            className="input w-auto min-w-0 py-1 text-sm"
            value={sort}
            onChange={(e) => setSort(e.target.value as Sort)}
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        }
      />
      <SearchInput value={q} onChange={setQ} placeholder="Cerca acquirente, n° ordine o carta" />
      <FilterChips options={[...FILTERS]} value={filter} onChange={setFilter} />

      {query.isLoading ? (
        <ListSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState icon="📦" title="Nessun ordine" hint="Prova a cambiare filtro o ricerca." />
      ) : (
        <ul className="card divide-y divide-slate-100 dark:divide-slate-800" data-testid="orders-list">
          {items.map((order) => (
            <li key={order.id}>
              <RowLink href={`/orders/${order.id}`}>
                <Avatar name={order.buyer_name} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-semibold">{order.buyer_name}</span>
                    {order.is_new && <Badge tone="danger">Nuovo</Badge>}
                  </div>
                  <div className="flex items-center gap-2 text-sm text-slate-500">
                    <span>#{order.cardmarket_id}</span>
                    <span>·</span>
                    <span>{order.item_count ?? "?"} art.</span>
                    <span>·</span>
                    <span>{formatRelative(order.order_date)}</span>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="font-semibold tabular-nums">
                    {formatMoney(order.total_amount, order.currency)}
                  </span>
                  <OrderStatusBadge status={order.status} />
                </div>
              </RowLink>
            </li>
          ))}
        </ul>
      )}
      <LoadMore
        hasMore={Boolean(query.hasNextPage)}
        loading={query.isFetchingNextPage}
        onClick={() => void query.fetchNextPage()}
      />
    </div>
  );
}

export default function OrdersPage() {
  return (
    <Suspense>
      <OrdersList />
    </Suspense>
  );
}
