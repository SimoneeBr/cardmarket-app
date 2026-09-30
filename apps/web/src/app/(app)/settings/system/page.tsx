"use client";

import type { RuntimeSettings } from "@cmc/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { ErrorState, PageHeader, Section, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { invalidateCommerce } from "@/lib/queries";

const PURGE_PHRASE = "ELIMINA DATI";

export default function SystemPage() {
  const settings = useQuery({ queryKey: ["runtime-settings"], queryFn: () => api.get<RuntimeSettings>("/admin/settings") });
  if (settings.error) return <ErrorState error={settings.error} />;
  if (!settings.data) return <Spinner />;
  return <SystemForm initial={settings.data} />;
}

function SystemForm({ initial }: { initial: RuntimeSettings }) {
  const client = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<RuntimeSettings>(initial);
  const [phrase, setPhrase] = useState("");
  const onError = (err: unknown) => toast(err instanceof ApiError ? err.message : "Errore", "error");

  const save = useMutation({
    mutationFn: (value: RuntimeSettings) => api.put<RuntimeSettings>("/admin/settings", value),
    onSuccess: (data) => {
      client.setQueryData(["runtime-settings"], data);
      toast("Impostazioni salvate", "success");
    },
    onError,
  });
  const retention = useMutation({
    mutationFn: () => api.post<Record<string, number>>("/admin/retention/run"),
    onSuccess: (data) => toast(`Retention applicata: ${Object.values(data).reduce((a, b) => a + b, 0)} record rimossi`, "success"),
    onError,
  });
  const purge = useMutation({
    mutationFn: () => api.post<Record<string, number>>("/admin/data/purge", { confirm: phrase }),
    onSuccess: () => {
      setPhrase("");
      invalidateCommerce(client);
      toast("Dati locali eliminati. Verranno reimportati alla prossima sincronizzazione.", "success");
    },
    onError,
  });

  return (
    <div>
      <PageHeader back="/settings" title="Sistema e privacy" />
      <Section title="Sincronizzazione">
        <form className="card space-y-3 p-4" onSubmit={(e) => { e.preventDefault(); save.mutate(form); }}>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.sync_enabled} onChange={(e) => setForm({ ...form, sync_enabled: e.target.checked })} />
            Sincronizzazione automatica attiva
          </label>
          <div>
            <label className="label" htmlFor="interval">Intervallo (secondi, 10–3600)</label>
            <input id="interval" className="input" type="number" min={10} max={3600} value={form.sync_interval_seconds} onChange={(e) => setForm({ ...form, sync_interval_seconds: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label" htmlFor="shop">Nome negozio (variabile {"{{shop_name}}"})</label>
            <input id="shop" className="input" maxLength={80} value={form.shop_name} onChange={(e) => setForm({ ...form, shop_name: e.target.value })} />
          </div>
          <button className="btn-primary w-full" disabled={save.isPending}>Salva</button>
        </form>
      </Section>
      <Section title="Privacy e dati locali">
        <div className="card space-y-4 p-4 text-sm">
          <p className="text-slate-600 dark:text-slate-400">
            I dati di ordini e messaggi dei clienti sono conservati solo per il tempo configurato (variabili RETENTION_*). Nessun servizio di analytics di terze parti è attivo.
          </p>
          <button className="btn-secondary w-full" onClick={() => retention.mutate()}>Applica retention ora</button>
          <div className="rounded-xl border border-red-200 p-3 dark:border-red-900">
            <p className="font-semibold text-red-700 dark:text-red-400">Elimina tutti i dati locali di Cardmarket</p>
            <p className="mb-2 text-slate-500">Ordini, conversazioni, carrelli e notifiche vengono cancellati da questo database. Cardmarket non viene modificato. Digita <b>{PURGE_PHRASE}</b> per confermare.</p>
            <input className="input mb-2" value={phrase} aria-label="Conferma eliminazione" onChange={(e) => setPhrase(e.target.value)} />
            <button className="btn-danger w-full" disabled={phrase !== PURGE_PHRASE || purge.isPending} onClick={() => purge.mutate()}>Elimina dati locali</button>
          </div>
        </div>
      </Section>
    </div>
  );
}
