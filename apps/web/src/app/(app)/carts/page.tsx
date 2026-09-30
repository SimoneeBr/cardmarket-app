"use client";

import { Suspense } from "react";

import { CartStatusBadge } from "@/components/StatusBadges";
import {
  Avatar,
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
import { useCarts } from "@/lib/queries";
import { useUrlState } from "@/lib/useUrlState";

const FILTERS = [
  { value: "all", label: "Tutti" },
  { value: "to_pay", label: "Da pagare" },
  { value: "paid", label: "Pagati" },
  { value: "completed", label: "Completati" },
  { value: "cancelled", label: "Annullati" },
] as const;
type Filter = (typeof FILTERS)[number]["value"];

function CartsList() {
  const [filter, setFilter] = useUrlState<Filter>("filter", "all", FILTERS.map((f) => f.value));
  const [q, setQ] = useUrlState<string>("q", "");
  const query = useCarts({ filter, q });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      <PageHeader title="Carrelli" subtitle={query.data ? `${query.data.pages[0]?.total ?? 0} carrelli` : undefined} />
      <SearchInput value={q} onChange={setQ} placeholder="Cerca acquirente o carrello" />
      <FilterChips options={[...FILTERS]} value={filter} onChange={setFilter} />
      {query.isLoading ? (
        <ListSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState icon="🛒" title="Nessun carrello" />
      ) : (
        <ul className="card divide-y divide-slate-100 dark:divide-slate-800" data-testid="carts-list">
          {items.map((cart) => (
            <li key={cart.id}>
              <RowLink href={`/carts/${cart.id}`}>
                <Avatar name={cart.buyer_name} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{cart.buyer_name}</p>
                  <p className="text-sm text-slate-500">
                    {cart.item_count ?? "?"} articoli · {formatRelative(cart.cardmarket_created_at ?? cart.created_at)}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="font-semibold tabular-nums">{formatMoney(cart.total_amount, cart.currency)}</span>
                  <CartStatusBadge status={cart.status} />
                </div>
              </RowLink>
            </li>
          ))}
        </ul>
      )}
      <LoadMore hasMore={Boolean(query.hasNextPage)} loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()} />
    </div>
  );
}

export default function CartsPage() {
  return (
    <Suspense>
      <CartsList />
    </Suspense>
  );
}
