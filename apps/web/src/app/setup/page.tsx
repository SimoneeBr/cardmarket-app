"use client";

import type { Me } from "@cmc/types";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { keys, useSetupStatus } from "@/lib/queries";
import { Logo } from "@/components/Logo";

function Step({ n, title, done, children }: { n: number; title: string; done?: boolean; children?: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        className={`grid size-7 shrink-0 place-items-center rounded-full text-sm font-bold ${
          done ? "bg-emerald-600 text-white" : "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
        }`}
      >
        {done ? "✓" : n}
      </span>
      <div className="min-w-0 flex-1 pb-4">
        <p className="font-semibold">{title}</p>
        {children && <div className="mt-1 text-sm text-slate-600 dark:text-slate-400">{children}</div>}
      </div>
    </li>
  );
}

export default function SetupPage() {
  const router = useRouter();
  const client = useQueryClient();
  const { data: status, refetch } = useSetupStatus();
  const [form, setForm] = useState({ name: "", email: "", password: "", setup_token: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function createAdmin(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api.post<Me>("/setup/admin", {
        ...form,
        setup_token: form.setup_token || null,
      });
      client.setQueryData(keys.me, me);
      await refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Creazione non riuscita");
    } finally {
      setBusy(false);
    }
  }

  const adminDone = status ? !status.needs_admin : false;

  return (
    <div className="mx-auto max-w-lg p-4 pt-10">
      <div className="mb-6 flex items-center gap-3">
        <Logo size={48} />
        <div>
          <h1 className="text-2xl font-bold">Benvenuto in Cardmarket Companion</h1>
          <p className="text-sm text-slate-500">Configurazione iniziale</p>
        </div>
      </div>
      <ol className="card p-5">
        <Step n={1} title="Crea l'amministratore" done={adminDone}>
          {!adminDone && status?.web_setup === "disabled" && (
            <p className="mt-2">
              In produzione l&apos;amministratore si crea dal server:{" "}
              <code className="text-xs">python -m app.scripts.create_admin --email …</code> (vedi
              docs/deployment.md).
            </p>
          )}
          {!adminDone && status?.web_setup !== "disabled" && (
            <form onSubmit={createAdmin} className="mt-3 space-y-3">
              {status?.web_setup === "token" && (
                <input className="input" placeholder="Codice di setup (SETUP_TOKEN)" autoComplete="off" required value={form.setup_token} onChange={(e) => setForm({ ...form, setup_token: e.target.value })} aria-label="Codice di setup" />
              )}
              <input className="input" placeholder="Nome" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="Nome" />
              <input className="input" type="email" placeholder="Email" autoComplete="username" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} aria-label="Email" />
              <input className="input" type="password" placeholder="Password (min. 10 caratteri)" autoComplete="new-password" minLength={10} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} aria-label="Password" />
              {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
              <button className="btn-primary w-full" disabled={busy}>
                {busy ? "Creazione…" : "Crea amministratore"}
              </button>
            </form>
          )}
        </Step>
        <Step n={2} title="Database configurato" done>
          Migrazioni applicate all&apos;avvio del servizio API.
        </Step>
        <Step n={3} title="Avvia il Cardmarket Agent" done={status?.agent_online}>
          {status?.agent_online
            ? `Agent attivo (${status.mock_mode ? "modalità MOCK" : "Cardmarket reale"}).`
            : "In attesa dell'agent… (docker compose up agent)"}
        </Step>
        <Step n={4} title="Collega l'account Cardmarket" done={status?.connection_status === "CONNECTED"}>
          {adminDone ? (
            <Link className="font-semibold text-brand-600" href="/settings/connection">
              Apri la procedura di collegamento →
            </Link>
          ) : (
            "Disponibile dopo aver creato l'amministratore."
          )}
        </Step>
        <Step n={5} title="Attiva le notifiche">
          {adminDone ? (
            <Link className="font-semibold text-brand-600" href="/settings/notifications">
              Configura le notifiche →
            </Link>
          ) : (
            "Facoltativo."
          )}
        </Step>
      </ol>
      {adminDone && (
        <button className="btn-primary mt-4 w-full" onClick={() => router.push("/")}>
          Vai alla dashboard
        </button>
      )}
    </div>
  );
}
