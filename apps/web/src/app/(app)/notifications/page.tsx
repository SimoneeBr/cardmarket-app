"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { EmptyState, ErrorState, ListSkeleton, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { NOTIFICATION_TYPE } from "@/lib/labels";
import { keys, useNotifications } from "@/lib/queries";

export default function NotificationsPage() {
  const client = useQueryClient();
  const { data, error, isLoading, refetch } = useNotifications();
  const refresh = () => void client.invalidateQueries({ queryKey: keys.notifications });
  const readOne = useMutation({ mutationFn: (id: number) => api.post(`/notifications/${id}/read`), onSuccess: refresh });
  const readAll = useMutation({ mutationFn: () => api.post("/notifications/read-all"), onSuccess: refresh });
  const clear = useMutation({ mutationFn: () => api.delete("/notifications"), onSuccess: refresh });
  const unread = data?.items.filter((n) => !n.read).length ?? 0;

  return (
    <div>
      <PageHeader
        title="Notifiche"
        subtitle={data ? `${unread} non lette` : undefined}
        back="/"
      />
      <div className="mb-3 flex gap-2">
        <button className="btn-secondary flex-1" onClick={() => readAll.mutate()} disabled={!unread}>
          Segna tutte come lette
        </button>
        <button className="btn-secondary flex-1" onClick={() => clear.mutate()} disabled={!data?.items.some((n) => n.read)}>
          Elimina lette
        </button>
      </div>
      {isLoading ? (
        <ListSkeleton />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : !data?.items.length ? (
        <EmptyState icon="🔔" title="Nessuna notifica" hint="Configura cosa ricevere in Impostazioni → Notifiche." />
      ) : (
        <ul className="card divide-y divide-slate-100 dark:divide-slate-800" data-testid="notifications-list">
          {data.items.map((n) => (
            <li key={n.id} className={n.read ? "" : "bg-brand-50/60 dark:bg-slate-800/40"}>
              <Link
                href={n.link}
                onClick={() => !n.read && readOne.mutate(n.id)}
                className="flex items-start gap-3 px-4 py-3"
              >
                <span className="text-xl">{NOTIFICATION_TYPE[n.type].icon}</span>
                <div className="min-w-0 flex-1">
                  <p className={`text-sm ${n.read ? "" : "font-semibold"}`}>{n.title}</p>
                  {n.body && <p className="truncate text-sm text-slate-500">{n.body}</p>}
                </div>
                <span className="shrink-0 text-xs text-slate-500">{formatRelative(n.created_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
