"use client";

import type { Action, AuditLog, ErrorsReport, Page, SyncRun } from "@cmc/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ActionStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { Badge, ConfirmButton, EmptyState, ErrorState, FilterChips, PageHeader, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { ERROR_CODE } from "@/lib/labels";
import { invalidateCommerce, useMe } from "@/lib/queries";

type Tab = "actions" | "errors" | "sync" | "audit";

const ACTION_LABEL: Record<string, string> = {
  SEND_MESSAGE: "Invio messaggio",
  MARK_ORDER_SHIPPED: "Segna spedito",
  PAIR_SESSION: "Collegamento",
  VERIFY_SESSION: "Verifica sessione",
};

function Artifacts({ names }: { names: string[] }) {
  if (!names.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-2">
      {names.map((n) => (
        <a key={n} className="text-xs font-semibold text-brand-600 underline" href={`/api/admin/artifacts/${encodeURIComponent(n)}`} target="_blank" rel="noreferrer">
          📎 {n.endsWith(".png") ? "screenshot" : n.split(".").pop()}
        </a>
      ))}
    </div>
  );
}

function ActionRow({ action }: { action: Action }) {
  const client = useQueryClient();
  const toast = useToast();
  const { data: me } = useMe();
  const manage = me?.permissions.includes("MANAGE_ACTIONS");
  const op = useMutation({
    mutationFn: (verb: string) => api.post<Action>(`/admin/actions/${action.id}/${verb}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["ops"] });
      invalidateCommerce(client);
    },
    onError: (err) => toast(err instanceof ApiError ? err.message : "Errore", "error"),
  });
  const artifacts = (action.result?.artifacts as string[] | undefined) ?? [];
  return (
    <li className="px-4 py-3" data-testid="action-row" data-status={action.status}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">
          #{action.id} {ACTION_LABEL[action.type] ?? action.type}
        </span>
        <ActionStatusBadge status={action.status} />
      </div>
      <p className="text-xs text-slate-500">
        {formatDateTime(action.created_at)} · tentativi {action.attempts}/{action.max_attempts}
        {action.needs_verification && " · da verificare prima di ripetere"}
      </p>
      {typeof action.payload.body === "string" && <p className="mt-1 truncate text-sm">“{action.payload.body}”</p>}
      {action.last_error && (
        <p className="mt-1 text-sm text-red-700 dark:text-red-400">
          {action.last_error_code && <b>{ERROR_CODE[action.last_error_code]}: </b>}
          {action.last_error}
        </p>
      )}
      <Artifacts names={artifacts} />
      {manage && (action.status === "FAILED" || action.status === "NEEDS_ATTENTION") && (
        <div className="mt-2 flex flex-wrap gap-2">
          <button className="btn-secondary min-h-9 text-xs" onClick={() => op.mutate("retry")}>
            Riprova
          </button>
          {action.status === "NEEDS_ATTENTION" && (
            <ConfirmButton
              className="btn-secondary min-h-9 text-xs"
              label="Verificato: eseguita"
              confirmLabel="Confermi che su Cardmarket è avvenuta?"
              onConfirm={() => op.mutate("resolve")}
            />
          )}
          <ConfirmButton className="btn-secondary min-h-9 text-xs" label="Annulla" confirmLabel="Confermi annullamento?" onConfirm={() => op.mutate("cancel")} />
        </div>
      )}
    </li>
  );
}

function SyncRunRow({ run }: { run: SyncRun }) {
  const tone = run.status === "SUCCESS" ? "success" : run.status === "FAILED" ? "danger" : run.status === "PARTIAL" ? "warning" : "info";
  return (
    <li className="px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">
          {formatDateTime(run.started_at)} <span className="text-xs text-slate-500">({run.trigger})</span>
        </span>
        <Badge tone={tone}>{run.status}</Badge>
      </div>
      <p className="text-xs text-slate-500">
        sync_id {run.sync_id} · trovati {run.records_found} · modificati {run.records_changed}
      </p>
      {run.error && (
        <p className="mt-1 text-sm text-red-700 dark:text-red-400">
          {run.error_code && <b>{ERROR_CODE[run.error_code]}: </b>}
          {run.error}
        </p>
      )}
      <Artifacts names={run.artifacts} />
    </li>
  );
}

function ActionsTab() {
  const [status, setStatus] = useState("");
  const q = useQuery({
    queryKey: ["ops", "actions", status],
    queryFn: () => api.get<Page<Action>>("/admin/actions", { status, limit: 50 }),
    refetchInterval: 5000,
  });
  return (
    <>
      <FilterChips
        options={[
          { value: "", label: "Tutte" },
          { value: "PENDING", label: "In coda" },
          { value: "PROCESSING", label: "In corso" },
          { value: "NEEDS_ATTENTION", label: "Da verificare" },
          { value: "FAILED", label: "Fallite" },
          { value: "SUCCESS", label: "Riuscite" },
        ]}
        value={status}
        onChange={setStatus}
      />
      {q.isLoading ? <Spinner /> : q.error ? <ErrorState error={q.error} /> : !q.data?.items.length ? (
        <EmptyState icon="✅" title="Nessuna azione" />
      ) : (
        <ul className="card divide-y divide-slate-100 dark:divide-slate-800">{q.data.items.map((a) => <ActionRow key={a.id} action={a} />)}</ul>
      )}
    </>
  );
}

function ErrorsTab() {
  const q = useQuery({ queryKey: ["ops", "errors"], queryFn: () => api.get<ErrorsReport>("/admin/errors"), refetchInterval: 10000 });
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorState error={q.error} />;
  const { data } = q;
  return (
    <div className="space-y-4">
      {data.connection_error && (
        <div className="card p-4 text-sm">
          <p className="font-semibold">Connessione: {data.connection_error_code ? ERROR_CODE[data.connection_error_code] : "errore"}</p>
          <p className="text-slate-600 dark:text-slate-400">{data.connection_error}</p>
        </div>
      )}
      <div>
        <p className="mb-2 text-sm font-semibold text-slate-500">Azioni fallite / da verificare</p>
        {data.actions.length ? <ul className="card divide-y divide-slate-100 dark:divide-slate-800">{data.actions.map((a) => <ActionRow key={a.id} action={a} />)}</ul> : <EmptyState icon="✅" title="Nessuna azione in errore" />}
      </div>
      <div>
        <p className="mb-2 text-sm font-semibold text-slate-500">Sincronizzazioni fallite</p>
        {data.sync_runs.length ? <ul className="card divide-y divide-slate-100 dark:divide-slate-800">{data.sync_runs.map((r) => <SyncRunRow key={r.id} run={r} />)}</ul> : <EmptyState icon="✅" title="Nessun errore di sincronizzazione" />}
      </div>
    </div>
  );
}

function SyncTab() {
  const q = useQuery({ queryKey: ["ops", "sync"], queryFn: () => api.get<Page<SyncRun>>("/sync/runs", { limit: 50 }), refetchInterval: 10000 });
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorState error={q.error} />;
  return q.data.items.length ? (
    <ul className="card divide-y divide-slate-100 dark:divide-slate-800">{q.data.items.map((r) => <SyncRunRow key={r.id} run={r} />)}</ul>
  ) : (
    <EmptyState icon="🔄" title="Nessuna sincronizzazione" />
  );
}

function AuditTab() {
  const q = useQuery({ queryKey: ["ops", "audit"], queryFn: () => api.get<Page<AuditLog>>("/admin/audit-logs", { limit: 100 }) });
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorState error={q.error} />;
  return (
    <ul className="card divide-y divide-slate-100 font-mono text-xs dark:divide-slate-800" data-testid="audit-list">
      {q.data.items.map((a) => (
        <li key={a.id} className="px-4 py-2">
          <div className="flex justify-between gap-2">
            <span>{formatDateTime(a.created_at)}</span>
            <span className={a.result === "FAILURE" ? "text-red-600" : a.result === "PENDING" ? "text-amber-600" : "text-emerald-600"}>{a.result}</span>
          </div>
          <div>
            <b>{a.action}</b> · {a.actor}
            {a.entity_type && ` · ${a.entity_type.toLowerCase()} ${a.entity_id ?? ""}`}
          </div>
          {a.error && <div className="text-red-600">{a.error}</div>}
        </li>
      ))}
    </ul>
  );
}

export default function OperationsPage() {
  const [tab, setTab] = useState<Tab>("actions");
  return (
    <div>
      <PageHeader back="/settings" title="Operazioni" />
      <FilterChips<Tab>
        options={[
          { value: "actions", label: "Coda azioni" },
          { value: "errors", label: "Errori" },
          { value: "sync", label: "Sincronizzazioni" },
          { value: "audit", label: "Audit log" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "actions" && <ActionsTab />}
      {tab === "errors" && <ErrorsTab />}
      {tab === "sync" && <SyncTab />}
      {tab === "audit" && <AuditTab />}
    </div>
  );
}
