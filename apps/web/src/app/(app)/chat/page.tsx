"use client";

import { Suspense } from "react";

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
import { formatRelative } from "@/lib/format";
import { useConversations } from "@/lib/queries";
import { useUrlState } from "@/lib/useUrlState";

const FILTERS = [
  { value: "all", label: "Tutte" },
  { value: "unread", label: "Non lette" },
  { value: "with_order", label: "Con ordine" },
] as const;
type Filter = (typeof FILTERS)[number]["value"];

function Inbox() {
  const [filter, setFilter] = useUrlState<Filter>("filter", "all", FILTERS.map((f) => f.value));
  const [q, setQ] = useUrlState<string>("q", "");
  const query = useConversations({ filter, q });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      <PageHeader title="Chat" />
      <SearchInput value={q} onChange={setQ} placeholder="Cerca acquirente, ordine o testo" />
      <FilterChips options={[...FILTERS]} value={filter} onChange={setFilter} />
      {query.isLoading ? (
        <ListSkeleton />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState icon="💬" title="Nessuna conversazione" />
      ) : (
        <ul className="card divide-y divide-slate-100 dark:divide-slate-800" data-testid="conversations-list">
          {items.map((c) => (
            <li key={c.id}>
              <RowLink href={`/chat/${c.id}`}>
                <Avatar name={c.buyer_name} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className={`truncate ${c.unread ? "font-bold" : "font-semibold"}`}>{c.buyer_name}</span>
                    <span className={`shrink-0 text-xs ${c.unread ? "font-semibold text-brand-600" : "text-slate-500"}`}>
                      {formatRelative(c.last_message_at)}
                    </span>
                  </div>
                  {c.order && <p className="text-xs text-slate-500">Ordine #{c.order.cardmarket_id}</p>}
                  <div className="flex items-center gap-2">
                    <p className={`truncate text-sm ${c.unread ? "text-slate-900 dark:text-white" : "text-slate-500"}`}>
                      {c.last_message_preview ? `“${c.last_message_preview}”` : "—"}
                    </p>
                    {c.unread && <span className="size-2.5 shrink-0 rounded-full bg-brand-600" aria-label="non letta" />}
                  </div>
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

export default function ChatPage() {
  return (
    <Suspense>
      <Inbox />
    </Suspense>
  );
}
