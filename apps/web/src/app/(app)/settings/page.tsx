"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ConnectionLine } from "@/components/ConnectionBanner";
import { PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { ROLE } from "@/lib/labels";
import { useConnection, useMe } from "@/lib/queries";

const SECTIONS = [
  { href: "/settings/connection", icon: "🔌", title: "Connessione Cardmarket", hint: "Stato agent, sessione, collegamento", permission: "VIEW_DATA" },
  { href: "/settings/notifications", icon: "🔔", title: "Notifiche", hint: "Preferenze e notifiche push", permission: "VIEW_DATA" },
  { href: "/settings/profile", icon: "👤", title: "Profilo", hint: "Cambia password", permission: "VIEW_DATA" },
  { href: "/settings/templates", icon: "📝", title: "Template messaggi", hint: "Risposte rapide per la chat", permission: "MANAGE_TEMPLATES" },
  { href: "/settings/operations", icon: "🧰", title: "Operazioni", hint: "Coda azioni, sincronizzazioni, errori, audit", permission: "VIEW_OPERATIONS" },
  { href: "/settings/users", icon: "👥", title: "Utenti e ruoli", hint: "Crea, disabilita, modifica ruoli", permission: "MANAGE_USERS" },
  { href: "/settings/system", icon: "⚙️", title: "Sistema e privacy", hint: "Sincronizzazione, retention, dati locali", permission: "MANAGE_SETTINGS" },
];

export default function SettingsPage() {
  const { data: me } = useMe();
  const { data: connection } = useConnection();
  const client = useQueryClient();
  const router = useRouter();

  async function logout() {
    await api.post("/auth/logout").catch(() => undefined);
    client.clear();
    router.replace("/login");
  }

  return (
    <div>
      <PageHeader title="Impostazioni" />
      {me && (
        <div className="card mb-4 p-4">
          <p className="font-semibold">{me.name}</p>
          <p className="text-sm text-slate-500">
            {me.email} · {ROLE[me.role]}
          </p>
          {connection && (
            <div className="mt-3">
              <ConnectionLine connection={connection} />
            </div>
          )}
        </div>
      )}
      <ul className="card mb-4 divide-y divide-slate-100 dark:divide-slate-800">
        {SECTIONS.filter((s) => me?.permissions.includes(s.permission)).map((s) => (
          <li key={s.href}>
            <Link href={s.href} className="flex items-center gap-3 px-4 py-3.5 hover:bg-slate-50 dark:hover:bg-slate-800/50">
              <span className="text-xl">{s.icon}</span>
              <div className="min-w-0 flex-1">
                <p className="font-medium">{s.title}</p>
                <p className="truncate text-sm text-slate-500">{s.hint}</p>
              </div>
              <span className="text-slate-400">›</span>
            </Link>
          </li>
        ))}
      </ul>
      <button className="btn-secondary w-full" onClick={() => void logout()}>
        Esci
      </button>
      <p className="mt-6 text-center text-xs text-slate-400">
        Cardmarket Companion · app non ufficiale, non affiliata a Cardmarket
      </p>
    </div>
  );
}
