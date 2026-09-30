"use client";

import type { ConversationDetail, Message } from "@cmc/types";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useEffect, useRef } from "react";

import { Composer } from "@/components/Composer";
import { OrderStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { ErrorState, PageHeader, Spinner } from "@/components/ui";
import { api, ApiError, clientKey } from "@/lib/api";
import { formatDateTime, formatMoney, formatTime } from "@/lib/format";
import { MESSAGE_STATUS } from "@/lib/labels";
import { invalidateCommerce, keys, useConnection, useConversation, useMe, useTemplates } from "@/lib/queries";

function Bubble({ message, onRetry }: { message: Message; onRetry: (body: string) => void }) {
  const outbound = message.direction === "OUTBOUND";
  const status = MESSAGE_STATUS[message.status];
  return (
    <div className={`flex ${outbound ? "justify-end" : "justify-start"}`} data-testid="message" data-status={message.status}>
      <div
        className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-[15px] leading-snug whitespace-pre-wrap shadow-sm ${
          outbound
            ? "rounded-br-md bg-brand-600 text-white"
            : "rounded-bl-md bg-white text-slate-900 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700"
        } ${message.status === "FAILED" ? "opacity-70" : ""}`}
      >
        {!outbound && <p className="mb-0.5 text-xs font-semibold text-slate-500">{message.sender}</p>}
        {message.body}
        <div className={`mt-1 flex items-center justify-end gap-1.5 text-[11px] ${outbound ? "text-white/75" : "text-slate-400"}`}>
          <span title={formatDateTime(message.sent_at ?? message.created_at)}>
            {formatTime(message.sent_at ?? message.created_at)}
          </span>
          {outbound && message.status !== "SENT" && <span className="font-semibold">· {status.label}</span>}
          {outbound && message.status === "SENT" && <span aria-label="inviato e verificato">✓</span>}
        </div>
        {outbound && message.status === "FAILED" && (
          <button type="button" className="mt-1 text-xs font-semibold underline" onClick={() => onRetry(message.body)}>
            Riprova invio
          </button>
        )}
        {outbound && message.status === "UNKNOWN" && (
          <p className="mt-1 text-[11px] text-white/90">
            Non è stato possibile verificare l&apos;invio: controlla su Cardmarket prima di reinviare.
          </p>
        )}
      </div>
    </div>
  );
}

export default function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const conversationId = Number(id);
  const client = useQueryClient();
  const toast = useToast();
  const { data: me } = useMe();
  const { data: convo, error, isLoading, refetch } = useConversation(conversationId);
  const { data: templates } = useTemplates();
  const { data: connection } = useConnection();
  const bottom = useRef<HTMLDivElement>(null);
  const markedRead = useRef(false);

  useEffect(() => {
    if (convo?.unread && !markedRead.current) {
      markedRead.current = true;
      void api.post(`/conversations/${conversationId}/read`).then(() => invalidateCommerce(client));
    }
  }, [convo?.unread, conversationId, client]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [convo?.messages.length]);

  if (isLoading) return <Spinner />;
  if (error || !convo) return <ErrorState error={error} onRetry={() => void refetch()} />;

  async function send(body: string) {
    try {
      const message = await api.post<Message>(`/conversations/${conversationId}/messages`, {
        body,
        client_key: clientKey(),
      });
      client.setQueryData<ConversationDetail>(keys.conversation(conversationId), (old) =>
        old ? { ...old, messages: [...old.messages.filter((m) => m.id !== message.id), message] } : old,
      );
      void client.invalidateQueries({ queryKey: keys.conversation(conversationId) });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Invio non riuscito", "error");
      throw err;
    }
  }

  const canSend = me?.permissions.includes("SEND_MESSAGE");
  const offline = connection && connection.status !== "CONNECTED";

  return (
    <div className="flex min-h-[calc(100dvh-8rem)] flex-col">
      <PageHeader
        back="/chat"
        title={convo.buyer_name}
        subtitle={
          convo.order ? (
            <Link href={`/orders/${convo.order.id}`} className="inline-flex items-center gap-2 text-brand-600">
              Ordine #{convo.order.cardmarket_id} · {formatMoney(convo.order.total_amount, convo.order.currency)}
              <OrderStatusBadge status={convo.order.status} />
            </Link>
          ) : undefined
        }
      />
      <div className="flex-1 space-y-2 pb-4" data-testid="messages">
        {convo.messages.map((m) => (
          <Bubble key={m.id} message={m} onRetry={(body) => void send(body).catch(() => undefined)} />
        ))}
        <div ref={bottom} />
      </div>
      {canSend && (
        <div className="pb-safe sticky bottom-16 -mx-4 border-t border-slate-200 bg-slate-50/95 px-4 pt-2 backdrop-blur md:bottom-0 dark:border-slate-800 dark:bg-slate-950/95">
          {offline && (
            <p className="mb-2 text-xs text-amber-700 dark:text-amber-400">
              Cardmarket non è connesso: il messaggio resterà in coda finché la connessione non sarà ripristinata.
            </p>
          )}
          <Composer conversationId={conversationId} templates={templates ?? []} onSend={send} />
        </div>
      )}
    </div>
  );
}
