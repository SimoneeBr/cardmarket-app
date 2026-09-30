"use client";

import type { ActionBrief, Connection } from "@cmc/types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConnectionLine } from "@/components/ConnectionBanner";
import { ActionStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { ConfirmButton, ErrorState, KeyValue, PageHeader, Section, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatAgo, formatDateTime } from "@/lib/format";
import { ERROR_CODE } from "@/lib/labels";
import { invalidateCommerce, keys, useConnection, useMe } from "@/lib/queries";

function PairingInstructions({ connection }: { connection: Connection }) {
  if (connection.mock_mode) {
    return (
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Modalità <b>MOCK</b>: il login manuale (con eventuale 2FA) viene simulato dall&apos;agent in pochi secondi.
      </p>
    );
  }
  return (
    <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-400">
      <li>Premi &quot;Avvia collegamento&quot;: l&apos;agent apre Cardmarket in un browser dedicato.</li>
      <li>
        Apri il browser remoto dell&apos;agent
        {connection.pairing_viewer_url ? (
          <>
            {" "}
            (
            <a className="font-semibold text-brand-600 underline" href={connection.pairing_viewer_url} target="_blank" rel="noreferrer noopener">
              apri viewer
            </a>
            )
          </>
        ) : (
          " (vedi docs/cardmarket-agent.md)"
        )}
        .
      </li>
      <li>Esegui tu il login su Cardmarket e completa la 2FA se richiesta.</li>
      <li>L&apos;agent rileva il login, salva la sessione nel profilo persistente e passa a CONNECTED.</li>
    </ol>
  );
}

export default function ConnectionPage() {
  const client = useQueryClient();
  const toast = useToast();
  const { data: me } = useMe();
  const { data: connection, error, isLoading, refetch } = useConnection({ fast: true });

  const run = useMutation({
    mutationFn: ({ path }: { path: string }) => api.post<ActionBrief | Connection>(path),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.connection });
      invalidateCommerce(client);
    },
    onError: (err) => toast(err instanceof ApiError ? err.message : "Errore", "error"),
  });
  const simulate = useMutation({
    mutationFn: (scenario: string) => api.post("/admin/simulate", { scenario }),
    onSuccess: () => toast("Simulazione inviata all'agent", "success"),
    onError: (err) => toast(err instanceof ApiError ? err.message : "Errore", "error"),
  });

  if (isLoading) return <Spinner />;
  if (error || !connection) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const isAdmin = me?.permissions.includes("MANAGE_CONNECTION");
  const canSync = me?.permissions.includes("TRIGGER_SYNC");
  const pending = connection.pending_session_action;

  return (
    <div>
      <PageHeader back="/settings" title="Connessione Cardmarket" />
      <div className="card mb-4 p-4" data-testid="connection-status" data-status={connection.status}>
        <ConnectionLine connection={connection} />
        <div className="mt-3 divide-y divide-slate-100 dark:divide-slate-800">
          <KeyValue label="Ultima sincronizzazione">{formatAgo(connection.last_successful_sync)}</KeyValue>
          <KeyValue label="Ultima autenticazione">{formatDateTime(connection.last_authentication)}</KeyValue>
          <KeyValue label="Sessione">{connection.session_paired_at ? `collegata il ${formatDateTime(connection.session_paired_at)}` : "non collegata"}</KeyValue>
          <KeyValue label="Agent">
            {connection.agent_online ? "online" : "offline"} {connection.agent_version && `· v${connection.agent_version}`}{" "}
            {connection.agent_mode && `· ${connection.agent_mode}`}
          </KeyValue>
          <KeyValue label="Ultimo contatto agent">{formatAgo(connection.agent_last_seen_at)}</KeyValue>
          {connection.sync_running && <KeyValue label="Sincronizzazione">in corso…</KeyValue>}
        </div>
        {connection.last_error && connection.status !== "CONNECTED" && (
          <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200" role="alert">
            <p className="font-semibold">{connection.last_error_code ? ERROR_CODE[connection.last_error_code] : "Errore"}</p>
            <p>{connection.last_error}</p>
            <p className="mt-1 text-xs opacity-75">{formatDateTime(connection.last_error_at)}</p>
            {connection.last_error_code === "ACCESS_BLOCKED" && (
              <p className="mt-2" data-testid="access-blocked-hint">
                L&apos;agent ha sospeso ogni navigazione automatica verso Cardmarket. Verifica
                prima l&apos;accesso da un browser normale; poi usa &quot;Riconnetti&quot; per un
                solo controllo esplicito della sessione.
              </p>
            )}
          </div>
        )}
      </div>

      {pending && (
        <div className="card mb-4 flex items-center justify-between p-4" data-testid="session-action">
          <span className="text-sm font-medium">{pending.type === "PAIR_SESSION" ? "Collegamento in corso" : "Verifica sessione in corso"}</span>
          <ActionStatusBadge status={pending.status} />
        </div>
      )}

      {isAdmin && (
        <Section title="Collegamento">
          <div className="card space-y-4 p-4">
            <PairingInstructions connection={connection} />
            <div className="grid gap-2 sm:grid-cols-2">
              <button className="btn-primary" disabled={Boolean(pending) || run.isPending} onClick={() => run.mutate({ path: "/connection/pair" })}>
                🔐 Avvia collegamento
              </button>
              <button className="btn-secondary" disabled={Boolean(pending) || run.isPending} onClick={() => run.mutate({ path: "/connection/reconnect" })}>
                🔄 Riconnetti (verifica sessione)
              </button>
            </div>
            <p className="text-xs text-slate-500">
              La password Cardmarket non viene mai chiesta né salvata dall&apos;app: la sessione resta nel profilo del browser dell&apos;agent.
            </p>
          </div>
        </Section>
      )}

      {(canSync || isAdmin) && (
        <Section title="Azioni">
          <div className="grid gap-2 sm:grid-cols-2">
            {canSync && (
              <button className="btn-secondary" onClick={() => run.mutate({ path: "/connection/sync-now" })}>
                ⚡ Sincronizza ora
              </button>
            )}
            {isAdmin && connection.status !== "DISCONNECTED" && (
              <ConfirmButton label="⏏︎ Disconnetti" confirmLabel="Confermi disconnessione?" onConfirm={() => run.mutate({ path: "/connection/disconnect" })} />
            )}
          </div>
        </Section>
      )}

      {isAdmin && connection.mock_mode && (
        <Section title="Simulazioni (solo MOCK)">
          <div className="grid gap-2 sm:grid-cols-3">
            <button className="btn-secondary" onClick={() => simulate.mutate("session_expired")} data-testid="simulate-session-expired">
              Sessione scaduta
            </button>
            <button className="btn-secondary" onClick={() => simulate.mutate("sync_error")} data-testid="simulate-sync-error">
              Errore di sync
            </button>
            <button className="btn-secondary" onClick={() => simulate.mutate("new_activity")} data-testid="simulate-activity">
              Nuova attività
            </button>
          </div>
        </Section>
      )}
    </div>
  );
}
